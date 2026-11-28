from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.attachments.application.attachment_service import ALLOWED_CONTENT_TYPES
from app.shared.models import Membership, User
from app.shared.problem_details import PROBLEM_TYPE_BASE
from app.shared.settings import Settings
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
        "hire_start_date",
        "source",
        "consent",
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


@pytest.mark.parametrize("suffix", ["", "/audit-events", "/legal-hold"])
def test_unknown_and_foreign_case_have_equivalent_problem_responses(suffix: str) -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = bootstrap_tenant(client, "acme-not-found", "admin-a")
        foreign = bootstrap_tenant(client, "globex-not-found", "admin-b")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin-a"}
        foreign_case = _candidate(
            client, {"X-Tenant-Id": foreign["id"], "X-Actor-Id": "admin-b"}, "foreign@example.test"
        )
        responses = [
            client.get(f"/v1/candidate-cases/{case_id}{suffix}", headers=headers)
            for case_id in ["missing", foreign_case["id"]]
        ]
        for response in responses:
            assert response.status_code == 404
            assert response.headers["content-type"] == "application/problem+json"
            assert response.json()["type"] == f"{PROBLEM_TYPE_BASE}not-found"
        bodies = [
            {
                key: value
                for key, value in response.json().items()
                if key not in {"instance", "correlation_id"}
            }
            for response in responses
        ]
        assert bodies[0] == bodies[1]


@pytest.mark.parametrize(
    ("role", "route"),
    [
        ("hiring_manager", "/v1/candidate-cases/{id}/audit-events"),
        ("hiring_manager", "/v1/candidate-cases/{id}/legal-hold"),
        ("hiring_manager", "/v1/retention-policy"),
        ("auditor", "/v1/candidate-cases/{id}/legal-hold"),
        ("auditor", "/v1/retention-policy"),
        ("interviewer", "/v1/candidate-cases/{id}"),
        ("interviewer", "/v1/attachment-policy"),
    ],
)
@pytest.mark.parametrize("exists", [True, False], ids=["real-case", "unknown-case"])
def test_read_route_permission_is_checked_before_case_lookup(
    role: str, route: str, exists: bool
) -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = bootstrap_tenant(client, "acme-forbidden", "admin")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        case = _candidate(client, headers, "permission@example.test")
        with client.app.state.session_factory() as session:
            session.add(User(id="restricted"))
            session.add(Membership(tenant_id=tenant["id"], user_id="restricted", role=role))
            session.commit()
        response = client.get(
            route.format(id=case["id"] if exists else "missing"),
            headers={**headers, "X-Actor-Id": "restricted"},
        )
        assert response.status_code == 403, response.text
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["type"] == f"{PROBLEM_TYPE_BASE}forbidden"


def test_attachment_policy_uses_runtime_override_and_exact_sorted_types() -> None:
    app = create_app("sqlite://", app_settings=Settings(app_env="test", attachment_max_bytes=1234))
    with TestClient(app) as client:
        tenant = bootstrap_tenant(client, "acme-override", "admin")
        response = client.get(
            "/v1/attachment-policy",
            headers={"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "max_bytes": 1234,
        "allowed_content_types": sorted(ALLOWED_CONTENT_TYPES),
    }


@pytest.mark.parametrize(("suffix", "field"), [("", "created_at"), ("/legal-hold", "placed_at")])
def test_candidate_read_timestamps_have_utc_offset(suffix: str, field: str) -> None:
    with TestClient(create_app("sqlite://")) as client:
        tenant = bootstrap_tenant(client, "acme-timestamp", "admin")
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        case = _candidate(client, headers, "timestamp@example.test")
        route = f"/v1/candidate-cases/{case['id']}{suffix}"
        if suffix:
            placed = client.put(route, headers=headers, json={"held": True, "reason": "Test hold"})
            assert placed.status_code == 204
        response = client.get(route, headers=headers)
        assert response.status_code == 200
        assert datetime.fromisoformat(response.json()[field]).utcoffset() == timedelta(0)
