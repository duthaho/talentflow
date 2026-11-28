"""Process tests use real PostgreSQL connections; clocks and effect ports are controlled."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import app.shared.models  # noqa: F401
from app.modules.candidates.persistence import CandidateCase
from app.modules.onboarding.application.run_due import DueStepRunner
from app.modules.onboarding.infrastructure.models import Saga, Step, Task
from app.modules.onboarding.infrastructure.repository import (
    SqlAlchemySagaRepository,
    compensation,
    erase,
    steps_for,
)
from app.modules.organization.persistence import Membership, Requisition, Tenant, User
from app.shared.database import Base


@pytest.fixture
def process():
    url = os.getenv("ONBOARDING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set ONBOARDING_TEST_DATABASE_URL for disposable PostgreSQL")
    schema = "onboarding_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    tenant, case, req = [str(uuid4()) for _ in range(3)]
    with sessions.begin() as s:
        s.add(Tenant(id=tenant, name="Test", slug=tenant))
        s.add(User(id="hire", email="hire@example.test"))
        s.flush()
        s.add(Membership(tenant_id=tenant, user_id="hire", role="tenant_admin"))
        s.add(
            Requisition(
                id=req, tenant_id=tenant, created_by="hire", title="Engineer", department="IT"
            )
        )
        s.flush()
        s.add(
            CandidateCase(
                id=case,
                tenant_id=tenant,
                requisition_id=req,
                first_name="PrivateName",
                last_name="PrivateLast",
                email="private@example.test",
                stage="hired",
                created_by="hire",
                version=1,
            )
        )
    now = [datetime(2026, 11, 28, tzinfo=UTC)]
    event = {
        "id": str(uuid4()),
        "tenantid": tenant,
        "subject": case,
        "type": "candidate_case.stage_changed.v1",
        "time": now[0].isoformat(),
        "actorid": "hire",
        "data": {"to_stage": "hired"},
    }
    repo = SqlAlchemySagaRepository(sessions)
    with sessions.begin() as s:
        assert repo.start(s, event, now[0], True) == "started"
    effects = Effects()
    runner = DueStepRunner(repo, effects, effects, clock=lambda: now[0])
    yield sessions, repo, runner, effects, now, event
    engine.dispose()
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


class Effects:
    def __init__(self):
        self.calls = []
        self.fail = set()
        self.resources = {}

    async def effect(self, step, key, delete=False):
        self.calls.append(("undo_" if delete else "") + step)
        if ("undo_" if delete else "") + step in self.fail:
            raise RuntimeError("private@example.test")
        if delete:
            self.resources.pop((step, key), None)
            return None
        return self.resources.setdefault((step, key), str(uuid4()))

    async def upsert_employee(self, key, person):
        return await self.effect("create_employee", key)

    async def delete_employee(self, key):
        return await self.effect("create_employee", key, True)

    async def provision_user(self, case, key, person):
        return await self.effect("provision_account", key)

    async def delete_user(self, case, key):
        return await self.effect("provision_account", key, True)


def advance(process, terminal=True):
    sessions, repo, runner, effects, now, event = process
    for _ in range(60):
        runner.run_one()
        with sessions() as s:
            saga = s.scalar(select(Saga))
            due = s.scalar(select(Step.next_attempt_at).where(Step.next_attempt_at.is_not(None)))
            if due is None:
                return saga.status
        now[0] = max(now[0], due)
    raise AssertionError("did not reach a terminal state")


def test_happy_path_defaults_and_duplicate(process):
    sessions, repo, runner, effects, now, event = process
    with sessions.begin() as s:
        assert repo.start(s, {**event, "id": str(uuid4())}, now[0], True) == "duplicate"
    assert advance(process) == "completed"
    with sessions() as s:
        saga = s.scalar(select(Saga))
        tasks = list(s.scalars(select(Task)))
        assert saga.start_date == now[0].date() + timedelta(days=14)
        assert len(tasks) == 4
        from app.modules.notifications.persistence import NotificationDelivery

        deliveries = list(s.scalars(select(NotificationDelivery)))
        assert len(deliveries) == 1
        assert "PrivateName" not in str(deliveries[0].payload_json)
        assert deliveries[0].kind == "onboarding_ready"


@pytest.mark.parametrize(
    "step,undo",
    [
        ("create_employee", ["undo_create_employee"]),
        ("provision_account", ["undo_provision_account", "undo_create_employee"]),
        ("schedule_tasks", ["undo_provision_account", "undo_create_employee"]),
    ],
)
def test_compensation_in_reverse_order(process, step, undo):
    effects = process[3]
    if step == "schedule_tasks":
        process[1].faults = {step}
    else:
        effects.fail = {step}
    assert advance(process) == "compensated"
    assert [c for c in effects.calls if c.startswith("undo_")] == undo
    assert not effects.resources
    with process[0]() as s:
        assert s.scalar(select(CandidateCase)).stage == "hired"
        assert all("private" not in (step.last_error or "") for step in s.scalars(select(Step)))


def test_notify_is_past_pivot(process):
    process[1].faults = {"notify"}
    assert advance(process) == "completed_with_warnings"
    assert len(process[3].resources) == 2
    assert not any(c.startswith("undo_") for c in process[3].calls)


def test_compensation_failure_stops_automatic_work(process):
    process[1].faults = {"schedule_tasks"}
    process[3].fail = {"undo_provision_account"}
    assert advance(process) == "compensation_failed"
    with process[0].begin() as s:
        saga = s.scalar(select(Saga))
        erase(s, saga, process[4][0])
        from app.modules.audit.persistence import AuditEvent

        s.flush()

        assert (
            s.scalar(
                select(AuditEvent.action).where(
                    AuditEvent.action == "onboarding_erasure_cleanup_required"
                )
            )
            == "onboarding_erasure_cleanup_required"
        )


@pytest.mark.parametrize("position", [0, 1, 2, 3, 4])
def test_erasure_all_boundaries(process, position):
    for _ in range(position):
        process[2].run_one()
    with process[0].begin() as s:
        erase(s, s.scalar(select(Saga)), process[4][0])
    result = advance(process)
    assert result == (
        "cancelled"
        if position < 3
        else ("completed_with_warnings" if position == 3 else "completed")
    )
    if position < 3:
        assert not process[3].resources


def test_lease_fences_old_owner_and_reclaims_crash(process):
    sessions, repo, runner, effects, now, event = process
    claim = repo.claim(now[0])
    assert claim
    assert repo.claim(now[0]) is None
    now[0] += timedelta(seconds=35)
    replacement = repo.claim(now[0])
    assert replacement.owner != claim.owner
    assert not repo.record(claim, now[0], external_ref="stale")
    assert repo.record(replacement, now[0], external_ref="fresh")
    assert advance(process) == "completed"


def test_cancel_waits_for_in_flight_outcome(process):
    sessions, repo, runner, effects, now, event = process
    claim = repo.claim(now[0])
    with sessions.begin() as s:
        saga = s.scalar(select(Saga))
        saga.compensation_reason = "cancel_requested"
        compensation(s, saga, steps_for(s, saga), now[0])
    assert repo.claim(now[0]) is None
    assert repo.record(claim, now[0], external_ref="employee")
    assert advance(process) == "cancelled"
    assert effects.calls == ["undo_create_employee"]


def test_parallel_claim_skips_locked_saga(process):
    from threading import Event, Thread

    from sqlalchemy import event as sql_event

    engine = process[0].kw["bind"]
    claimed = Event()
    release = Event()
    results = []
    errors = []

    def pause(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE onboarding_sagas") and not claimed.is_set():
            claimed.set()
            assert release.wait(10)

    sql_event.listen(engine, "after_cursor_execute", pause)

    def first():
        try:
            results.append(process[1].claim(process[4][0]))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=first)
    thread.start()
    try:
        assert claimed.wait(10)
        assert process[1].claim(process[4][0]) is None
    finally:
        release.set()
        thread.join(10)
        sql_event.remove(engine, "after_cursor_execute", pause)
    assert not errors and len(results) == 1 and results[0]
    assert process[1].claim(process[4][0]) is None


def test_start_erase_race_is_serialized(process):
    from threading import Barrier, Thread

    from sqlalchemy import delete

    sessions, repo, runner, effects, now, event = process
    with sessions.begin() as s:
        s.execute(delete(Step))
        s.execute(delete(Saga))
    barrier = Barrier(2)
    errors = []

    def apply(ev):
        try:
            barrier.wait(10)
            with sessions.begin() as s:
                repo.start(s, ev, now[0], True)
        except BaseException as error:
            errors.append(error)

    threads = [
        Thread(target=apply, args=(ev,))
        for ev in (event, {**event, "id": str(uuid4()), "type": "candidate_case.erased.v1"})
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
        assert not thread.is_alive()
    assert not errors
    with sessions() as s:
        saga = s.scalar(select(Saga))
        assert saga is None or (saga.erased_at and saga.status == "cancelled")
    assert not effects.calls


def test_fake_timeout_boundary_and_deadline(process):
    from app.modules.onboarding.domain.policy import AttemptTimeout

    sessions, repo, runner, effects, now, event = process

    async def timeout(call, seconds):
        call.close()
        now[0] += timedelta(seconds=seconds)
        raise AttemptTimeout()

    runner.execute = timeout
    assert runner.run_one()
    with sessions() as s:
        step = s.scalar(select(Step).where(Step.position == 1))
        assert step.last_error == "AttemptTimeout"
        assert step.next_attempt_at == now[0] + timedelta(seconds=10)
        deadline = step.deadline_at
    assert not runner.run_one()
    now[0] = deadline
    assert runner.run_one()  # deadline transition counts as processed work
    from app.modules.onboarding.application.run_due import bounded

    runner.execute = bounded
    assert advance(process) == "compensated"
    assert effects.calls == ["undo_create_employee"]


def test_notify_no_recipients_and_anonymized_read(process):
    from sqlalchemy import delete

    with process[0].begin() as s:
        s.execute(delete(Membership))
    assert advance(process) == "completed_with_warnings"
    with process[0]() as s:
        assert s.scalar(select(Saga.warning)) == "no_recipients"


def test_consumer_flag_off_tombstone_and_untrusted_hire(process):
    from sqlalchemy import delete

    from app.modules.notifications.persistence import InboxMessage
    from app.modules.onboarding.infrastructure.consumer import OnboardingConsumer
    from app.modules.onboarding.infrastructure.models import Tombstone

    sessions, repo, runner, effects, now, event = process

    class Flags:
        def is_enabled(self, *args):
            return False

    consumer = OnboardingConsumer(sessions, None, repo, Flags(), clock=lambda: now[0])
    with sessions.begin() as s:
        s.execute(delete(Step))
        s.execute(delete(Saga))
    assert consumer.apply(event) == "skipped_flag_off"
    assert consumer.apply(event) == "duplicate"
    with sessions() as s:
        assert s.scalar(select(InboxMessage.event_id)) == event["id"]
        assert s.scalar(select(Saga)) is None
    # Enabling cannot replay an inboxed hire; R6 explicitly deletes that entry.
    consumer.flags.is_enabled = lambda *args: True
    assert consumer.apply(event) == "duplicate"
    with sessions.begin() as s:
        s.execute(delete(InboxMessage))
    assert consumer.apply(event) == "started"
    with sessions.begin() as s:
        s.execute(delete(Step))
        s.execute(delete(Saga))
    assert (
        consumer.apply({**event, "id": str(uuid4()), "type": "candidate_case.erased.v1"})
        == "erased"
    )
    assert consumer.apply({**event, "id": str(uuid4())}) == "skipped"
    with sessions() as s:
        assert s.get(Tombstone, (event["tenantid"], event["subject"]))
    with sessions.begin() as s:
        s.execute(delete(Tombstone))
        candidate = s.get(CandidateCase, event["subject"])
        candidate.stage = "applied"
    assert consumer.apply({**event, "id": str(uuid4())}) == "skipped"
    with sessions.begin() as s:
        s.get(CandidateCase, event["subject"]).stage = "hired"
        s.get(CandidateCase, event["subject"]).anonymized_at = now[0]
    assert consumer.apply({**event, "id": str(uuid4())}) == "skipped"


def test_erasure_after_crash_compensates_ambiguous_effect_without_candidate_read(process):
    sessions, repo, runner, effects, now, event = process
    claim = repo.claim(now[0])
    assert claim
    # The external effect succeeded, but the worker died before its record tx.
    import asyncio

    asyncio.run(effects.upsert_employee(claim.saga_id, claim.person))
    with sessions.begin() as s:
        erase(s, s.scalar(select(Saga)), now[0])
        s.get(CandidateCase, event["subject"]).anonymized_at = now[0]
    now[0] += timedelta(seconds=35)
    assert advance(process) == "cancelled"
    assert not effects.resources
    assert effects.calls == ["create_employee", "undo_create_employee"]


def test_commit_only_metrics_and_erasure_template(process):
    from app.modules.onboarding.infrastructure.metrics import refresh_running, running, sagas

    before = sagas.labels("completed")._value.get()
    assert advance(process) == "completed"
    assert sagas.labels("completed")._value.get() == before + 1
    process[2].run_one()
    assert sagas.labels("completed")._value.get() == before + 1
    refresh_running(process[0])
    assert running._value.get() == 0
    from app.modules.notifications.application.email_delivery import EmailDeliverySender
    from app.modules.notifications.persistence import NotificationDelivery

    with process[0].begin() as s:
        candidate = s.get(CandidateCase, process[5]["subject"])
        candidate.anonymized_at = process[4][0]
        delivery = s.scalar(select(NotificationDelivery))

    class Recorder:
        def send(self, **kwargs):
            self.message = kwargs

    adapter = Recorder()
    EmailDeliverySender(process[0], adapter)(delivery)
    assert "a new hire" in adapter.message["text"] and "PrivateName" not in adapter.message["text"]


def test_foreign_tenant_event_and_transaction_rollback_leave_no_saga(process):
    from app.modules.notifications.persistence import InboxMessage
    from app.modules.onboarding.infrastructure.consumer import OnboardingConsumer

    sessions, repo, runner, effects, now, event = process
    other = str(uuid4())
    with sessions.begin() as s:
        s.add(Tenant(id=other, name="Other", slug=other))

    class Flags:
        def is_enabled(self, *args):
            return True

    consumer = OnboardingConsumer(sessions, None, repo, Flags(), clock=lambda: now[0])
    forged = {**event, "id": str(uuid4()), "tenantid": other}
    assert consumer.apply(forged) == "skipped"
    with sessions() as s:
        assert s.scalar(select(Saga.id).where(Saga.tenant_id == other)) is None
    # Inbox and saga writes roll back together if process startup fails.
    original = repo.start

    def fail(*args):
        raise RuntimeError("transaction abort")

    repo.start = fail
    replay = {**event, "id": str(uuid4())}
    with pytest.raises(RuntimeError):
        consumer.apply(replay)
    with sessions() as s:
        assert s.get(InboxMessage, ("onboarding", replay["id"])) is None
    repo.start = original
    assert consumer.apply(replay) == "duplicate"
