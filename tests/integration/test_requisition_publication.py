import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.modules.audit.persistence import AuditEvent
from app.modules.organization.persistence import Membership
from tests.integration.test_requisition_list_query import create_requisition, create_tenant


def test_publication_changes_are_audited_and_retries_are_noops() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = create_tenant(client, slug="acme", admin_id="admin-1")
        headers = {
            "X-Tenant-Id": tenant["id"],
            "X-Actor-Id": "admin-1",
            "X-Correlation-Id": "publication-test",
        }
        job = create_requisition(client, headers, "Engineer")
        assert job["published"] is False and job["published_at"] is None
        url = f"/v1/requisitions/{job['id']}/publication"
        assert client.patch(url, headers=headers, json={"published": False}).json() == job
        published = client.patch(url, headers=headers, json={"published": True})
        assert published.status_code == 200
        assert published.json()["published"] is True
        assert published.json()["published_at"] is not None
        assert (
            client.patch(url, headers=headers, json={"published": True}).json() == published.json()
        )
        listing = client.get("/v1/requisitions", headers=headers).json()
        assert listing["tenant_slug"] == "acme"
        assert listing["items"] == [published.json()]
        assert client.patch(url, headers=headers, json={"published": False}).json() == job
        assert client.patch(url, headers=headers, json={"published": False}).json() == job
        with app.state.session_factory() as session:
            events = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_(["requisition.published", "requisition.unpublished"])
                )
            ).all()
            assert sorted(event.action for event in events) == [
                "requisition.published",
                "requisition.unpublished",
            ]
            assert all(
                event.tenant_id == tenant["id"]
                and event.aggregate_id == job["id"]
                and event.actor_id == "admin-1"
                and event.correlation_id == "publication-test"
                for event in events
            )


@pytest.mark.parametrize("role", ["hiring_manager", "auditor", "interviewer"])
def test_publication_forbidden_and_cross_tenant_not_found(role: str) -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = create_tenant(client, slug="acme", admin_id="admin-1")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-1"}
        job = create_requisition(client, headers, "Engineer")
        url = f"/v1/requisitions/{job['id']}/publication"
        other = create_tenant(client, slug="other", admin_id="admin-2")
        assert (
            client.patch(
                url,
                headers={"X-Tenant-Id": other["id"], "X-Actor-Id": "admin-2"},
                json={"published": True},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/v1/requisitions/missing/publication", headers=headers, json={"published": True}
            ).status_code
            == 404
        )
        with app.state.session_factory() as session:
            membership = session.scalar(
                select(Membership).where(Membership.tenant_id == tenant["id"])
            )
            membership.role = role
            session.commit()
        response = client.patch(url, headers=headers, json={"published": True})
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "payload", [{}, {"published": None}, {"published": "true"}, {"published": 1}]
)
def test_publication_requires_a_boolean(payload: dict) -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = create_tenant(client, slug="acme", admin_id="admin-1")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-1"}
        job = create_requisition(client, headers, "Engineer")
        assert (
            client.patch(
                f"/v1/requisitions/{job['id']}/publication", headers=headers, json=payload
            ).status_code
            == 422
        )
