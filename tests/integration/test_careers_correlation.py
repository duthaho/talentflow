"""Anonymous intake must persist only the middleware-validated correlation ID."""

import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.modules.audit.persistence import AuditEvent
from app.shared.settings import Settings
from tests.integration.test_public_careers import apply
from tests.integration.test_tenant_rbac import bootstrap_tenant


@pytest.mark.parametrize(
    "database_url",
    [
        pytest.param("sqlite://", id="sqlite"),
        pytest.param(
            os.getenv("CAREERS_TEST_DATABASE_URL"),
            id="postgres",
            marks=pytest.mark.skipif(
                not os.getenv("CAREERS_TEST_DATABASE_URL"),
                reason="Requires disposable PostgreSQL",
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    "untrusted_id",
    [
        pytest.param("x" * 200, id="oversized"),
        pytest.param("forged <script>alert(1)</script>", id="invalid-characters"),
    ],
)
def test_apply_persists_validated_correlation_id(database_url, untrusted_id, tmp_path):
    app = create_app(
        database_url,
        Settings(
            app_env="test",
            attachment_storage_root=str(tmp_path),
            rate_limit_enabled=False,
        ),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        actor = "correlation-admin-" + uuid4().hex
        tenant = bootstrap_tenant(client, "correlation-" + uuid4().hex, actor)
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": actor}
        created = client.post(
            "/v1/requisitions", headers=headers, json={"title": "Engineer", "department": "QA"}
        )
        assert created.status_code == 201
        job = created.json()
        assert (
            client.patch(
                f"/v1/requisitions/{job['id']}/publication",
                headers=headers,
                json={"published": True},
            ).status_code
            == 200
        )
        context = (app, client, tenant, headers, job, tmp_path)
        response = apply(context, headers={"X-Correlation-Id": untrusted_id})
        assert response.status_code == 202
        validated_id = response.headers["x-correlation-id"]
        assert validated_id != untrusted_id
        UUID(validated_id)
        with app.state.session_factory() as session:
            events = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant["id"],
                    AuditEvent.actor_id == "system:careers",
                )
            ).all()
            assert {event.action for event in events} == {
                "candidate_case.created",
                "candidate_attachment.uploaded",
            }
            assert {event.correlation_id for event in events} == {validated_id}
