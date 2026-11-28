"""PostgreSQL is the timer, lease and state store. Never hold a transaction over HTTP."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.modules.audit.persistence import AuditEvent
from app.modules.candidates.persistence import CandidateCase
from app.modules.notifications.persistence import NotificationDelivery
from app.modules.onboarding.application.ports import Claim
from app.modules.onboarding.domain.policy import (
    STEP_POLICIES,
    STEPS,
    TASKS,
    PermanentStepError,
    decide,
    on_outcome,
)
from app.modules.onboarding.infrastructure.models import Saga, Step, Task, Tombstone
from app.modules.organization.persistence import Membership, Requisition

logger = logging.getLogger(__name__)


def aware(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def insert_for(session):
    return pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert


def case_lock(session, tenant, case):
    if session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"onboarding:{tenant}:{case}"},
        )


def steps_for(session, saga):
    return list(
        session.scalars(
            select(Step)
            .where(Step.saga_id == saga.id, Step.attempt == saga.attempt)
            .order_by(Step.position)
        )
    )


def add_steps(session, saga, now):
    for position, name in enumerate(STEPS, 1):
        session.add(
            Step(
                saga_id=saga.id,
                tenant_id=saga.tenant_id,
                attempt=saga.attempt,
                step=name,
                position=position,
                next_attempt_at=now if position == 1 else None,
            )
        )


def audit(session, saga, action, actor, correlation):
    session.add(
        AuditEvent(
            tenant_id=saga.tenant_id,
            actor_id=actor,
            action=action,
            aggregate_type="onboarding_saga",
            aggregate_id=saga.id,
            correlation_id=correlation,
            metadata_json={"attempt": saga.attempt},
        )
    )


def finish(session, saga, status, now):
    saga.status, status_before = status, saga.status
    saga.finished_at = now
    # Defer metric publication until COMMIT; rollback must not report an outcome.
    if status_before != status:
        session.info.setdefault("onboarding_outcomes", []).append(status)


def compensation(session, saga, steps, now):
    """Leave an in-flight effect fenced until its result or lease expiry."""
    for step in steps:
        if step.status == "in_flight" and step.lease_owner:
            return
    saga.status = "compensating"
    for step in steps:
        if step.status in {"pending", "retry_wait"}:
            step.status = "not_run"
        step.next_attempt_at = None
    for step in reversed(steps[:3]):
        if step.status == "succeeded" and step.compensation_status != "done":
            step.compensation_status = "pending"
            step.next_attempt_at = now
            return
    finish(
        session,
        saga,
        on_outcome(
            step="",
            success=True,
            compensation=True,
            reason=saga.compensation_reason,
            erased=saga.erased_at is not None,
        ),
        now,
    )


def erase(session, saga, now):
    saga.erased_at = now
    saga.version += 1
    steps = steps_for(session, saga)
    if saga.status == "compensated":
        finish(session, saga, "cancelled", now)
    elif saga.status in {"running", "compensating"}:
        if steps[2].status == "succeeded":
            steps[3].status = "skipped"
            steps[3].next_attempt_at = None
            saga.warning = "candidate_erased"
            finish(session, saga, "completed_with_warnings", now)
        else:
            saga.compensation_reason = "candidate_erased"
            compensation(session, saga, steps, now)
    elif saga.status == "compensation_failed":
        audit(
            session,
            saga,
            "onboarding_erasure_cleanup_required",
            "system:onboarding",
            saga.correlation_id or str(uuid4()),
        )
        logger.warning("onboarding_erasure_cleanup_required", extra={"saga_id": saga.id})
        session.info["onboarding_cleanup"] = session.info.get("onboarding_cleanup", 0) + 1


class SqlAlchemySagaRepository:
    def __init__(self, sessions, *, faults=()):
        self.sessions, self.faults = sessions, set(faults)

    def start(self, session, event, now, enabled):
        tenant, case = event["tenantid"], event["subject"]
        case_lock(session, tenant, case)
        if event["type"] == "candidate_case.erased.v1":
            session.execute(
                insert_for(session)(Tombstone)
                .values(
                    tenant_id=tenant,
                    candidate_case_id=case,
                    erased_at=now,
                    source_event_id=event["id"],
                )
                .on_conflict_do_nothing()
            )
            saga = session.scalar(
                select(Saga)
                .where(Saga.tenant_id == tenant, Saga.candidate_case_id == case)
                .with_for_update()
            )
            if saga:
                erase(session, saga, now)
            return "erased"
        if event["data"].get("to_stage") != "hired":
            return "skipped"
        candidate = session.scalar(
            select(CandidateCase).where(CandidateCase.id == case, CandidateCase.tenant_id == tenant)
        )
        if candidate is None or candidate.stage != "hired" or candidate.anonymized_at is not None:
            return "skipped"
        if session.get(Tombstone, (tenant, case)):
            return "skipped"
        if not enabled:
            return "skipped_flag_off"
        if session.scalar(
            select(Saga.id).where(Saga.tenant_id == tenant, Saga.candidate_case_id == case)
        ):
            return "duplicate"
        saga = Saga(
            id=str(uuid4()),
            tenant_id=tenant,
            candidate_case_id=case,
            status="running",
            attempt=1,
            version=1,
            start_date=candidate.hire_start_date
            or (datetime.fromisoformat(event["time"]).astimezone(UTC).date() + timedelta(days=14)),
            hired_by=event.get("actorid"),
            source_event_id=event["id"],
            correlation_id=event.get("correlationid"),
            started_at=now,
        )
        session.add(saga)
        session.flush()
        add_steps(session, saga, now)
        return "started"

    def claim(self, now):
        with self.sessions.begin() as session:
            # Always lock saga before step, matching API/erasure lock order.
            saga = session.scalar(
                select(Saga)
                .join(Step, Step.saga_id == Saga.id)
                .where(
                    Saga.status.in_(["running", "compensating"]),
                    Step.attempt == Saga.attempt,
                    Step.next_attempt_at <= now,
                )
                .order_by(Step.next_attempt_at)
                .with_for_update(skip_locked=True, of=Saga)
                .limit(1)
            )
            if saga is None:
                return None
            steps = steps_for(session, saga)
            step = next(
                (s for s in steps if s.next_attempt_at and aware(s.next_attempt_at) <= now), None
            )
            if step is None:
                return None
            old_version = saga.version
            changed = session.execute(
                update(Saga)
                .where(Saga.id == saga.id, Saga.version == old_version)
                .values(version=old_version + 1)
            )
            if changed.rowcount != 1:
                return None
            undo = step.compensation_status in {"pending", "retry_wait", "in_flight"}
            if not undo and saga.compensation_reason and step.status != "in_flight":
                compensation(session, saga, steps, now)
                return None
            if not undo and step.deadline_at and aware(step.deadline_at) <= now:
                self._failure(
                    session, saga, step, steps, now, PermanentStepError("deadline_exceeded"), False
                )
                return None
            if step.deadline_at is None:
                step.deadline_at = now + timedelta(seconds=STEP_POLICIES[step.step].deadline)
            if undo:
                step.compensation_attempts += 1
                step.compensation_status = "in_flight"
            else:
                step.attempts += 1
                step.status = "in_flight"
            step.lease_owner = str(uuid4())
            step.next_attempt_at = now + timedelta(seconds=35)
            if step.step in {"schedule_tasks", "notify"}:
                # A savepoint rolls back local effects on failure, preserving claim state.
                try:
                    with session.begin_nested():
                        if step.step in self.faults:
                            raise RuntimeError("injected")
                        self._local(session, saga, step, now, undo)
                except Exception as error:
                    self._failure(session, saga, step, steps, now, error, undo)
                else:
                    self._success(session, saga, step, steps, now, None, undo)
                return None
            person = None
            if not undo:
                if saga.erased_at is not None:
                    saga.compensation_reason = "candidate_erased"
                    step.status = "not_run"
                    step.lease_owner = None
                    compensation(session, saga, steps, now)
                    return None
                candidate = session.scalar(
                    select(CandidateCase).where(
                        CandidateCase.id == saga.candidate_case_id,
                        CandidateCase.tenant_id == saga.tenant_id,
                    )
                )
                if candidate is None or candidate.anonymized_at is not None:
                    step.status = "not_run"
                    step.lease_owner = None
                    erase(session, saga, now)
                    return None
                person = {
                    "tenant_id": saga.tenant_id,
                    "candidate_case_id": saga.candidate_case_id,
                    "first_name": candidate.first_name,
                    "last_name": candidate.last_name,
                    "email": candidate.email,
                    "start_date": saga.start_date.isoformat(),
                }
            return Claim(
                step.id, step.lease_owner, saga.id, saga.candidate_case_id, step.step, undo, person
            )

    def record(self, claim, now, external_ref=None, error=None):
        with self.sessions.begin() as session:
            saga = session.scalar(select(Saga).where(Saga.id == claim.saga_id).with_for_update())
            step = session.get(Step, claim.step_id)
            if step is None or step.lease_owner != claim.owner:
                return False
            steps = steps_for(session, saga)
            saga.version += 1
            if error is None:
                self._success(session, saga, step, steps, now, external_ref, claim.compensation)
            else:
                self._failure(session, saga, step, steps, now, error, claim.compensation)
            return True

    def _success(self, session, saga, step, steps, now, ref, undo):
        step.lease_owner = None
        step.next_attempt_at = None
        step.last_error = None
        session.info.setdefault("onboarding_attempts", []).append(
            (step.step, "compensated" if undo else "succeeded")
        )
        if undo:
            step.compensation_status = "done"
            compensation(session, saga, steps, now)
            return
        step.status = "succeeded"
        step.completed_at = now
        if ref:
            step.external_ref = ref
        if saga.compensation_reason:
            compensation(session, saga, steps, now)
        elif step.step == "notify":
            finish(session, saga, "completed_with_warnings" if saga.warning else "completed", now)
        else:
            steps[step.position].next_attempt_at = now

    def _failure(self, session, saga, step, steps, now, error, undo):
        step.lease_owner = None
        code = error.code if isinstance(error, PermanentStepError) else type(error).__name__
        # Allow only symbolic error classes, even for arbitrary injected adapters.
        import re

        step.last_error = (
            code if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", code) else "StepError"
        )
        session.info.setdefault("onboarding_attempts", []).append((step.step, "failed"))
        decision = decide(
            now=now,
            deadline=aware(step.deadline_at),
            attempts=step.compensation_attempts if undo else step.attempts,
            step=step.step,
            compensation=undo,
            permanent=isinstance(error, PermanentStepError) and not undo,
        )
        step.next_attempt_at = decision.due_at
        if decision.action == "retry":
            if undo:
                step.compensation_status = "retry_wait"
            else:
                step.status = "retry_wait"
            if saga.compensation_reason and not undo:
                compensation(session, saga, steps, now)
        elif undo:
            step.compensation_status = "failed"
            finish(session, saga, "compensation_failed", now)
        elif step.step == "notify":
            step.status = "failed"
            saga.warning = "notify_exhausted"
            finish(session, saga, "completed_with_warnings", now)
        else:
            step.status = "failed"
            saga.compensation_reason = saga.compensation_reason or "step_failed"
            compensation(session, saga, steps, now)

    def _local(self, session, saga, step, now, undo):
        if step.step == "schedule_tasks":
            if undo:
                session.execute(
                    update(Task)
                    .where(Task.saga_id == saga.id, Task.attempt == saga.attempt)
                    .values(status="cancelled")
                )
            else:
                for key in TASKS:
                    session.execute(
                        insert_for(session)(Task)
                        .values(
                            id=str(uuid4()),
                            saga_id=saga.id,
                            tenant_id=saga.tenant_id,
                            attempt=saga.attempt,
                            key=key,
                            due_date=saga.start_date,
                            status="scheduled",
                            created_at=now,
                        )
                        .on_conflict_do_nothing()
                    )
        else:
            if saga.erased_at is not None:
                saga.warning = "candidate_erased"
                return
            candidate = session.scalar(
                select(CandidateCase).where(
                    CandidateCase.id == saga.candidate_case_id,
                    CandidateCase.tenant_id == saga.tenant_id,
                )
            )
            if candidate is None or candidate.anonymized_at is not None:
                saga.erased_at = now
                saga.warning = "candidate_erased"
                return
            requisition = session.get(Requisition, candidate.requisition_id)
            recipients = list(
                session.scalars(
                    select(Membership.user_id).where(
                        Membership.tenant_id == saga.tenant_id,
                        Membership.user_id.in_([saga.hired_by, requisition.created_by]),
                    )
                )
            )
            if not recipients:
                saga.warning = "no_recipients"
            for recipient in set(recipients):
                session.execute(
                    insert_for(session)(NotificationDelivery)
                    .values(
                        id=str(uuid4()),
                        tenant_id=saga.tenant_id,
                        recipient_id=recipient,
                        channel="email",
                        status="pending",
                        attempts=0,
                        kind="onboarding_ready",
                        dedup_key=f"onboarding:{saga.id}:{saga.attempt}:{recipient}",
                        payload_json={
                            "saga_id": saga.id,
                            "candidate_case_id": saga.candidate_case_id,
                            "start_date": saga.start_date.isoformat(),
                            "task_keys": list(TASKS),
                        },
                        created_at=now,
                    )
                    .on_conflict_do_nothing()
                )
