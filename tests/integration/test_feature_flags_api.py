import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_webhooks import Sender, create, enqueue, worker
from test_webhooks import api as api

from app.modules.feature_flags.application.flags import WEBHOOKS_DELIVERY, WEBHOOKS_OUTBOUND
from app.modules.feature_flags.infrastructure.openfeature import OpenFeatureFlags
from app.modules.webhooks.infrastructure.egress import Outcome
from app.modules.webhooks.infrastructure.management import aware
from app.modules.webhooks.infrastructure.models import Delivery, DeliveryPause, Endpoint, Event
from app.shared.models import IdempotencyRecord, Membership, User
from app.shared.settings import Settings


def set_flags(api, tmp_path, gate=True, delivery=True, tenant=None, paused_tenant=None):
    app = api[0]
    definitions = json.loads(open("tests/fixtures/flags-on.json").read())
    definitions["flags"][WEBHOOKS_OUTBOUND.key]["defaultVariant"] = "on" if gate else "off"
    definitions["flags"][WEBHOOKS_DELIVERY.key]["defaultVariant"] = "on" if delivery else "off"
    if tenant is not None:
        definitions["flags"][WEBHOOKS_OUTBOUND.key]["targeting"] = {
            "if": [{"in": [{"var": "tenant_id"}, [tenant]]}, "on", None]
        }
    if paused_tenant is not None:
        definitions["flags"][WEBHOOKS_DELIVERY.key]["targeting"] = {
            "if": [{"in": [{"var": "tenant_id"}, [paused_tenant]]}, "off", None]
        }
    path = tmp_path / "flags.json"
    path.write_text(json.dumps(definitions))
    app.state.feature_flags.close()
    app.state.feature_flags = OpenFeatureFlags(
        Settings(feature_flags_provider="file", flagd_offline_flag_source_path=str(path))
    )


def test_tenant_role_isolation_and_no_targeting_override(api, tmp_path):
    app, client, headers = api
    allowed = headers["X-Tenant-Id"]
    other = client.post(
        "/v1/tenants", json={"name": "Other", "slug": "other", "admin_id": "other"}
    ).json()["id"]
    set_flags(api, tmp_path, gate=False, tenant=allowed)
    assert create(api).status_code == 201
    other_headers = {"X-Tenant-Id": other, "X-Actor-Id": "other", "X-Feature-Tenant": allowed}
    response = client.post(
        f"/v1/webhook-endpoints?tenant_id={allowed}",
        headers=other_headers,
        json={"tenant_id": allowed},
    )
    assert response.status_code == 403 and response.json()["feature"] == "webhooks"
    assert client.get("/v1/me", headers=headers).json()["features"]["webhooks"]["enabled"]
    assert not client.get("/v1/me", headers=other_headers).json()["features"]["webhooks"]["enabled"]
    with app.state.session_factory.begin() as session:
        session.add(User(id="recruiter", email="private@example.test"))
        session.add(Membership(tenant_id=other, user_id="recruiter", role="recruiter"))
    response = client.post(
        "/v1/webhook-endpoints", headers={**other_headers, "X-Actor-Id": "recruiter"}, json={}
    )
    assert response.status_code == 403 and response.json()["type"].endswith("#forbidden")
    assert client.get("/v1/me", headers={**headers, "X-Tenant-Id": other}).status_code == 403
    assert client.post("/v1/webhook-endpoints", json={}).status_code == 401


@pytest.mark.parametrize(
    "body,allowed",
    [
        ('{"enabled":false}', True),
        ('{"enabled":0}', True),
        ('{"enabled":true,"enabled":false}', True),
        ('{"enabled":false,"description":"x"}', False),
        ('{"enabled":true}', False),
        ('{"url":"https://new.example"}', False),
    ],
)
def test_gate_uses_parsed_patch_before_conditions_and_idempotency(api, tmp_path, body, allowed):
    app, client, headers = api
    endpoint = create(api).json()
    _, ident = enqueue(api)
    set_flags(api, tmp_path, gate=False)
    response = client.patch(
        "/v1/webhook-endpoints/" + endpoint["id"],
        content=body,
        headers={
            **headers,
            "Content-Type": "application/json",
            "If-Match": '"1"',
            "Idempotency-Key": "test",
        },
    )
    assert response.status_code == (200 if allowed else 403), response.text
    with app.state.session_factory() as session:
        assert session.get(Delivery, ident).status == ("cancelled" if allowed else "pending")
        assert len(list(session.scalars(select(IdempotencyRecord)))) == (1 if allowed else 0)
    if not allowed:
        assert response.json()["title"] == "Feature Disabled"
        assert response.headers["Cache-Control"] == "private, no-store"
    assert (
        client.patch(
            "/v1/webhook-endpoints/" + endpoint["id"], json={}, headers=headers
        ).status_code
        == 422
    )


def test_disabled_route_matrix_and_gate_precedes_validation(api, tmp_path):
    app, client, headers = api
    endpoint = create(api).json()
    _, ident = enqueue(api)
    set_flags(api, tmp_path, gate=False)
    for path in (
        "/v1/webhook-event-types",
        "/v1/webhook-endpoints",
        "/v1/webhook-endpoints/" + endpoint["id"],
        f"/v1/webhook-endpoints/{endpoint['id']}/deliveries",
        f"/v1/webhook-deliveries/{ident}",
    ):
        assert client.get(path, headers=headers).status_code == 200
    assert client.post("/v1/webhook-endpoints", json={}, headers=headers).status_code == 403
    assert (
        client.post(
            "/v1/webhook-deliveries/not-a-uuid/redeliveries",
            headers={**headers, "Idempotency-Key": "retry"},
        ).status_code
        == 403
    )
    rotated = client.post(
        f"/v1/webhook-endpoints/{endpoint['id']}/secret-rotations",
        json={},
        headers={**headers, "If-Match": '"1"'},
    )
    assert rotated.status_code == 201, rotated.text
    deleted = client.delete(
        f"/v1/webhook-endpoints/{endpoint['id']}", headers={**headers, "If-Match": '"2"'}
    )
    assert deleted.status_code == 204, deleted.text
    with app.state.session_factory() as session:
        assert session.get(Delivery, ident).status == "cancelled"


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("delivery", [False, True])
@pytest.mark.parametrize("outage", [False, True])
def test_api_actor_worker_agreement_and_outage(api, tmp_path, gate, delivery, outage, caplog):
    app, client, headers = api
    create(api)
    _, ident = enqueue(api)
    set_flags(api, tmp_path, gate=gate, delivery=delivery)
    if outage:
        app.state.feature_flags.close()
        app.state.feature_flags = OpenFeatureFlags(
            Settings(
                feature_flags_provider="flagd",
                flagd_host="127.0.0.1",
                flagd_port=1,
            )
        )
    state = client.get("/v1/me", headers=headers).json()["features"]["webhooks"]
    assert state == {
        "enabled": gate and not outage,
        "delivery_paused": not (gate and delivery and not outage),
    }
    assert create(api, url="https://other.example/hook").status_code == (
        201 if state["enabled"] else 403
    )
    runner = worker(api)
    assert runner.deliver_pending() == int(not state["delivery_paused"])
    with app.state.session_factory() as session:
        row = session.get(Delivery, ident)
        assert row.attempt_count == int(not state["delivery_paused"])
        if state["delivery_paused"]:
            assert row.status == "pending" and row.leased_until is None
            assert session.get(DeliveryPause, headers["X-Tenant-Id"]).reason == (
                "flag_error" if outage else "flag_off"
            )
    assert client.get("/health/ready").status_code == 200
    if outage:
        warnings = [r for r in caplog.records if r.message == "feature_flag_evaluation_failed"]
        assert {r.flag_key for r in warnings} == {
            "release.webhooks.outbound",
            "ops.webhooks.delivery",
            "release.onboarding.saga",
        }


@pytest.mark.parametrize("account_for_pause", [True, False])
def test_pause_resume_excludes_streak_time_and_preserves_attempt_budget(
    api, tmp_path, account_for_pause
):
    app, _, headers = api
    endpoint = create(api).json()
    _, ident = enqueue(api)
    now = [datetime.now(UTC)]
    with app.state.session_factory.begin() as session:
        row = session.get(Endpoint, endpoint["id"])
        row.consecutive_failures = 19
        row.failure_streak_started_at = now[0] - timedelta(hours=70)
    set_flags(api, tmp_path, delivery=False)
    sender = Sender(Outcome(500))
    runner = worker(api, sender=sender, clock=lambda: now[0])
    with app.state.session_factory() as session:
        before = session.get(Delivery, ident)
        due = aware(before.next_attempt_at)
    assert runner.deliver_pending() == 0 and not sender.calls
    with app.state.session_factory() as session:
        row = session.get(Delivery, ident)
        assert (row.attempt_count, aware(row.next_attempt_at), row.leased_until) == (0, due, None)
        since = aware(session.get(DeliveryPause, headers["X-Tenant-Id"]).paused_since)
    now[0] += timedelta(days=3)
    if not account_for_pause:
        # Control: skipping the resume shift makes the 20th failure auto-disable.
        with app.state.session_factory.begin() as session:
            session.delete(session.get(DeliveryPause, headers["X-Tenant-Id"]))
    set_flags(api, tmp_path)
    runner.flags = app.state.feature_flags
    runner.deliver_pending()
    with app.state.session_factory() as session:
        row = session.get(Endpoint, endpoint["id"])
        assert row.status == ("enabled" if account_for_pause else "disabled")
        assert row.consecutive_failures == 20
        assert aware(row.failure_streak_started_at) == since - timedelta(hours=70) + (
            timedelta(days=3) if account_for_pause else timedelta()
        )
        shifted = aware(row.failure_streak_started_at)
        assert session.get(Delivery, ident).attempt_count == 1
        assert session.get(DeliveryPause, headers["X-Tenant-Id"]) is None
    runner.refresh_snapshot()
    with app.state.session_factory() as session:
        assert aware(session.get(Endpoint, endpoint["id"]).failure_streak_started_at) == shifted


def test_stale_pause_cleanup_and_snapshot_refresh(api, tmp_path):
    app, _, headers = api
    create(api)
    _, ident = enqueue(api)
    now = [datetime.now(UTC)]
    set_flags(api, tmp_path, delivery=False)
    runner = worker(api, clock=lambda: now[0])
    assert runner.claim() is None
    with app.state.session_factory.begin() as session:
        session.get(Delivery, ident).status = "cancelled"
    now[0] += timedelta(seconds=6)
    assert runner.claim() is None
    with app.state.session_factory() as session:
        assert session.get(DeliveryPause, headers["X-Tenant-Id"]) is None
        assert session.scalar(select(Event)) is not None


def test_per_tenant_kill_switch_keeps_other_tenant_delivering_and_redelivery_pending(api, tmp_path):
    app, client, headers = api
    create(api)
    _, first = enqueue(api)
    tenant = client.post(
        "/v1/tenants", json={"name": "Other", "slug": "other", "admin_id": "other"}
    ).json()["id"]
    other = app, client, {"X-Tenant-Id": tenant, "X-Actor-Id": "other"}
    create(other)
    _, second = enqueue(other)
    set_flags(api, tmp_path, paused_tenant=headers["X-Tenant-Id"])
    runner = worker(api)
    assert runner.deliver_pending() == 1
    with app.state.session_factory() as session:
        assert session.get(Delivery, first).attempt_count == 0
        assert session.get(Delivery, second).status == "succeeded"
    set_flags(api, tmp_path, delivery=False)
    response = client.post(f"/v1/webhook-deliveries/{second}/redeliveries", headers=other[2])
    assert response.status_code == 202, response.text
    runner.flags = app.state.feature_flags
    runner.snapshot_at = None
    assert runner.deliver_pending() == 0
    with app.state.session_factory() as session:
        redelivery = session.get(Delivery, response.json()["id"])
        assert redelivery.status == "pending" and redelivery.attempt_count == 0
