import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.identity.security import ROLE_PERMISSIONS
from app.shared.models import Membership, User


def _create_context(
    client: TestClient, suffix: str, *, interviewer_id: str | None = None
) -> tuple[dict[str, str], dict[str, str], str]:
    recruiter_id = f"recruiter-{suffix}"
    interviewer_id = interviewer_id or f"interviewer-{suffix}"
    tenant = client.post(
        "/v1/tenants",
        json={"name": f"Tenant {suffix}", "slug": f"tenant-{suffix}", "admin_id": recruiter_id},
    ).json()
    recruiter_headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": recruiter_id}
    with client.app.state.session_factory() as session:
        if session.get(User, interviewer_id) is None:
            session.add(User(id=interviewer_id, email=f"{interviewer_id}@example.com"))
        session.add(Membership(tenant_id=tenant["id"], user_id=interviewer_id, role="interviewer"))
        session.commit()
    requisition = client.post(
        "/v1/requisitions",
        headers=recruiter_headers,
        json={"title": f"Engineer {suffix}", "department": "Engineering"},
    ).json()
    candidate = client.post(
        "/v1/candidate-cases",
        headers=recruiter_headers,
        json={
            "requisition_id": requisition["id"],
            "first_name": f"Candidate{suffix}",
            "last_name": "Example",
            "email": f"candidate-{suffix}@example.com",
        },
    ).json()
    return (
        recruiter_headers,
        {"X-Tenant-Id": tenant["id"], "X-Actor-Id": interviewer_id},
        candidate["id"],
    )


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


def _add_member(
    client: TestClient, tenant_id: str, user_id: str, role: str, email: str | None = None
) -> None:
    with client.app.state.session_factory() as session:
        if session.get(User, user_id) is None:
            session.add(User(id=user_id, email=email))
        session.add(Membership(tenant_id=tenant_id, user_id=user_id, role=role))
        session.commit()


def _cursor(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_manager_lists_interviews_with_keyset_pagination_feedback_and_tie_break() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, candidate_id = _create_context(client, "page")
        start = datetime(2026, 10, 1, 9, tzinfo=UTC)
        scheduled = [
            _schedule(client, recruiter_headers, candidate_id, "interviewer-page", start),
            _schedule(client, recruiter_headers, candidate_id, "interviewer-page", start),
            *[
                _schedule(
                    client,
                    recruiter_headers,
                    candidate_id,
                    "interviewer-page",
                    start + timedelta(days=day),
                )
                for day in range(1, 6)
            ],
        ]
        assert (
            client.post(
                f"/v1/interviews/{scheduled[0]['id']}/feedback",
                headers=interviewer_headers,
                json={"score": 4, "recommendation": "hire", "comments": "Strong"},
            ).status_code
            == 201
        )
        responses = []
        cursor = None
        while True:
            params = {"limit": 3}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get("/v1/interviews", headers=recruiter_headers, params=params)
            assert response.status_code == 200
            responses.append(response)
            cursor = response.json()["next_cursor"]
            if cursor is None:
                break

    pages = [response.json() for response in responses]
    assert responses[0].headers["Cache-Control"] == "private, no-store"
    assert pages[0]["total"] == 7
    items = [item for page in pages for item in page["items"]]
    assert [item["id"] for item in items] == [
        item["id"]
        for item in sorted(
            scheduled, key=lambda interview: (interview["scheduled_at"], interview["id"])
        )
    ]
    assert len({item["id"] for item in items}) == 7
    feedback_by_id = {item["id"]: item["feedback_submitted"] for item in items}
    assert feedback_by_id[scheduled[0]["id"]] is True
    assert all(
        not submitted
        for interview_id, submitted in feedback_by_id.items()
        if interview_id != scheduled[0]["id"]
    )
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


def test_tenant_and_shared_interviewer_scopes_never_cross_tenant() -> None:
    with TestClient(create_app("sqlite://")) as client:
        a_recruiter, a_interviewer, a_candidate = _create_context(
            client, "a", interviewer_id="shared"
        )
        b_recruiter, _, b_candidate = _create_context(client, "b", interviewer_id="shared")
        _schedule(client, a_recruiter, a_candidate, "shared", datetime(2026, 10, 1, tzinfo=UTC))
        _schedule(client, b_recruiter, b_candidate, "shared", datetime(2026, 10, 2, tzinfo=UTC))
        manager_page = client.get("/v1/interviews", headers=a_recruiter).json()
        own_pages = [
            client.get("/v1/interviews", headers=a_interviewer, params=params).json()
            for params in ({}, {"interviewer": "me"}, {"interviewer": "shared"})
        ]

    assert manager_page["total"] == 1
    assert manager_page["items"][0]["candidate_name"] == "Candidatea Example"
    assert all(page["total"] == 1 for page in own_pages)
    assert {page["items"][0]["candidate_case_id"] for page in own_pages} == {a_candidate}


def test_manager_can_filter_by_interviewer_or_self() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter, _, candidate = _create_context(client, "filter")
        tenant_id = recruiter["X-Tenant-Id"]
        _add_member(client, tenant_id, "interviewer-other", "interviewer", "other@example.com")
        _schedule(
            client, recruiter, candidate, "interviewer-filter", datetime(2026, 10, 1, tzinfo=UTC)
        )
        _schedule(
            client, recruiter, candidate, "interviewer-other", datetime(2026, 10, 2, tzinfo=UTC)
        )
        filtered = client.get(
            "/v1/interviews", headers=recruiter, params={"interviewer": "interviewer-other"}
        ).json()
        own = client.get("/v1/interviews", headers=recruiter, params={"interviewer": "me"}).json()

    assert [item["interviewer_id"] for item in filtered["items"]] == ["interviewer-other"]
    assert own == {"items": [], "next_cursor": None, "total": 0}


def test_interviewer_owns_only_own_interviews_and_forbidden_bodies_match() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter, interviewer, candidate = _create_context(client, "own")
        tenant_id = recruiter["X-Tenant-Id"]
        _add_member(client, tenant_id, "interviewer-other", "interviewer", "other@example.com")
        _schedule(
            client, recruiter, candidate, "interviewer-own", datetime(2026, 10, 1, tzinfo=UTC)
        )
        _schedule(
            client, recruiter, candidate, "interviewer-other", datetime(2026, 10, 2, tzinfo=UTC)
        )
        own = [
            client.get("/v1/interviews", headers=interviewer, params=params)
            for params in ({}, {"interviewer": "me"}, {"interviewer": "interviewer-own"})
        ]
        forbidden = [
            client.get(
                "/v1/interviews",
                headers={**interviewer, "X-Correlation-Id": "same-forbidden-request"},
                params={"interviewer": value},
            )
            for value in ("interviewer-other", "unknown", "", "ME", " me ")
        ]

    assert all(response.json()["total"] == 1 for response in own)
    assert {response.status_code for response in forbidden} == {403}
    assert len({json.dumps(response.json(), sort_keys=True) for response in forbidden}) == 1


def test_roles_without_permissions_cannot_list_interviews_or_interviewers() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter, _, _ = _create_context(client, "roles")
        tenant_id = recruiter["X-Tenant-Id"]
        for role in ("hiring_manager", "auditor"):
            user_id = f"{role}-roles"
            _add_member(client, tenant_id, user_id, role, f"{user_id}@example.com")
            headers = {"X-Tenant-Id": tenant_id, "X-Actor-Id": user_id}
            assert client.get("/v1/interviews", headers=headers).status_code == 403
            assert client.get("/v1/interviewers", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "value",
    [
        "!!!",
        _cursor("not-json"),
        _cursor([]),
        _cursor({"s": "2026-10-01T09:00:00+00:00"}),
        _cursor({"s": None, "i": 1}),
        _cursor({"s": [], "i": {}}),
        _cursor({"s": "2026-10-01T09:00:00", "i": "x"}),
        _cursor({"s": "0001-01-01T00:00:00+01:00", "i": "x"}),
        "x" * 513,
    ],
)
def test_invalid_cursors_return_generic_422(value: str) -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter, _, _ = _create_context(client, "cursor")
        response = client.get("/v1/interviews", headers=recruiter, params={"cursor": value})

    assert response.status_code == 422
    assert value not in response.json()["detail"]


@pytest.mark.parametrize("limit", [0, 101])
def test_invalid_limits_return_422(limit: int) -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter, _, _ = _create_context(client, f"limit-{limit}")
        assert (
            client.get("/v1/interviews", headers=recruiter, params={"limit": limit}).status_code
            == 422
        )


def test_cursor_replay_and_unknown_manager_filters_stay_scoped() -> None:
    with TestClient(create_app("sqlite://")) as client:
        a_recruiter, _, a_candidate = _create_context(client, "cursor-a")
        b_recruiter, _, b_candidate = _create_context(client, "cursor-b")
        _schedule(
            client,
            a_recruiter,
            a_candidate,
            "interviewer-cursor-a",
            datetime(2026, 10, 3, tzinfo=UTC),
        )
        _schedule(
            client,
            b_recruiter,
            b_candidate,
            "interviewer-cursor-b",
            datetime(2026, 10, 1, tzinfo=UTC),
        )
        _schedule(
            client,
            b_recruiter,
            b_candidate,
            "interviewer-cursor-b",
            datetime(2026, 10, 2, tzinfo=UTC),
        )
        b_cursor = client.get("/v1/interviews", headers=b_recruiter, params={"limit": 1}).json()[
            "next_cursor"
        ]
        replay = client.get("/v1/interviews", headers=a_recruiter, params={"cursor": b_cursor})
        unknown = [
            client.get("/v1/interviews", headers=a_recruiter, params={"interviewer": value})
            for value in ("unknown", "x" * 200)
        ]

    assert replay.status_code == 200
    assert replay.json()["items"][0]["candidate_case_id"] == a_candidate
    assert all(
        response.json() == {"items": [], "next_cursor": None, "total": 0} for response in unknown
    )


def test_interviewers_are_tenant_scoped_ordered_and_match_scheduling_roles() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter, interviewer, _ = _create_context(client, "members")
        tenant_id = recruiter["X-Tenant-Id"]
        with client.app.state.session_factory() as session:
            session.get(User, "interviewer-members").email = "one@example.com"
            session.commit()
        _add_member(client, tenant_id, "interviewer-null", "interviewer")
        other_recruiter, _, _ = _create_context(client, "members-b", interviewer_id="shared-member")
        _add_member(client, tenant_id, "shared-member", "recruiter", "shared@example.com")
        listed = client.get("/v1/interviewers", headers=recruiter)
        denied = client.get("/v1/interviewers", headers=interviewer)

    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "private, no-store"
    assert listed.json() == {
        "items": [
            {"id": "interviewer-members", "email": "one@example.com"},
            {"id": "interviewer-null", "email": None},
        ]
    }
    assert denied.status_code == 403
    assert other_recruiter["X-Tenant-Id"] != tenant_id
    assert ROLE_PERMISSIONS["interviewer"] == frozenset({"feedback:submit"})
    assert {
        role for role, permissions in ROLE_PERMISSIONS.items() if "feedback:submit" in permissions
    } == {"interviewer"}


def test_interviewer_cannot_read_candidate_cases() -> None:
    with TestClient(create_app("sqlite://")) as client:
        _, interviewer, _ = _create_context(client, "candidate-access")
        assert client.get("/v1/candidate-cases", headers=interviewer).status_code == 403
