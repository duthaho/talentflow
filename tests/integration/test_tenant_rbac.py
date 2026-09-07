from fastapi.testclient import TestClient

from app.main import create_app


def bootstrap_tenant(client: TestClient, slug: str, admin_id: str) -> dict[str, str]:
    response = client.post(
        "/v1/tenants",
        json={"name": f"{slug.title()} HR", "slug": slug, "admin_id": admin_id},
    )
    assert response.status_code == 201
    return response.json()


def test_tenant_admin_can_create_a_requisition_and_audit_is_recorded() -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = bootstrap_tenant(client, "acme", "admin-1")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-1"}

        response = client.post(
            "/v1/requisitions",
            headers=headers,
            json={"title": "Senior Platform Engineer", "department": "Engineering"},
        )
        audit_response = client.get("/v1/audit-events", headers=headers)

    assert response.status_code == 201
    assert response.json()["title"] == "Senior Platform Engineer"
    assert audit_response.status_code == 200
    assert [event["action"] for event in audit_response.json()] == [
        "requisition.created",
        "tenant.created",
    ]


def test_user_cannot_access_another_tenant() -> None:
    with TestClient(create_app("sqlite://")) as client:
        acme = bootstrap_tenant(client, "acme", "admin-1")
        globex = bootstrap_tenant(client, "globex", "admin-2")
        response = client.post(
            "/v1/requisitions",
            headers={"X-Tenant-Id": globex["id"], "X-Actor-Id": "admin-1"},
            json={"title": "Recruiter", "department": "People"},
        )

    assert acme["id"] != globex["id"]
    assert response.status_code == 403
    assert response.json()["detail"] == "Actor is not a member of this tenant"
