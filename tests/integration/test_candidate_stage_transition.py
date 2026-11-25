from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.candidates.infrastructure.models import CandidateCase
from app.shared.problem_details import PROBLEM_TYPE_BASE


def candidate_context(client: TestClient) -> tuple[dict[str, str], str]:
    tenant = client.post(
        "/v1/tenants",
        json={"name": "Acme HR", "slug": "acme", "admin_id": "recruiter-1"},
    ).json()
    headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "recruiter-1"}
    requisition = client.post(
        "/v1/requisitions",
        headers=headers,
        json={"title": "Senior Platform Engineer", "department": "Engineering"},
    ).json()
    candidate = client.post(
        "/v1/candidate-cases",
        headers=headers,
        json={
            "requisition_id": requisition["id"],
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
        },
    ).json()
    return headers, candidate["id"]


def test_recruiter_transitions_candidate_and_creates_audit_event() -> None:
    with TestClient(create_app("sqlite://")) as client:
        headers, candidate_id = candidate_context(client)
        response = client.patch(
            f"/v1/candidate-cases/{candidate_id}/stage",
            headers={**headers, "X-Correlation-Id": "workflow-test-1"},
            json={"target_stage": "screening", "expected_version": 1},
        )
        audit_events = client.get("/v1/audit-events", headers=headers).json()

    assert response.status_code == 200
    assert response.json()["stage"] == "screening"
    assert response.json()["version"] == 2
    assert audit_events[0] == {
        "id": audit_events[0]["id"],
        "action": "candidate_case.stage_transitioned",
        "aggregate_type": "candidate_case",
        "aggregate_id": candidate_id,
        "correlation_id": "workflow-test-1",
    }


def test_transition_rejects_invalid_stage_and_stale_version() -> None:
    with TestClient(create_app("sqlite://")) as client:
        headers, candidate_id = candidate_context(client)
        invalid = client.patch(
            f"/v1/candidate-cases/{candidate_id}/stage",
            headers=headers,
            json={"target_stage": "hired", "expected_version": 1},
        )
        assert invalid.status_code == 422
        assert (
            client.patch(
                f"/v1/candidate-cases/{candidate_id}/stage",
                headers=headers,
                json={"target_stage": "screening", "expected_version": 1},
            ).status_code
            == 200
        )
        stale = client.patch(
            f"/v1/candidate-cases/{candidate_id}/stage",
            headers=headers,
            json={"target_stage": "interviewing", "expected_version": 1},
        )

    assert invalid.json()["detail"] == "Invalid candidate stage transition: applied -> hired"
    assert invalid.json()["type"] == f"{PROBLEM_TYPE_BASE}validation-error"
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Candidate case has changed; refresh and retry"
    assert stale.json()["type"] == f"{PROBLEM_TYPE_BASE}version-conflict"
    assert stale.json()["current_version"] == 2


def test_transition_requires_tenant_member_with_permission() -> None:
    with TestClient(create_app("sqlite://")) as client:
        headers, candidate_id = candidate_context(client)
        response = client.patch(
            f"/v1/candidate-cases/{candidate_id}/stage",
            headers={"X-Tenant-Id": headers["X-Tenant-Id"], "X-Actor-Id": "unknown"},
            json={"target_stage": "screening", "expected_version": 1},
        )

    assert response.status_code == 403


def test_generic_stage_endpoint_cannot_bypass_offer_approval() -> None:
    app = create_app("sqlite://")
    with TestClient(app) as client:
        headers, candidate_id = candidate_context(client)
        for stage, version in (("screening", 1), ("interviewing", 2)):
            assert (
                client.patch(
                    f"/v1/candidate-cases/{candidate_id}/stage",
                    headers=headers,
                    json={"target_stage": stage, "expected_version": version},
                ).status_code
                == 200
            )

        for target_stage in ("offer_pending_approval", "offer_approved", "offer_rejected"):
            response = client.patch(
                f"/v1/candidate-cases/{candidate_id}/stage",
                headers=headers,
                json={"target_stage": target_stage, "expected_version": 3},
            )
            assert response.status_code == 422
            assert (
                response.json()["detail"]
                == "Offer stages can only be changed through the offers flow"
            )

        with app.state.session_factory() as session:
            candidate = session.get(CandidateCase, candidate_id)
            assert candidate is not None
            candidate.stage = "offer_approved"
            candidate.version = 4
            session.commit()

        hired = client.patch(
            f"/v1/candidate-cases/{candidate_id}/stage",
            headers=headers,
            json={"target_stage": "hired", "expected_version": 4},
        )

    assert hired.status_code == 422
    assert hired.json()["detail"] == "An approved offer is required before hiring a candidate"
