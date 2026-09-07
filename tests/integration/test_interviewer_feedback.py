from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import Membership, User


def setup_interview_context(client: TestClient) -> tuple[dict[str, str], dict[str, str], str]:
    tenant = client.post(
        "/v1/tenants",
        json={"name": "Acme HR", "slug": "acme", "admin_id": "recruiter-1"},
    ).json()
    recruiter_headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "recruiter-1"}
    with client.app.state.session_factory() as session:
        session.add(User(id="interviewer-1"))
        session.add(Membership(tenant_id=tenant["id"], user_id="interviewer-1", role="interviewer"))
        session.commit()
    requisition = client.post(
        "/v1/requisitions",
        headers=recruiter_headers,
        json={"title": "Senior Platform Engineer", "department": "Engineering"},
    ).json()
    candidate = client.post(
        "/v1/candidate-cases",
        headers=recruiter_headers,
        json={
            "requisition_id": requisition["id"],
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
        },
    ).json()
    return (
        recruiter_headers,
        {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "interviewer-1"},
        candidate["id"],
    )


def test_recruiter_schedules_interview_and_assigned_interviewer_submits_feedback() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, candidate_id = setup_interview_context(client)
        interview = client.post(
            f"/v1/candidate-cases/{candidate_id}/interviews",
            headers=recruiter_headers,
            json={"interviewer_id": "interviewer-1", "scheduled_at": "2026-10-01T09:00:00Z"},
        )
        feedback = client.post(
            f"/v1/interviews/{interview.json()['id']}/feedback",
            headers={**interviewer_headers, "X-Correlation-Id": "feedback-1"},
            json={
                "score": 5,
                "recommendation": "strong_hire",
                "comments": "Excellent systems thinking.",
            },
        )

    assert interview.status_code == 201
    assert interview.json()["scheduled_at"] == "2026-10-01T09:00:00Z"
    assert feedback.status_code == 201
    assert feedback.json()["score"] == 5
    assert feedback.json()["recommendation"] == "strong_hire"


def test_only_assigned_interviewer_can_submit_once() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, candidate_id = setup_interview_context(client)
        interview_id = client.post(
            f"/v1/candidate-cases/{candidate_id}/interviews",
            headers=recruiter_headers,
            json={
                "interviewer_id": "interviewer-1",
                "scheduled_at": datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
            },
        ).json()["id"]
        forbidden = client.post(
            f"/v1/interviews/{interview_id}/feedback",
            headers=recruiter_headers,
            json={"score": 3, "recommendation": "hire", "comments": "Not assigned"},
        )
        assert (
            client.post(
                f"/v1/interviews/{interview_id}/feedback",
                headers=interviewer_headers,
                json={"score": 3, "recommendation": "hire", "comments": "Good"},
            ).status_code
            == 201
        )
        duplicate = client.post(
            f"/v1/interviews/{interview_id}/feedback",
            headers=interviewer_headers,
            json={"score": 4, "recommendation": "strong_hire", "comments": "Updated"},
        )

    assert forbidden.status_code == 403
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Feedback has already been submitted"
