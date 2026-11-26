from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.models import Membership, User
from tests.integration.test_interviewer_feedback import setup_interview_context


def test_interviewer_calendar_feed_is_private_revokable_and_contains_scheduled_interviews() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, _, candidate_id = setup_interview_context(client)
        scheduled = client.post(
            f"/v1/candidate-cases/{candidate_id}/interviews",
            headers=recruiter_headers,
            json={"interviewer_id": "interviewer-1", "scheduled_at": "2026-10-01T09:00:00Z"},
        )
        subscription = client.post(
            "/v1/calendar-subscriptions",
            headers=recruiter_headers,
            json={"interviewer_id": "interviewer-1"},
        )
        feed_url = subscription.json()["feed_url"]
        feed = client.get(feed_url)
        revoked = client.delete(
            f"/v1/calendar-subscriptions/{subscription.json()['id']}", headers=recruiter_headers
        )
        revoked_feed = client.get(feed_url)

    assert scheduled.status_code == 201
    assert subscription.status_code == 201
    assert "/v1/calendar-feeds/" in feed_url
    assert feed.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in feed.text
    assert "UID:" + scheduled.json()["id"] + "@talentflow" in feed.text
    assert "DTSTART:20261001T090000Z" in feed.text
    assert "DTEND:20261001T100000Z" in feed.text
    assert "SUMMARY:TalentFlow interview" in feed.text
    assert "Ada" not in feed.text
    assert revoked.status_code == 204
    assert revoked_feed.status_code == 404


def test_calendar_subscription_requires_a_tenant_interviewer() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, _, _ = setup_interview_context(client)
        response = client.post(
            "/v1/calendar-subscriptions",
            headers=recruiter_headers,
            json={"interviewer_id": "not-a-member"},
        )

    assert response.status_code == 404


def test_interviewer_can_create_list_and_revoke_only_own_subscriptions() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, _ = setup_interview_context(client)
        with client.app.state.session_factory() as session:
            session.add(User(id="interviewer-2"))
            session.add(
                Membership(
                    tenant_id=interviewer_headers["X-Tenant-Id"],
                    user_id="interviewer-2",
                    role="interviewer",
                )
            )
            session.commit()

        own = client.post("/v1/calendar-subscriptions", headers=interviewer_headers, json={})
        other = client.post(
            "/v1/calendar-subscriptions",
            headers=recruiter_headers,
            json={"interviewer_id": "interviewer-2"},
        )
        denied_create = client.post(
            "/v1/calendar-subscriptions",
            headers=interviewer_headers,
            json={"interviewer_id": "interviewer-2", "scope": "manage"},
        )
        listed = client.get(
            "/v1/calendar-subscriptions?interviewer=me", headers=interviewer_headers
        )
        denied_list = client.get(
            "/v1/calendar-subscriptions?interviewer=interviewer-2", headers=interviewer_headers
        )
        denied_revoke = client.delete(
            f"/v1/calendar-subscriptions/{other.json()['id']}", headers=interviewer_headers
        )
        revoked = client.delete(
            f"/v1/calendar-subscriptions/{own.json()['id']}", headers=interviewer_headers
        )

    assert own.status_code == 201
    assert own.headers["cache-control"] == "private, no-store"
    assert denied_create.status_code == 403
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    assert list(listed.json()[0]) == ["id", "created_at", "expires_at"]
    assert listed.json()[0]["id"] == own.json()["id"]
    assert listed.json()[0]["expires_at"] == own.json()["expires_at"]
    assert "feed_url" not in listed.text
    assert denied_list.status_code == 403
    assert denied_revoke.status_code == 404
    assert revoked.status_code == 204


def test_calendar_subscription_list_is_tenant_scoped_and_manage_can_list() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, _ = setup_interview_context(client)
        created = client.post("/v1/calendar-subscriptions", headers=interviewer_headers, json={})
        listed = client.get(
            "/v1/calendar-subscriptions?interviewer=interviewer-1", headers=recruiter_headers
        )
        tenant_b = client.post(
            "/v1/tenants",
            json={"name": "Other HR", "slug": "other", "admin_id": "recruiter-b"},
        ).json()
        tenant_b_headers = {"X-Tenant-Id": tenant_b["id"], "X-Actor-Id": "recruiter-b"}
        cross_tenant = client.get(
            "/v1/calendar-subscriptions?interviewer=interviewer-1", headers=tenant_b_headers
        )
        missing = client.get("/v1/calendar-subscriptions", headers=interviewer_headers)
        oversized = client.get(
            f"/v1/calendar-subscriptions?interviewer={'x' * 129}", headers=interviewer_headers
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created.json()["id"]]
    assert cross_tenant.json() == []
    assert missing.status_code == 422
    assert oversized.status_code == 422
