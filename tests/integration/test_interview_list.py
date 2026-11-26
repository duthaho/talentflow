from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import Membership, User
from tests.integration.test_interviewer_feedback import setup_interview_context


def _schedule(
    client: TestClient,
    headers: dict[str, str],
    candidate_id: str,
    interviewer_id: str,
    scheduled_at: datetime,
) -> dict[str, object]:
    response = client.post(
        f"/v1/candidate-cases/{candidate_id}/interviews",
        headers=headers,
        json={"interviewer_id": interviewer_id, "scheduled_at": scheduled_at.isoformat()},
    )
    assert response.status_code == 201
    return response.json()


def test_manager_lists_interviews_with_keyset_pagination_and_feedback_state() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, candidate_id = setup_interview_context(client)
        start = datetime(2026, 10, 1, 9, tzinfo=UTC)
        scheduled = [
            _schedule(
                client,
                recruiter_headers,
                candidate_id,
                "interviewer-1",
                start + timedelta(days=day),
            )
            for day in range(4)
        ]
        assert (
            client.post(
                f"/v1/interviews/{scheduled[0]['id']}/feedback",
                headers=interviewer_headers,
                json={"score": 4, "recommendation": "hire", "comments": "Strong"},
            ).status_code
            == 201
        )

        first = client.get("/v1/interviews", headers=recruiter_headers, params={"limit": 2})
        second = client.get(
            "/v1/interviews",
            headers=recruiter_headers,
            params={"limit": 2, "cursor": first.json()["next_cursor"]},
        )

    assert first.status_code == second.status_code == 200
    assert first.headers["Cache-Control"] == "private, no-store"
    assert first.json()["total"] == second.json()["total"] == 4
    assert second.json()["next_cursor"] is None
    items = first.json()["items"] + second.json()["items"]
    assert [item["id"] for item in items] == [item["id"] for item in scheduled]
    assert set(items[0]) == {
        "id",
        "candidate_case_id",
        "candidate_name",
        "requisition_title",
        "interviewer_id",
        "interviewer_email",
        "scheduled_at",
        "feedback_submitted",
    }
    assert items[0]["candidate_name"] == "Ada Lovelace"
    assert items[0]["feedback_submitted"] is True


def test_interviewer_only_sees_own_interviews_and_forbidden_values_match() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, candidate_id = setup_interview_context(client)
        tenant_id = recruiter_headers["X-Tenant-Id"]
        with client.app.state.session_factory() as session:
            session.add(User(id="interviewer-2", email="two@example.com"))
            session.add(
                Membership(tenant_id=tenant_id, user_id="interviewer-2", role="interviewer")
            )
            session.commit()
        _schedule(
            client,
            recruiter_headers,
            candidate_id,
            "interviewer-1",
            datetime(2026, 10, 1, tzinfo=UTC),
        )
        _schedule(
            client,
            recruiter_headers,
            candidate_id,
            "interviewer-2",
            datetime(2026, 10, 2, tzinfo=UTC),
        )
        own = client.get("/v1/interviews", headers=interviewer_headers)
        forbidden = [
            client.get("/v1/interviews", headers=interviewer_headers, params={"interviewer": value})
            for value in ("interviewer-2", "", "ME", " me ")
        ]

    assert own.status_code == 200
    assert own.json()["total"] == 1
    assert own.json()["items"][0]["interviewer_id"] == "interviewer-1"
    assert {response.status_code for response in forbidden} == {403}
    assert len({response.json()["detail"] for response in forbidden}) == 1


def test_interviewers_are_tenant_scoped_and_require_manage_permission() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, _ = setup_interview_context(client)
        tenant_id = recruiter_headers["X-Tenant-Id"]
        with client.app.state.session_factory() as session:
            session.get(User, "interviewer-1").email = "one@example.com"
            session.add(User(id="recruiter-in-other-tenant", email="other@example.com"))
            session.add(
                Membership(
                    tenant_id=tenant_id, user_id="recruiter-in-other-tenant", role="recruiter"
                )
            )
            session.commit()
        listed = client.get("/v1/interviewers", headers=recruiter_headers)
        denied = client.get("/v1/interviewers", headers=interviewer_headers)

    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "private, no-store"
    assert listed.json() == {"items": [{"id": "interviewer-1", "email": "one@example.com"}]}
    assert denied.status_code == 403


def test_list_rejects_invalid_cursor_without_echoing_it() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, _, _ = setup_interview_context(client)
        cursor = "x" * 513
        response = client.get(
            "/v1/interviews", headers=recruiter_headers, params={"cursor": cursor}
        )

    assert response.status_code == 422
    assert cursor not in response.json()["detail"]
