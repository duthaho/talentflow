from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_onboarding import advance
from test_onboarding import process as process

from app.main import create_app
from app.modules.onboarding.infrastructure.models import Saga
from app.modules.organization.persistence import Membership, Tenant, User
from app.shared.settings import Settings


@pytest.fixture
def api(process):
    app = create_app(
        "sqlite://", Settings(auth_mode="development_headers", rate_limit_enabled=False)
    )
    with TestClient(app) as client:
        app.state.session_factory = process[0]
        yield app, client, {"X-Tenant-Id": process[5]["tenantid"], "X-Actor-Id": "hire"}


def ids(process):
    with process[0]() as s:
        return s.scalar(select(Saga)).id


def test_get_actions_and_preconditions(api, process):
    app, client, headers = api
    path = "/v1/onboarding-sagas/" + ids(process) + "/cancel"
    read = "/v1/candidate-cases/" + process[5]["subject"] + "/onboarding"
    body = client.get(read, headers=headers)
    assert body.status_code == 200, body.text
    assert body.json()["actions"] == {"can_retry": False, "can_cancel": True}
    assert body.headers["etag"] == '"1"'
    assert client.post(path, headers=headers).status_code == 428
    assert client.post(path, headers={**headers, "If-Match": '"999"'}).status_code == 412
    response = client.post(
        path, headers={**headers, "If-Match": '"1"', "Idempotency-Key": "cancel-1"}
    )
    assert response.status_code == 202, response.text
    replay = client.post(
        path, headers={**headers, "If-Match": '"1"', "Idempotency-Key": "cancel-1"}
    )
    assert replay.status_code == 202 and replay.headers["idempotent-replayed"] == "true"
    assert replay.json() == response.json()
    from app.modules.audit.persistence import AuditEvent

    with process[0]() as session:
        records = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "onboarding.cancel_requested")
            )
        )
        assert len(records) == 1 and records[0].actor_id == "hire" and records[0].correlation_id
    assert client.post(path, headers={**headers, "If-Match": '"2"'}).status_code == 409
    assert client.post(path).status_code == 401


def test_tenant_and_role_isolation_before_gate_and_headers(api, process):
    app, client, headers = api
    tenant = str(uuid4())
    with process[0].begin() as s:
        s.add(Tenant(id=tenant, name="Other", slug=tenant))
        s.add(User(id="other"))
        s.add(User(id="recruiter"))
        s.flush()
        s.add(Membership(tenant_id=tenant, user_id="other", role="tenant_admin"))
        s.add(Membership(tenant_id=headers["X-Tenant-Id"], user_id="recruiter", role="recruiter"))
    path = "/v1/onboarding-sagas/" + ids(process)
    read = "/v1/candidate-cases/" + process[5]["subject"] + "/onboarding"
    for action in ("retry", "cancel"):
        assert (
            client.post(
                path + "/" + action, headers={**headers, "X-Actor-Id": "recruiter"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                path + "/" + action, headers={"X-Tenant-Id": tenant, "X-Actor-Id": "other"}
            ).status_code
            == 404
        )
    assert (
        client.get(read, headers={"X-Tenant-Id": tenant, "X-Actor-Id": "other"}).status_code == 404
    )
    assert client.get(read, headers={**headers, "X-Actor-Id": "recruiter"}).json()["actions"] == {
        "can_retry": False,
        "can_cancel": False,
    }

    class Off:
        def is_enabled(self, *args):
            return False

    app.state.feature_flags.close()
    app.state.feature_flags = Off()
    app.state.feature_flags.close = lambda: None
    for action in ("retry", "cancel"):
        response = client.post(path + "/" + action, headers=headers)
        assert response.status_code == 403 and response.json()["feature"] == "onboarding"
    assert client.get(read, headers=headers).status_code == 200


def test_retry_preserves_history_and_caps_five(api, process):
    app, client, headers = api
    process[3].fail = {"create_employee"}
    assert advance(process) == "compensated"
    saga_id = ids(process)
    for attempt in range(2, 6):
        read = client.get(
            "/v1/candidate-cases/" + process[5]["subject"] + "/onboarding", headers=headers
        )
        response = client.post(
            "/v1/onboarding-sagas/" + saga_id + "/retry",
            headers={**headers, "If-Match": read.headers["etag"]},
        )
        assert response.status_code == 202, response.text
        assert response.json()["attempt"] == attempt
        assert advance(process) == "compensated"
    read = client.get(
        "/v1/candidate-cases/" + process[5]["subject"] + "/onboarding", headers=headers
    )
    assert not read.json()["actions"]["can_retry"]
    assert (
        client.post(
            "/v1/onboarding-sagas/" + saga_id + "/retry",
            headers={**headers, "If-Match": read.headers["etag"]},
        ).status_code
        == 409
    )


def test_start_date_validation_and_me_feature(api, process):
    app, client, headers = api
    path = "/v1/candidate-cases/" + process[5]["subject"] + "/stage"
    today = datetime.now(UTC).date()
    for target, value in [
        ("hired", today - timedelta(days=1)),
        ("hired", today + timedelta(days=366)),
        ("screening", today),
    ]:
        assert (
            client.patch(
                path,
                headers={**headers, "If-Match": '"1"'},
                json={"target_stage": target, "start_date": value.isoformat()},
            ).status_code
            == 422
        )
    assert client.get("/v1/me", headers=headers).json()["features"]["onboarding"] is True
