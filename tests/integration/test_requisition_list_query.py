from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.organization.persistence import Membership


def create_tenant(client: TestClient, *, slug: str, admin_id: str) -> dict[str, str]:
    response = client.post(
        "/v1/tenants",
        json={"name": f"{slug.title()} HR", "slug": slug, "admin_id": admin_id},
    )
    assert response.status_code == 201
    return response.json()


def create_requisition(client: TestClient, headers: dict[str, str], title: str) -> dict[str, str]:
    response = client.post(
        "/v1/requisitions", headers=headers, json={"title": title, "department": "Engineering"}
    )
    assert response.status_code == 201
    return response.json()


def test_requisition_list_is_paginated_and_tenant_scoped() -> None:
    with TestClient(create_app("sqlite://")) as client:
        acme = create_tenant(client, slug="acme", admin_id="admin-1")
        acme_headers = {"X-Tenant-Id": acme["id"], "X-Actor-Id": "admin-1"}
        acme_requisitions = [
            create_requisition(client, acme_headers, title)
            for title in ("Backend Engineer", "Designer")
        ]
        globex = create_tenant(client, slug="globex", admin_id="admin-2")
        globex_headers = {"X-Tenant-Id": globex["id"], "X-Actor-Id": "admin-2"}
        create_requisition(client, globex_headers, "Recruiter")

        first = client.get("/v1/requisitions", headers=acme_headers, params={"limit": 1})
        assert first.status_code == 200
        assert first.json()["total"] == 2
        assert len(first.json()["items"]) == 1
        assert first.json()["next_cursor"]

        second = client.get(
            "/v1/requisitions",
            headers=acme_headers,
            params={"limit": 1, "cursor": first.json()["next_cursor"]},
        )

    assert second.status_code == 200
    assert second.json()["total"] == 2
    assert second.json()["next_cursor"] is None
    assert {item["id"] for item in first.json()["items"] + second.json()["items"]} == {
        requisition["id"] for requisition in acme_requisitions
    }


def test_requisition_list_requires_read_permission() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        tenant = create_tenant(client, slug="acme", admin_id="admin-1")
        with app.state.session_factory() as session:
            membership = (
                session.query(Membership).filter_by(tenant_id=tenant["id"], user_id="admin-1").one()
            )
            membership.role = "interviewer"
            session.commit()

        response = client.get(
            "/v1/requisitions",
            headers={"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-1"},
        )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 403
