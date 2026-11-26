from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.test_tenant_rbac import bootstrap_tenant


def _candidate(client: TestClient, headers: dict[str, str], email: str) -> dict[str, object]:
    requisition = client.post(
        "/v1/requisitions", headers=headers, json={"title": "Engineer", "department": "Platform"}
    ).json()
    response = client.post(
        "/v1/candidate-cases",
        headers=headers,
        json={
            "requisition_id": requisition["id"],
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": email,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_candidate_detail_reads_are_tenant_scoped_and_private() -> None:
    with TestClient(create_app("sqlite://")) as client:
        acme = bootstrap_tenant(client, "acme-detail", "admin-a")
        globex = bootstrap_tenant(client, "globex-detail", "admin-b")
        headers = {"X-Tenant-Id": acme["id"], "X-Actor-Id": "admin-a"}
        foreign_headers = {"X-Tenant-Id": globex["id"], "X-Actor-Id": "admin-b"}
        candidate = _candidate(client, headers, "ada@example.test")
        foreign = _candidate(client, foreign_headers, "grace@example.test")
        detail = client.get(f"/v1/candidate-cases/{candidate['id']}", headers=headers)
        foreign_detail = client.get(f"/v1/candidate-cases/{foreign['id']}", headers=headers)
        unknown = client.get("/v1/candidate-cases/missing", headers=headers)
        hold = client.get(f"/v1/candidate-cases/{candidate['id']}/legal-hold", headers=headers)
    assert detail.status_code == 200
    assert set(detail.json()) == {
        "id",
        "requisition_id",
        "first_name",
        "last_name",
        "email",
        "stage",
        "version",
        "created_at",
    }
    assert detail.headers["cache-control"] == "private, no-store"
    assert foreign_detail.status_code == unknown.status_code == 404
    assert hold.json() == {"held": False, "reason": None, "placed_at": None, "placed_by": None}


def test_case_timeline_redacts_metadata_and_validates_cursor() -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = bootstrap_tenant(client, "acme-timeline", "admin-a")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-a"}
        candidate = _candidate(client, headers, "ada.timeline@example.test")
        timeline = client.get(
            f"/v1/candidate-cases/{candidate['id']}/audit-events",
            headers=headers,
            params={"limit": 1},
        )
        invalid = client.get(
            f"/v1/candidate-cases/{candidate['id']}/audit-events",
            headers=headers,
            params={"cursor": "!"},
        )
    assert timeline.status_code == 200
    assert timeline.headers["cache-control"] == "private, no-store"
    assert timeline.json()["items"][0]["metadata"] == {
        "requisition_id": candidate["requisition_id"],
        "stage": "applied",
    }
    assert invalid.status_code == 422


def test_read_policies_return_null_when_unset_and_enforce_permissions() -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = bootstrap_tenant(client, "acme-policy", "admin-a")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-a"}
        policy = client.get("/v1/retention-policy", headers=headers)
        attachment_policy = client.get("/v1/attachment-policy", headers=headers)
        forbidden = client.get("/v1/retention-policy")
    assert policy.json() == {"retention_days": None}
    assert attachment_policy.status_code == 200
    assert attachment_policy.json()["allowed_content_types"] == sorted(
        attachment_policy.json()["allowed_content_types"]
    )
    assert forbidden.status_code == 403
