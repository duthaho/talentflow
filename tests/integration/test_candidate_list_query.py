from fastapi.testclient import TestClient

from app.main import create_app


def test_candidate_list_is_tenant_scoped_and_filterable() -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Acme", "slug": "acme", "admin_id": "admin"}
        ).json()
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        req = client.post(
            "/v1/requisitions", headers=headers, json={"title": "Engineer", "department": "Eng"}
        ).json()
        for email in ("ada@example.com", "grace@example.com"):
            client.post(
                "/v1/candidate-cases",
                headers=headers,
                json={
                    "requisition_id": req["id"],
                    "first_name": "Candidate",
                    "last_name": "One",
                    "email": email,
                },
            )
        first = client.get("/v1/candidate-cases", headers=headers, params={"limit": 1})
        assert first.status_code == 200
        assert len(first.json()["items"]) == 1
        assert first.json()["next_cursor"]
        second = client.get(
            "/v1/candidate-cases",
            headers=headers,
            params={"limit": 1, "cursor": first.json()["next_cursor"]},
        )
        assert len(second.json()["items"]) == 1
        filtered = client.get("/v1/candidate-cases", headers=headers, params={"stage": "applied"})
    assert filtered.json()["total"] == 2
