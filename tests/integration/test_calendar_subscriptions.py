from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.shared.models import AuditEvent, CalendarSubscription, Membership, User
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
        revoked_feed = client.get(own.json()["feed_url"])
        with client.app.state.session_factory() as session:
            revoke_audit = session.scalar(
                select(AuditEvent).where(AuditEvent.action == "calendar_subscription.revoked")
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
    assert revoked_feed.status_code == 404
    assert revoke_audit is not None
    assert revoke_audit.actor_id == "interviewer-1"
    assert revoke_audit.metadata_json["scope"] == "self"


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
    assert list(listed.json()[0]) == ["id", "created_at", "expires_at"]
    assert cross_tenant.json() == []
    assert missing.status_code == 422
    assert oversized.status_code == 422


def test_self_create_variants_do_not_write_and_explicit_self_link_works() -> None:
    with TestClient(create_app("sqlite://")) as client:
        _, interviewer_headers, _ = setup_interview_context(client)
        own = client.post(
            "/v1/calendar-subscriptions",
            headers=interviewer_headers,
            json={"interviewer_id": "interviewer-1"},
        )
        feed = client.get(own.json()["feed_url"])
        current_actor = client.get("/v1/me", headers=interviewer_headers)
        with client.app.state.session_factory() as session:
            before = len(session.scalars(select(CalendarSubscription)).all())
            audits_before = len(session.scalars(select(AuditEvent)).all())
        denied = [
            client.post(
                "/v1/calendar-subscriptions",
                headers=interviewer_headers,
                json={"interviewer_id": value},
            )
            for value in ("INTERVIEWER-1", " interviewer-1 ", "me")
        ]
        with client.app.state.session_factory() as session:
            after = len(session.scalars(select(CalendarSubscription)).all())
            audits_after = len(session.scalars(select(AuditEvent)).all())

    assert own.status_code == 201
    assert feed.status_code == 200
    assert "calendar:self" in current_actor.json()["permissions"]
    assert all(response.status_code == 403 for response in denied)
    assert (after, audits_after) == (before, audits_before)


def test_revoke_hides_foreign_missing_revoked_and_cross_tenant_links() -> None:
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
        other = client.post(
            "/v1/calendar-subscriptions",
            headers=recruiter_headers,
            json={"interviewer_id": "interviewer-2"},
        )
        revoked = client.post("/v1/calendar-subscriptions", headers=interviewer_headers, json={})
        assert (
            client.delete(
                f"/v1/calendar-subscriptions/{revoked.json()['id']}", headers=interviewer_headers
            ).status_code
            == 204
        )
        tenant_b = client.post(
            "/v1/tenants",
            json={"name": "Other HR", "slug": "other-revoke", "admin_id": "recruiter-b"},
        ).json()
        tenant_b_headers = {"X-Tenant-Id": tenant_b["id"], "X-Actor-Id": "recruiter-b"}
        with client.app.state.session_factory() as session:
            session.add(User(id="interviewer-b"))
            session.add(
                Membership(tenant_id=tenant_b["id"], user_id="interviewer-b", role="interviewer")
            )
            session.commit()
        foreign_tenant = client.post(
            "/v1/calendar-subscriptions",
            headers=tenant_b_headers,
            json={"interviewer_id": "interviewer-b"},
        )
        audit_count = _calendar_audit_count(client)
        responses = [
            client.delete(
                f"/v1/calendar-subscriptions/{other.json()['id']}", headers=interviewer_headers
            ),
            client.delete("/v1/calendar-subscriptions/missing", headers=interviewer_headers),
            client.delete(
                f"/v1/calendar-subscriptions/{revoked.json()['id']}", headers=interviewer_headers
            ),
            client.delete(
                f"/v1/calendar-subscriptions/{foreign_tenant.json()['id']}",
                headers=interviewer_headers,
            ),
        ]
        other_feed = client.get(other.json()["feed_url"])
        audits_after = _calendar_audit_count(client)

    assert all(response.status_code == 404 for response in responses)
    assert len({_problem_body(response) for response in responses}) == 1
    assert other_feed.status_code == 200
    assert audits_after == audit_count


def test_list_excludes_revoked_expired_and_never_exposes_token_or_audit_secret() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, _ = setup_interview_context(client)
        first = client.post("/v1/calendar-subscriptions", headers=interviewer_headers, json={})
        second = client.post("/v1/calendar-subscriptions", headers=interviewer_headers, json={})
        assert (
            client.delete(
                f"/v1/calendar-subscriptions/{first.json()['id']}", headers=interviewer_headers
            ).status_code
            == 204
        )
        with client.app.state.session_factory() as session:
            subscription = session.get(CalendarSubscription, second.json()["id"])
            assert subscription is not None
            subscription.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        listed = client.get(
            "/v1/calendar-subscriptions?interviewer=me", headers=interviewer_headers
        )
        audits = client.get("/v1/audit-events", headers=recruiter_headers)
        with client.app.state.session_factory() as session:
            metadata = [
                (event.action, event.metadata_json)
                for event in session.scalars(
                    select(AuditEvent).where(AuditEvent.aggregate_type == "calendar_subscription")
                )
            ]

    token = second.json()["feed_url"].split("/")[-1].removesuffix(".ics")
    assert listed.json() == []
    assert token not in listed.text
    assert token not in audits.text
    assert "token_hash" not in audits.text
    assert all(token not in str(value) and "token_hash" not in str(value) for _, value in metadata)
    assert all(
        set(value)
        == (
            {"interviewer_id", "expires_at", "scope"}
            if action.endswith("created")
            else {"interviewer_id", "scope"}
        )
        for action, value in metadata
    )


def test_list_returns_active_subscriptions_newest_first() -> None:
    with TestClient(create_app("sqlite://")) as client:
        _, interviewer_headers, _ = setup_interview_context(client)
        first = client.post("/v1/calendar-subscriptions", headers=interviewer_headers, json={})
        second = client.post("/v1/calendar-subscriptions", headers=interviewer_headers, json={})
        with client.app.state.session_factory() as session:
            first_row = session.get(CalendarSubscription, first.json()["id"])
            second_row = session.get(CalendarSubscription, second.json()["id"])
            assert first_row is not None and second_row is not None
            first_row.created_at = datetime.now(UTC) - timedelta(days=2)
            second_row.created_at = datetime.now(UTC) - timedelta(days=1)
            session.commit()
        listed = client.get(
            "/v1/calendar-subscriptions?interviewer=me", headers=interviewer_headers
        )

    assert [item["id"] for item in listed.json()] == [second.json()["id"], first.json()["id"]]


@pytest.mark.parametrize("role", ["hiring_manager", "auditor"])
def test_roles_without_calendar_permissions_are_denied_before_query_validation(role: str) -> None:
    with TestClient(create_app("sqlite://")) as client:
        _, interviewer_headers, _ = setup_interview_context(client)
        with client.app.state.session_factory() as session:
            user_id = f"{role}-1"
            session.add(User(id=user_id))
            session.add(
                Membership(tenant_id=interviewer_headers["X-Tenant-Id"], user_id=user_id, role=role)
            )
            session.commit()
        headers = {**interviewer_headers, "X-Actor-Id": user_id}
        responses = (
            client.post("/v1/calendar-subscriptions", headers=headers, json={}),
            client.get("/v1/calendar-subscriptions", headers=headers),
            client.delete("/v1/calendar-subscriptions/missing", headers=headers),
            client.get(f"/v1/calendar-subscriptions?interviewer={'x' * 129}", headers=headers),
        )

    assert all(response.status_code == 403 for response in responses)


def test_same_user_memberships_are_scoped_to_actor_tenant() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_a, interviewer_a, _ = setup_interview_context(client)
        created_a = client.post("/v1/calendar-subscriptions", headers=interviewer_a, json={})
        tenant_b = client.post(
            "/v1/tenants", json={"name": "Tenant B", "slug": "tenant-b", "admin_id": "recruiter-b"}
        ).json()
        recruiter_b = {"X-Tenant-Id": tenant_b["id"], "X-Actor-Id": "recruiter-b"}
        with client.app.state.session_factory() as session:
            session.add(
                Membership(tenant_id=tenant_b["id"], user_id="interviewer-1", role="interviewer")
            )
            session.commit()
        interviewer_b = {"X-Tenant-Id": tenant_b["id"], "X-Actor-Id": "interviewer-1"}
        created_b = client.post("/v1/calendar-subscriptions", headers=interviewer_b, json={})
        assert (
            client.delete(
                f"/v1/calendar-subscriptions/{created_a.json()['id']}", headers=recruiter_b
            ).status_code
            == 404
        )
        assert client.get(created_a.json()["feed_url"]).status_code == 200
        listed_b = client.get("/v1/calendar-subscriptions?interviewer=me", headers=interviewer_b)
        listed_a = client.get("/v1/calendar-subscriptions?interviewer=me", headers=interviewer_a)

    assert [item["id"] for item in listed_a.json()] == [created_a.json()["id"]]
    assert [item["id"] for item in listed_b.json()] == [created_b.json()["id"]]


def test_interviewer_cannot_schedule_interviews() -> None:
    with TestClient(create_app("sqlite://")) as client:
        recruiter_headers, interviewer_headers, candidate_id = setup_interview_context(client)
        response = client.post(
            f"/v1/candidate-cases/{candidate_id}/interviews",
            headers=interviewer_headers,
            json={"interviewer_id": "interviewer-1", "scheduled_at": "2026-10-01T09:00:00Z"},
        )

    assert recruiter_headers
    assert response.status_code == 403


def _calendar_audit_count(client: TestClient) -> int:
    with client.app.state.session_factory() as session:
        return len(
            session.scalars(
                select(AuditEvent).where(AuditEvent.aggregate_type == "calendar_subscription")
            ).all()
        )


def _problem_body(response) -> str:
    body = response.json()
    body.pop("instance")
    body.pop("correlation_id")
    return str(sorted(body.items()))
