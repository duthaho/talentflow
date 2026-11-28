"""Tenant-scoped read model and audited administrative commands."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.onboarding.domain.policy import TASKS, can_cancel, can_retry
from app.modules.onboarding.infrastructure.models import Task
from app.modules.onboarding.infrastructure.repository import (
    add_steps,
    audit,
    compensation,
    steps_for,
)
from app.shared.concurrency import resolve_expected_version


def view(session, saga, *, enabled, may_manage):
    steps = steps_for(session, saga)
    tasks = session.scalars(
        select(Task).where(Task.saga_id == saga.id, Task.attempt == saga.attempt).order_by(Task.key)
    )
    return {
        "id": saga.id,
        "candidate_case_id": saga.candidate_case_id,
        "status": saga.status,
        "attempt": saga.attempt,
        "version": saga.version,
        "start_date": saga.start_date,
        "started_at": saga.started_at,
        "finished_at": saga.finished_at,
        "warning": saga.warning,
        "steps": [
            {
                "step": s.step,
                "status": s.status,
                "attempts": s.attempts,
                "last_error": s.last_error,
                "next_attempt_at": s.next_attempt_at,
                "completed_at": s.completed_at,
                "compensation_status": s.compensation_status,
            }
            for s in steps
        ],
        "tasks": [
            {"key": t.key, "title": TASKS[t.key], "due_date": t.due_date, "status": t.status}
            for t in tasks
        ],
        "actions": {
            "can_retry": enabled
            and may_manage
            and can_retry(saga.status, saga.attempt, saga.erased_at),
            "can_cancel": enabled
            and may_manage
            and can_cancel(saga.status, steps[2].status == "succeeded", saga.compensation_reason),
        },
    }


def command(session, saga, action, if_match, actor, correlation, now=None):
    now = now or datetime.now(UTC)
    resolve_expected_version(current_version=saga.version, expected_version=None, if_match=if_match)
    steps = steps_for(session, saga)
    allowed = (
        can_retry(saga.status, saga.attempt, saga.erased_at)
        if action == "retry"
        else can_cancel(saga.status, steps[2].status == "succeeded", saga.compensation_reason)
    )
    if not allowed:
        raise ValueError("action_not_allowed")
    saga.version += 1
    if action == "retry":
        saga.attempt += 1
        saga.status = "running"
        saga.compensation_reason = None
        saga.warning = None
        saga.finished_at = None
        saga.started_at = now
        add_steps(session, saga, now)
    else:
        saga.compensation_reason = "cancel_requested"
        compensation(session, saga, steps, now)
    audit(session, saga, "onboarding." + action + "_requested", actor, correlation)
    session.flush()
