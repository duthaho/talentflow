from fastapi.testclient import TestClient

from app.main import create_app


def bootstrap_tenant(client: TestClient) -> tuple[dict[str, str], dict[str, str]]:
    tenant_response = client.post(
        "/v1/tenants",
        json={"name": "Acme HR", "slug": "acme", "admin_id": "recruiter-1"},
    )
    assert tenant_response.status_code == 201
    tenant = tenant_response.json()
    return tenant, {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "recruiter-1"}


def create_requisition(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    response = client.post(
        "/v1/requisitions",
        headers=headers,
        json={"title": "Senior Platform Engineer", "department": "Engineering"},
    )
    assert response.status_code == 201
    return response.json()


def test_recruiter_creates_candidate_case_for_tenant_requisition() -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant, headers = bootstrap_tenant(client)
        requisition = create_requisition(client, headers)
        response = client.post(
            "/v1/candidate-cases",
            headers=headers,
            json={
                "requisition_id": requisition["id"],
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ADA@EXAMPLE.COM",
            },
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "requisition_id": requisition["id"],
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
        "stage": "applied",
        "version": 1,
    }
    assert tenant["id"]


def test_candidate_email_is_unique_per_tenant() -> None:
    with TestClient(create_app("sqlite://")) as client:
        _, headers = bootstrap_tenant(client)
        requisition = create_requisition(client, headers)
        payload = {
            "requisition_id": requisition["id"],
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
        }
        assert client.post("/v1/candidate-cases", headers=headers, json=payload).status_code == 201
        duplicate = client.post("/v1/candidate-cases", headers=headers, json=payload)

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Candidate email already exists in this tenant"


def test_candidate_case_rejects_requisition_from_another_tenant() -> None:
    with TestClient(create_app("sqlite://")) as client:
        _, acme_headers = bootstrap_tenant(client)
        acme_requisition = create_requisition(client, acme_headers)
        globex_response = client.post(
            "/v1/tenants",
            json={"name": "Globex HR", "slug": "globex", "admin_id": "recruiter-2"},
        )
        globex_headers = {
            "X-Tenant-Id": globex_response.json()["id"],
            "X-Actor-Id": "recruiter-2",
        }
        response = client.post(
            "/v1/candidate-cases",
            headers=globex_headers,
            json={
                "requisition_id": acme_requisition["id"],
                "first_name": "Grace",
                "last_name": "Hopper",
                "email": "grace@example.com",
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Requisition not found"
