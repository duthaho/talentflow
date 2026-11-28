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
        ("create_employee", []),
        ("provision_account", ["undo_create_employee"]),
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

        assert s.scalar(select(AuditEvent.action)) == "onboarding_erasure_cleanup_required"


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
