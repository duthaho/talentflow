from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.modules.candidates.application.create_candidate import CreateCandidateHandler
from app.modules.candidates.domain.candidate_case import CandidateCase as DomainCandidate
from app.shared.idempotency import IdempotencyRecord
from app.shared.models import AuditEvent, CandidateCase, Membership, Requisition, User
from app.shared.settings import Settings

PAYLOAD = {"title": "Engineer", "department": "Engineering"}


def bootstrap(client):
    actor = f"admin-{uuid4()}"
    response = client.post(
        "/v1/tenants",
        json={
            "name": "Idempotency test",
            "slug": f"idem-{uuid4()}",
            "admin_id": actor,
        },
    )
    assert response.status_code == 201, response.text
    return {"X-Tenant-Id": response.json()["id"], "X-Actor-Id": actor}


@pytest.fixture
def context():
    app = create_app("sqlite://", Settings(app_env="test", rate_limit_enabled=False))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client, bootstrap(client)


def post(client, headers, *, key="retry-1", payload=None, path="/v1/requisitions"):
    return client.post(path, headers={**headers, "Idempotency-Key": key}, json=payload or PAYLOAD)


def test_replay_canonical_json_without_extra_writes(context):
    app, client, headers = context
    first = post(client, headers)
    replay = client.post(
        "/v1/requisitions",
        headers={**headers, "Idempotency-Key": "retry-1", "Content-Type": "application/json"},
        content=' { "department": "Engineering", "title": "Engineer" } ',
    )
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert first.headers["Content-Type"] == replay.headers["Content-Type"]
    with app.state.session_factory() as session:
        assert session.query(Requisition).count() == 1
        assert session.query(AuditEvent).filter_by(action="requisition.created").count() == 1
        record = session.query(IdempotencyRecord).one()
        assert record.state == "completed"
        assert set(record.headers) == {"content-type"}


def test_body_and_route_mismatch(context):
    _, client, headers = context
    assert post(client, headers).status_code == 201
    mismatch = post(client, headers, payload={**PAYLOAD, "title": "Another"})
    assert mismatch.status_code == 422
    assert mismatch.headers["Content-Type"].startswith("application/problem+json")
    mismatch = post(client, headers, path="/v1/retention/purge")
    assert mismatch.status_code == 422


@pytest.mark.parametrize("key", ["", "has space", "\t", "\x00", "a" * 256, b"\xff"])
def test_malformed_keys(context, key):
    app, client, headers = context
    response = post(client, headers, key=key)
    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/problem+json")
    with app.state.session_factory() as session:
        assert session.query(IdempotencyRecord).count() == 0
        assert session.query(Requisition).count() == 0


def test_key_without_header_and_maximum_length(context):
    app, client, headers = context
    for _ in range(2):
        assert client.post("/v1/requisitions", headers=headers, json=PAYLOAD).status_code == 201
    assert post(client, headers, key="!" * 255).status_code == 201
    assert post(client, headers, key="!" * 255).headers["Idempotent-Replayed"] == "true"
    with app.state.session_factory() as session:
        assert session.query(Requisition).count() == 3
        assert session.query(IdempotencyRecord).count() == 1


def test_scope_isolates_actors_and_tenants(context):
    app, client, headers = context
    assert post(client, headers).status_code == 201
    other_actor = f"recruiter-{uuid4()}"
    with app.state.session_factory() as session:
        session.add(User(id=other_actor))
        session.add(
            Membership(tenant_id=headers["X-Tenant-Id"], user_id=other_actor, role="recruiter")
        )
        session.commit()
    second = post(client, {**headers, "X-Actor-Id": other_actor})
    third = post(client, bootstrap(client))
    assert second.status_code == third.status_code == 201
    assert "Idempotent-Replayed" not in second.headers
    assert "Idempotent-Replayed" not in third.headers
    with app.state.session_factory() as session:
        assert session.query(IdempotencyRecord).count() == 3


def test_replay_rechecks_permission_and_membership(context):
    app, client, headers = context
    assert post(client, headers).status_code == 201
    with app.state.session_factory() as session:
        membership = session.scalar(
            select(Membership).where(Membership.user_id == headers["X-Actor-Id"])
        )
        membership.role = "auditor"
        session.commit()
    assert post(client, headers).status_code == 403
    with app.state.session_factory() as session:
        session.delete(session.scalar(select(Membership)))
        session.commit()
    assert post(client, headers).status_code == 403


def test_expired_key_runs_again(context):
    app, client, headers = context
    first = post(client, headers)
    with app.state.session_factory() as session:
        session.query(IdempotencyRecord).one().expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    second = post(client, headers)
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    with app.state.session_factory() as session:
        assert session.query(IdempotencyRecord).count() == 1


def test_purge_summary_replays_with_no_body(context):
    app, client, headers = context
    args = {"headers": {**headers, "Idempotency-Key": "purge"}}
    first = client.post("/v1/retention/purge", **args)
    second = client.post("/v1/retention/purge", **args)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"purged_count": 0}
    assert second.headers["Idempotent-Replayed"] == "true"


@pytest.mark.parametrize("failure", ["not-found", "server-error", "validation"])
def test_failed_handler_releases_key(context, monkeypatch, failure):
    app, client, headers = context
    requisition = post(client, headers, key="setup").json()
    payload = {
        "requisition_id": requisition["id"],
        "first_name": "Ada",
        "last_name": "Test",
        "email": "ada@example.test",
    }
    original = CreateCandidateHandler.handle
    if failure == "not-found":
        bad_payload = {**payload, "requisition_id": str(uuid4())}
        expected = 404
    elif failure == "validation":
        bad_payload = {**payload, "email": ""}
        expected = 422
    else:

        def fail(self, command):
            self._candidates.add(
                candidate=DomainCandidate.open(
                    tenant_id=command.tenant_id, requisition_id=command.requisition_id
                ),
                first_name="Rollback",
                last_name="Test",
                email="rollback@example.test",
                created_by=command.actor_id,
            )
            self._candidates._session.flush()
            raise RuntimeError("injected failure before commit")

        monkeypatch.setattr(CreateCandidateHandler, "handle", fail)
        bad_payload, expected = payload, 500
    response = post(
        client, headers, path="/v1/candidate-cases", key="candidate", payload=bad_payload
    )
    assert response.status_code == expected, response.text
    with app.state.session_factory() as session:
        assert session.query(IdempotencyRecord).filter_by(key="candidate").count() == 0
        assert session.query(CandidateCase).count() == 0
    monkeypatch.setattr(CreateCandidateHandler, "handle", original)
    response = post(client, headers, path="/v1/candidate-cases", key="candidate", payload=payload)
    assert response.status_code == 201, response.text
    assert (
        post(client, headers, path="/v1/candidate-cases", key="candidate", payload=payload).headers[
            "Idempotent-Replayed"
        ]
        == "true"
    )


def test_finalization_failure_keeps_committed_reservation(context, monkeypatch):
    app, client, headers = context
    import app.api.idempotency as seam

    def crash(*args):
        raise RuntimeError("injected response storage failure")

    monkeypatch.setattr(seam, "_complete", crash)
    assert post(client, headers).status_code == 500
    retry = post(client, headers)
    assert retry.status_code == 409
    assert retry.headers["Retry-After"] == "1"
    with app.state.session_factory() as session:
        assert session.query(Requisition).count() == 1
        assert session.query(IdempotencyRecord).one().state == "in_progress"


def test_openapi_coverage_and_exclusions(context):
    _, client, _ = context
    schema = client.get("/openapi.json").json()
    excluded = {
        "/v1/tenants",
        "/v1/calendar-subscriptions",
        "/v1/candidate-cases/{candidate_case_id}/attachments",
    }
    for path, operations in schema["paths"].items():
        if "post" not in operations:
            continue
        operation = operations["post"]
        keys = [p for p in operation.get("parameters", []) if p["name"] == "Idempotency-Key"]
        if path in excluded:
            assert not keys
            assert "Idempotency-Key is ignored" in operation["description"]
        else:
            assert len(keys) == 1, path
            assert not keys[0]["required"]


def test_keyed_bodyless_command_rejects_invalid_json(context):
    app, client, headers = context
    response = client.post(
        "/v1/retention/purge",
        headers={**headers, "Idempotency-Key": "invalid-body"},
        content="invalid json",
    )
    assert response.status_code == 422
    assert response.headers["Content-Type"].startswith("application/problem+json")
    with app.state.session_factory() as session:
        assert session.query(IdempotencyRecord).count() == 0


def test_bootstrap_ignores_malformed_idempotency_header(context):
    app, client, _ = context
    response = client.post(
        "/v1/tenants",
        headers={"Idempotency-Key": "invalid key"},
        json={"name": "Bootstrap", "slug": "excluded-bootstrap", "admin_id": "new-admin"},
    )
    assert response.status_code == 201
    with app.state.session_factory() as session:
        assert session.query(IdempotencyRecord).count() == 0
