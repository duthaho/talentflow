from fastapi.testclient import TestClient

from app.main import create_app
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
