"""Run with DATABASE_URL pointing at an isolated, migrated PostgreSQL test DB."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.main import create_app
from app.modules.candidates.application.create_candidate import CreateCandidateHandler
from app.modules.offers.application.decide_offer import DecideOfferHandler
from app.shared.idempotency import IdempotencyRecord
from app.shared.models import (
    ApprovalDecision,
    AuditEvent,
    CandidateCase,
    Membership,
    OutboxEvent,
    User,
)
from app.shared.settings import Settings

POSTGRES_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL.startswith("postgresql"), reason="requires PostgreSQL DATABASE_URL"
)


@pytest.mark.parametrize("command", ["candidate", "approval"])
@pytest.mark.parametrize("timeout", [False, True], ids=["wait-for-commit", "lock-timeout"])
def test_parallel_commands_execute_once_across_api_instances(monkeypatch, command, timeout):
    settings = Settings(app_env="test", rate_limit_enabled=False)
    first_app = create_app(POSTGRES_URL, settings)
    second_app = create_app(POSTGRES_URL, settings)
    with TestClient(first_app) as first, TestClient(second_app) as second:
        suffix = uuid4().hex
        admin, manager = f"admin-{suffix}", f"manager-{suffix}"
        tenant = first.post(
            "/v1/tenants", json={"name": "Concurrency", "slug": suffix, "admin_id": admin}
        ).json()
        tenant_id = tenant["id"]
        headers = {"X-Tenant-Id": tenant_id, "X-Actor-Id": admin}
        requisition = first.post(
            "/v1/requisitions", headers=headers, json={"title": "Engineer", "department": "Eng"}
        ).json()
        path = "/v1/candidate-cases"
        payload = {
            "requisition_id": requisition["id"],
            "first_name": "Test",
            "last_name": "Candidate",
            "email": f"{suffix}@example.test",
        }
        handler = CreateCandidateHandler
        if command == "approval":
            with first_app.state.session_factory() as session:
                session.add(User(id=manager))
                session.flush()
                session.add(Membership(tenant_id=tenant_id, user_id=manager, role="hiring_manager"))
                session.commit()
            candidate = first.post(path, headers=headers, json=payload).json()
            for stage, version in [("screening", 1), ("interviewing", 2)]:
                result = first.patch(
                    f"/v1/candidate-cases/{candidate['id']}/stage",
                    headers=headers,
                    json={"target_stage": stage, "expected_version": version},
                )
                assert result.status_code == 200
            offer = first.post(
                f"/v1/candidate-cases/{candidate['id']}/offers",
                headers=headers,
                json={"title": "Engineer", "annual_salary": 100000, "currency": "USD"},
            ).json()
            path = f"/v1/offers/{offer['id']}/approvals"
            headers["X-Actor-Id"] = manager
            payload = {"decision": "approved", "expected_version": 1}
            handler = DecideOfferHandler

        entered, release, duplicate_insert = Event(), Event(), Event()
        executions = []
        original = handler.handle

        def blocked(self, value):
            executions.append(value)
            entered.set()
            assert release.wait(20), "test did not release the first transaction"
            return original(self, value)

        monkeypatch.setattr(handler, "handle", blocked)

        def inserting(connection, cursor, statement, parameters, context, many):
            if statement.startswith("INSERT INTO idempotency_records"):
                duplicate_insert.set()

        event.listen(
            second_app.state.session_factory.kw["bind"], "before_cursor_execute", inserting
        )
        headers["Idempotency-Key"] = f"parallel-{suffix}"
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_first = pool.submit(first.post, path, headers=headers, json=payload)
            try:
                assert entered.wait(10), "first request did not reach the handler"
                pending_second = pool.submit(second.post, path, headers=headers, json=payload)
                assert duplicate_insert.wait(10), "second API did not attempt the reservation"
                if timeout:
                    other = pending_second.result(timeout=12)
                    assert other.status_code == 409, other.text
                    assert other.headers["Retry-After"] == "1"
                release.set()
                result = pending_first.result(timeout=10)
                other = pending_second.result(timeout=10)
            finally:
                release.set()
        assert result.status_code in {200, 201}, result.text
        assert other.status_code in {result.status_code, 409}, other.text
        if other.status_code != 409:
            assert other.headers["Idempotent-Replayed"] == "true"
            assert other.json() == result.json()
        replay = second.post(path, headers=headers, json=payload)
        assert replay.status_code == result.status_code
        assert replay.json() == result.json()
        assert replay.headers["Idempotent-Replayed"] == "true"
        assert len(executions) == 1
        with first_app.state.session_factory() as session:
            assert session.query(CandidateCase).filter_by(tenant_id=tenant_id).count() == 1
            assert (
                session.query(AuditEvent)
                .filter_by(tenant_id=tenant_id, action="candidate_case.created")
                .count()
                == 1
            )
            assert session.query(ApprovalDecision).filter_by(tenant_id=tenant_id).count() == (
                1 if command == "approval" else 0
            )
            assert session.query(OutboxEvent).filter_by(tenant_id=tenant_id).count() == (
                1 if command == "approval" else 0
            )
            record = session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.tenant_id == tenant_id)
            )
            assert record.state == "completed"
