import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import select

from app.main import create_app
from app.modules.webhooks.application.signing import verify
from app.modules.webhooks.infrastructure.cipher import build_cipher
from app.modules.webhooks.infrastructure.consumer import WebhookConsumer
from app.modules.webhooks.infrastructure.egress import EgressGuard, Outcome
from app.modules.webhooks.infrastructure.maintenance import (
    expire_secrets,
    purge_webhooks,
    rewrap_batch,
)
from app.modules.webhooks.infrastructure.management import aware
from app.modules.webhooks.infrastructure.models import Delivery, Endpoint, Event, Secret
from app.modules.webhooks.infrastructure.worker import WebhookWorker
from app.shared.models import AuditEvent, IdempotencyRecord, Membership, User
from app.shared.settings import Settings


@pytest.fixture
def api():
    key = base64.b64encode(b"x" * 32).decode()
    settings = Settings(
        app_env="test",
        rate_limit_enabled=False,
        webhook_secret_keys="test:" + key,
        webhook_secret_active_key_id="test",
    )
    app = create_app("sqlite://", settings)

    async def resolver(host, port):
        return ["93.184.216.34"]

    app.state.webhook_egress_guard = EgressGuard(resolver=resolver)
    with TestClient(app) as client:
        tenant = client.post(
            "/v1/tenants", json={"name": "Hooks", "slug": "hooks", "admin_id": "admin"}
        ).json()
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "admin"}
        yield app, client, headers


def create(api, **changes):
    _, client, headers = api
    return client.post(
        "/v1/webhook-endpoints",
        headers=headers,
        json={
            "url": "https://receiver.example/hook?token=hidden",
            "event_types": ["candidate_case.created.v1"],
            **changes,
        },
    )


def event_for(api):
    return {
        "specversion": "1.0",
        "id": str(uuid4()),
        "tenantid": api[2]["X-Tenant-Id"],
        "subject": str(uuid4()),
        "type": "candidate_case.created.v1",
        "source": "urn:talentflow:candidates",
        "time": datetime.now(UTC).isoformat(),
        "datacontenttype": "application/json",
        "correlationid": "req-1",
        "causationid": "req-1",
        "data": {
            "candidate_case_id": str(uuid4()),
            "requisition_id": str(uuid4()),
            "stage": "applied",
            "channel": "recruiter",
            "version": 1,
        },
    }


def enqueue(api):
    event = event_for(api)
    consumer = WebhookConsumer(api[0].state.session_factory, None)
    assert consumer.apply(event)
    assert not consumer.apply(event)
    with api[0].state.session_factory() as session:
        ident = session.scalar(select(Delivery.id).where(Delivery.event_id == event["id"]))
    return event, ident


class Sender:
    def __init__(self, result=Outcome(204)):
        self.calls = []
        self.result = result

    async def send(self, url, headers, body):
        self.calls.append((url, headers, body))
        return self.result


def worker(api, sender=None, **options):
    app, _, _ = api
    return WebhookWorker(
        app.state.session_factory,
        sender or Sender(),
        build_cipher(app.state.runtime_settings),
        **options,
    )


def test_create_get_contract_and_no_secret_replay(api):
    app, client, headers = api
    response = create(api)
    assert response.status_code == 201, response.text
    body = response.json()
    assert response.headers["etag"] == '"1"'
    assert response.headers["cache-control"] == "private, no-store"
    schema = app.openapi()["components"]["schemas"]
    Draft202012Validator(
        {
            "$ref": "#/components/schemas/WebhookEndpointWithSecret",
            "components": {"schemas": schema},
        }
    ).validate(body)
    path = "/v1/webhook-endpoints/" + body["id"]
    read = client.get(path, headers=headers)
    assert read.status_code == 200
    assert "value" not in read.text and body["secret"]["value"] not in read.text
    listed = client.get("/v1/webhook-endpoints", headers=headers).json()
    assert listed["items"][0] == read.json()
    with app.state.session_factory() as session:
        stored = session.get(Secret, body["secret"]["id"])
        assert body["secret"]["value"] not in stored.ciphertext
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "webhook.created"))
        assert audit.metadata_json["host"] == "receiver.example"
        assert "hidden" not in json.dumps(audit.metadata_json)
        assert not list(session.scalars(select(IdempotencyRecord)))
    # Secret-bearing endpoints ignore even a malformed key and never replay a secret.
    second = client.post(
        "/v1/webhook-endpoints",
        headers={**headers, "Idempotency-Key": " "},
        json={"url": "https://receiver.example/second", "event_types": ["offer.created.v1"]},
    )
    assert second.status_code == 201


@pytest.mark.parametrize("role", ["recruiter", "auditor", "hiring_manager", "interviewer"])
def test_admin_only_every_operation(api, role):
    app, client, headers = api
    with app.state.session_factory() as session:
        session.add(User(id=role))
        session.add(Membership(tenant_id=headers["X-Tenant-Id"], user_id=role, role=role))
        session.commit()
    headers = {**headers, "X-Actor-Id": role}
    ident = str(uuid4())
    for method, path in [
        ("GET", "/v1/webhook-event-types"),
        ("POST", "/v1/webhook-endpoints"),
        ("GET", "/v1/webhook-endpoints"),
        ("GET", f"/v1/webhook-endpoints/{ident}"),
        ("PATCH", f"/v1/webhook-endpoints/{ident}"),
        ("DELETE", f"/v1/webhook-endpoints/{ident}"),
        ("POST", f"/v1/webhook-endpoints/{ident}/secret-rotations"),
        ("GET", f"/v1/webhook-endpoints/{ident}/deliveries"),
        ("GET", f"/v1/webhook-deliveries/{ident}"),
        ("POST", f"/v1/webhook-deliveries/{ident}/redeliveries"),
    ]:
        assert client.request(method, path, headers=headers).status_code == 403


def test_cross_tenant_and_unknown_ids_are_hidden(api):
    _, client, headers = api
    endpoint = create(api).json()
    other = client.post(
        "/v1/tenants", json={"name": "Other", "slug": "other", "admin_id": "other"}
    ).json()
    other_headers = {"X-Tenant-Id": other["id"], "X-Actor-Id": "other"}
    _, ident = enqueue(api)
    for method, path in [
        ("GET", "/v1/webhook-endpoints/" + endpoint["id"]),
        ("PATCH", "/v1/webhook-endpoints/" + endpoint["id"]),
        ("DELETE", "/v1/webhook-endpoints/" + endpoint["id"]),
        ("POST", "/v1/webhook-endpoints/" + endpoint["id"] + "/secret-rotations"),
        ("GET", "/v1/webhook-endpoints/" + endpoint["id"] + "/deliveries"),
        ("GET", "/v1/webhook-deliveries/" + ident),
        ("POST", "/v1/webhook-deliveries/" + ident + "/redeliveries"),
    ]:
        kwargs = {"json": {"enabled": False}} if method == "PATCH" else {}
        assert (
            client.request(
                method, path, headers={**other_headers, "If-Match": '"1"'}, **kwargs
            ).status_code
            == 404
        )


@pytest.mark.parametrize(
    "payload,pointer",
    [
        ({"event_types": ["offer.approval_recorded.v1"]}, "/event_types/0"),
        ({"event_types": ["offer.created.v1", "offer.created.v1"]}, "/event_types"),
        ({"event_types": []}, "/event_types"),
        ({"description": "bad\ntext"}, "/description"),
        ({"unknown": True}, "/unknown"),
    ],
)
def test_input_validation(api, payload, pointer):
    response = create(api, **payload)
    assert response.status_code == 422, response.text
    assert response.json()["errors"][0]["pointer"] == pointer


@pytest.mark.parametrize(
    "url",
    [
        "http://receiver.example",
        "https://127.0.0.1",
        "https://[::1]",
        "https://localhost",
        "https://user:pass@receiver.example",
        "https://receiver.example/#fragment",
        "https://receiver.example:8000",
    ],
)
def test_registration_rejects_unsafe_urls(api, url):
    response = create(api, url=url)
    assert response.status_code == 422
    assert response.json()["type"].endswith("#webhook-url-not-allowed")
    assert response.json()["errors"][0]["pointer"] == "/url"


def test_preconditions_patch_idempotency_disable_delete(api):
    app, client, headers = api
    endpoint = create(api).json()
    path = "/v1/webhook-endpoints/" + endpoint["id"]
    for tag, expected in [(None, 428), ("bad", 400), ('W/"1"', 400), ('"0"', 412)]:
        h = headers if tag is None else {**headers, "If-Match": tag}
        result = client.patch(path, headers=h, json={"description": "hello"})
        assert result.status_code == expected, result.text
    _, ident = enqueue(api)
    h = {**headers, "If-Match": '"1"', "Idempotency-Key": "disable"}
    first = client.patch(path, headers=h, json={"enabled": False})
    assert first.status_code == 200, first.text
    replay = client.patch(path, headers=h, json={"enabled": False})
    assert replay.status_code == 200 and replay.headers["idempotent-replayed"] == "true"
    assert replay.json() == first.json()
    assert (
        client.patch(path, headers={**h, "If-Match": '"2"'}, json={"enabled": False}).status_code
        == 422
    )
    assert (
        client.get("/v1/webhook-deliveries/" + ident, headers=headers).json()["status"]
        == "cancelled"
    )
    assert (
        client.patch(path, headers={**headers, "If-Match": "*"}, json={"enabled": True}).status_code
        == 200
    )
    assert client.delete(path, headers={**headers, "If-Match": "*"}).status_code == 204
    assert client.get(path, headers=headers).status_code == 404
    assert client.get("/v1/webhook-deliveries/" + ident, headers=headers).status_code == 200
    with app.state.session_factory() as session:
        assert all(s.ciphertext is None for s in session.scalars(select(Secret)))


def test_rotation_overlap_fresh_signing_and_grace_zero(api):
    app, client, headers = api
    created = create(api).json()
    path = "/v1/webhook-endpoints/" + created["id"] + "/secret-rotations"
    assert client.post(path, headers={**headers, "If-Match": "*"}).status_code == 400
    rotated = client.post(
        path, headers={**headers, "If-Match": '"1"', "Idempotency-Key": "rotate"}, json={}
    ).json()
    assert client.post(path, headers={**headers, "If-Match": '"1"'}).status_code == 412
    event, ident = enqueue(api)
    sender = Sender()
    runner = worker(api, sender)
    assert runner.deliver_pending() == 1
    _, wire, body = sender.calls[0]
    assert len(wire["webhook-signature"].split()) == 2
    for secret in (created["secret"], rotated["secret"]):
        verify(secret["value"], wire, body)
    assert wire["webhook-id"] == event["id"]
    assert json.loads(body) == event
    rotated_again = client.post(
        path, headers={**headers, "If-Match": '"2"'}, json={"grace_period_seconds": 0}
    )
    assert rotated_again.status_code == 201
    with app.state.session_factory() as session:
        active = list(session.scalars(select(Secret).where(Secret.status != "expired")))
        assert len(active) == 1
    redelivery = client.post("/v1/webhook-deliveries/" + ident + "/redeliveries", headers=headers)
    assert redelivery.status_code == 202
    assert runner.deliver_pending() == 1
    assert len(sender.calls[-1][1]["webhook-signature"].split()) == 1
    verify(rotated_again.json()["secret"]["value"], sender.calls[-1][1], sender.calls[-1][2])


def test_exponential_backoff_dead_letter_redelivery_and_log_filters(api):
    app, client, headers = api
    endpoint = create(api).json()
    event, ident = enqueue(api)
    now = [datetime.now(UTC) + timedelta(seconds=1)]
    sender = Sender(Outcome(503, "http_status", "120"))
    runner = worker(api, sender, clock=lambda: now[0], jitter=lambda: 1)
    delays = [120, 120, 600, 3600, 10800, 21600, 43200]
    for number in range(1, 9):
        assert runner.deliver_pending() == 0
        with app.state.session_factory() as session:
            row = session.get(Delivery, ident)
            assert row.attempt_count == number
            if number < 8:
                assert (aware(row.next_attempt_at) - now[0]).total_seconds() == delays[number - 1]
                now[0] = aware(row.next_attempt_at)
            else:
                assert row.status == "dead_lettered" and row.next_attempt_at is None
    path = "/v1/webhook-deliveries/" + ident
    detail = client.get(path, headers=headers).json()
    assert len(detail["attempts"]) == 8
    assert all(a["status_code"] == 503 for a in detail["attempts"])
    listing = client.get(
        "/v1/webhook-endpoints/" + endpoint["id"] + "/deliveries",
        headers=headers,
        params={
            "status": ["dead_lettered", "succeeded"],
            "event_id": event["id"],
            "event_type": event["type"],
        },
    )
    assert len(listing.json()["items"]) == 1
    redelivery = client.post(
        path + "/redeliveries", headers={**headers, "Idempotency-Key": "retry"}
    )
    assert redelivery.status_code == 202
    assert (
        redelivery.json()["event_id"] == event["id"]
        and redelivery.json()["redelivery_of_id"] == ident
    )
    assert client.post(path + "/redeliveries", headers=headers).status_code == 409
    replay = client.post(path + "/redeliveries", headers={**headers, "Idempotency-Key": "retry"})
    assert replay.json()["id"] == redelivery.json()["id"]
    assert client.get(path, headers=headers).json() == detail


def test_gone_and_long_failure_streak_auto_disable(api):
    app, client, headers = api
    endpoint = create(api).json()
    _, ident = enqueue(api)
    now = datetime.now(UTC)
    with app.state.session_factory() as session:
        row = session.get(Endpoint, endpoint["id"])
        row.consecutive_failures = 19
        row.failure_streak_started_at = now - timedelta(hours=73)
        session.commit()
    worker(api, Sender(Outcome(500, "http_status"))).deliver_pending()
    detail = client.get("/v1/webhook-endpoints/" + endpoint["id"], headers=headers).json()
    assert detail["status"] == "disabled" and detail["disabled_reason"] == "failing"
    assert detail["version"] == 2
    client.patch(
        "/v1/webhook-endpoints/" + endpoint["id"],
        headers={**headers, "If-Match": '"2"'},
        json={"enabled": True},
    )
    _, ident = enqueue(api)
    worker(api, Sender(Outcome(410, "http_status"))).deliver_pending()
    with app.state.session_factory() as session:
        assert session.get(Delivery, ident).status == "dead_lettered"
        assert session.get(Endpoint, endpoint["id"]).disabled_reason == "gone"


def test_pagination_tenant_limit_and_duplicate_url(api):
    _, client, headers = api
    assert create(api).status_code == 201
    assert create(api).status_code == 409
    for index in range(9):
        assert create(api, url=f"https://receiver.example/{index}").status_code == 201
    assert (
        create(api, url="https://receiver.example/eleven")
        .json()["type"]
        .endswith("#webhook-endpoint-limit-reached")
    )
    ids = []
    cursor = None
    while True:
        result = client.get(
            "/v1/webhook-endpoints",
            headers=headers,
            params={"limit": 3, **({"cursor": cursor} if cursor else {})},
        ).json()
        ids.extend(item["id"] for item in result["items"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert len(ids) == len(set(ids)) == 10
    assert (
        client.get(
            "/v1/webhook-endpoints", headers=headers, params={"cursor": "garbage"}
        ).status_code
        == 400
    )


def test_rewrap_expire_and_purge_original_before_redeliveries(api):
    app, client, headers = api
    created = create(api).json()
    event, ident = enqueue(api)
    runner = worker(api)
    runner.deliver_pending()
    redeliveries = []
    for _ in range(2):
        response = client.post("/v1/webhook-deliveries/" + ident + "/redeliveries", headers=headers)
        assert response.status_code == 202
        redeliveries.append(response.json()["id"])
        runner.deliver_pending()
    with app.state.session_factory() as session:
        original = session.get(Delivery, ident)
        original.completed_at = datetime.now(UTC) - timedelta(days=31)
        session.commit()
        assert purge_webhooks(session, batch_size=100) == 1
        for redelivery in redeliveries:
            row = session.get(Delivery, redelivery)
            assert row.kind == "redelivery" and row.redelivery_of_id is None
        assert session.get(Event, (headers["X-Tenant-Id"], event["id"])) is not None
    rotated = client.post(
        "/v1/webhook-endpoints/" + created["id"] + "/secret-rotations",
        headers={**headers, "If-Match": "*"},
    )
    assert rotated.status_code == 400
    settings = app.state.runtime_settings
    new = Settings(
        webhook_secret_keys=settings.webhook_secret_keys.get_secret_value()
        + ",next:"
        + base64.b64encode(b"n" * 32).decode(),
        webhook_secret_active_key_id="next",
    )
    with app.state.session_factory() as session:
        assert rewrap_batch(session, build_cipher(new), 10) == 1
        record = session.get(Secret, created["secret"]["id"])
        assert record.key_id == "next"
    app.state.runtime_settings = new
    client.post(
        "/v1/webhook-endpoints/" + created["id"] + "/secret-rotations",
        headers={**headers, "If-Match": '"3"'},
        json={"grace_period_seconds": 1},
    )
    with app.state.session_factory() as session:
        previous = session.scalar(select(Secret).where(Secret.status == "previous"))
        previous.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        assert expire_secrets(session, 10) == 1
        assert session.get(Secret, previous.id).ciphertext is None


def test_missing_auth_and_malformed_queries_follow_contract(api):
    _, client, headers = api
    assert client.get("/v1/webhook-event-types").status_code == 401
    for params in ({"limit": 0}, {"limit": 101}, {"status": "deleted"}, {"cursor": "x" * 513}):
        result = client.get("/v1/webhook-endpoints", headers=headers, params=params)
        assert result.status_code == 400, result.text
