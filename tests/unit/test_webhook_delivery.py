import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

import app.shared.models  # noqa: F401
from app.modules.webhooks.application.signing import aad
from app.modules.webhooks.infrastructure.cipher import build_cipher
from app.modules.webhooks.infrastructure.consumer import (
    WebhookConsumer,
    decode_event,
)
from app.modules.webhooks.infrastructure.egress import EgressGuard, Outcome, PinnedSender
from app.modules.webhooks.infrastructure.models import (
    Delivery,
    Endpoint,
    Event,
    Secret,
    Subscription,
)
from app.modules.webhooks.infrastructure.worker import WebhookWorker, retry_seconds
from app.shared.database import Base, build_session_factory
from app.shared.settings import Settings


@pytest.fixture
def storage():
    sessions = build_session_factory("sqlite://")
    Base.metadata.create_all(sessions.kw["bind"])
    now = datetime.now(UTC)
    tenant, endpoint, event_id, delivery_id, secret_id = [str(uuid4()) for _ in range(5)]
    cipher = build_cipher(Settings())
    with sessions.begin() as session:
        session.add(
            Endpoint(
                id=endpoint,
                tenant_id=tenant,
                url="https://receiver.example",
                status="enabled",
                created_by="admin",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Event(
                tenant_id=tenant,
                event_id=event_id,
                event_type="offer.created.v1",
                body={},
                occurred_at=now,
                received_at=now,
            )
        )
        session.flush()
        session.add(
            Subscription(
                tenant_id=tenant,
                endpoint_id=endpoint,
                event_type="offer.created.v1",
                created_at=now,
            )
        )
        session.add(
            Delivery(
                id=delivery_id,
                tenant_id=tenant,
                endpoint_id=endpoint,
                event_id=event_id,
                event_type="offer.created.v1",
                kind="fanout",
                status="pending",
                created_at=now,
                next_attempt_at=now,
            )
        )
        session.add(
            Secret(
                id=secret_id,
                tenant_id=tenant,
                endpoint_id=endpoint,
                status="current",
                ciphertext=cipher.encrypt(b"x" * 32, aad(tenant, endpoint, secret_id)),
                key_id=cipher.active,
                created_at=now,
            )
        )
    yield sessions, (tenant, endpoint, event_id, delivery_id)
    sessions.kw["bind"].dispose()


class Broker:
    def __init__(self, body, headers=None):
        self.message = (
            SimpleNamespace(delivery_tag=1),
            SimpleNamespace(headers=headers, delivery_mode=2),
            body,
        )
        self.published = []
        self.acked = []
        self.requeued = []

    def get(self):
        if self.message:
            message = self.message
            self.message = None
            return message
        return None, None, None

    def publish(self, *args):
        self.published.append(args)

    def ack(self, tag):
        self.acked.append(tag)

    def requeue(self, tag):
        self.requeued.append(tag)

    def depths(self):
        return {"webhooks.events": 0}


def event(tenant):
    ident = str(uuid4())
    return {
        "specversion": "1.0",
        "id": ident,
        "tenantid": tenant,
        "subject": str(uuid4()),
        "source": "urn:talentflow:offers",
        "type": "offer.created.v1",
        "time": datetime.now(UTC).isoformat(),
        "datacontenttype": "application/json",
        "correlationid": "req",
        "causationid": "req",
        "data": {"offer_id": str(uuid4())},
    }


def test_consumer_ack_after_commit_dedup_and_tenant_fanout(storage):
    sessions, (tenant, endpoint, _, _) = storage
    body = json.dumps(event(tenant)).encode()
    broker = Broker(body)
    consumer = WebhookConsumer(sessions, broker)
    consumer.drain()
    assert broker.acked == [1] and not broker.published
    decoded = decode_event(body)
    assert not consumer.apply(decoded)
    consumer.apply(event(str(uuid4())))
    with sessions() as session:
        assert (
            len(list(session.scalars(select(Delivery).where(Delivery.endpoint_id == endpoint))))
            == 2
        )


@pytest.mark.parametrize(
    "body", [b"{}", b"not-json", b"[]", b"null", b'"text"', b"x" * (256 * 1024 + 1)]
)
def test_poison_never_retries(storage, body):
    sessions, _ = storage
    broker = Broker(body)
    WebhookConsumer(sessions, broker).drain()
    assert broker.acked == [1]
    exchange, key, _, properties = broker.published[0]
    assert (exchange, key) == ("talentflow.dead-letter", "webhooks")
    assert properties.headers["x-tf-failure"] == "poison"


@pytest.mark.parametrize(
    "attempt,outcome",
    [
        (0, "retry"),
        (1, "retry"),
        (2, "retry"),
        (3, "exhausted"),
        (-1, "poison"),
        (True, "poison"),
        ("bad", "poison"),
    ],
)
def test_consumer_failure_routing(storage, attempt, outcome):
    sessions, _ = storage
    broker = Broker(b"{}", {"x-tf-attempt": attempt})
    consumer = WebhookConsumer(sessions, broker)
    consumer.failed(b"{}", broker.message[1], RuntimeError("must not echo this"))
    exchange, key, _, properties = broker.published[0]
    if outcome == "retry":
        assert exchange == "talentflow.retry" and key == f"webhooks.retry.{attempt + 1}"
    else:
        assert (
            exchange == "talentflow.dead-letter" and properties.headers["x-tf-failure"] == outcome
        )
    assert "must not echo" not in repr(properties.headers)


def test_republish_failure_requeues_without_ack(storage, monkeypatch):
    sessions, _ = storage
    broker = Broker(b"{}")

    def failed(*args):
        raise OSError("down")

    monkeypatch.setattr(broker, "publish", failed)
    with pytest.raises(RuntimeError, match="republish_failed"):
        WebhookConsumer(sessions, broker).drain()
    assert broker.requeued == [1] and not broker.acked


def test_consumer_database_error_rolls_back_inbox_before_retry(storage, monkeypatch):
    sessions, (tenant, _, _, _) = storage
    good = event(tenant)
    broker = Broker(json.dumps(good).encode())
    consumer = WebhookConsumer(sessions, broker)
    original = consumer.apply

    def failing(value):
        raise OSError("transient")

    monkeypatch.setattr(consumer, "apply", failing)
    consumer.drain()
    assert broker.published[0][0] == "talentflow.retry" and broker.acked == [1]
    assert original(good)


def test_expired_lease_is_reclaimed_and_stale_result_is_fenced(storage):
    sessions, (tenant, endpoint, _, delivery) = storage
    now = [datetime.now(UTC)]

    class Sender:
        async def send(self, *args):
            return Outcome(204)

    worker = WebhookWorker(sessions, Sender(), build_cipher(Settings()), clock=lambda: now[0])
    first = worker.claim()
    assert first[0] == delivery and worker.claim() is None
    now[0] += timedelta(seconds=61)
    next_worker = WebhookWorker(sessions, Sender(), build_cipher(Settings()), clock=lambda: now[0])
    second = next_worker.claim()
    assert second[0] == first[0] and second[3] > first[3]
    assert not asyncio.run(worker.attempt(first))
    assert asyncio.run(next_worker.attempt(second))
    assert next_worker.pending_count() == 0
    worker.release_leases()


def test_url_is_read_per_attempt_and_cancelled_lease_never_sends(storage):
    sessions, (tenant, endpoint, _, delivery) = storage
    calls = []

    class Sender:
        async def send(self, *args):
            calls.append(args)
            return Outcome(204)

    worker = WebhookWorker(sessions, Sender(), build_cipher(Settings()))
    claim = worker.claim()
    with sessions.begin() as session:
        row = session.get(Endpoint, endpoint)
        row.url = "https://new.example/path"
    assert asyncio.run(worker.attempt(claim))
    assert calls[0][0] == "https://new.example/path"
    with sessions.begin() as session:
        row = session.get(Delivery, delivery)
        row.status = "cancelled"
        row.leased_until = None
    assert not asyncio.run(worker.attempt(claim))
    assert len(calls) == 1


def test_cancellation_during_send_cannot_be_overwritten(storage):
    sessions, (_, _, _, delivery) = storage

    class Sender:
        async def send(self, *args):
            with sessions.begin() as session:
                row = session.get(Delivery, delivery)
                row.status = "cancelled"
                row.leased_until = None
            return Outcome(204)

    worker = WebhookWorker(sessions, Sender(), build_cipher(Settings()))
    assert not asyncio.run(worker.attempt(worker.claim()))
    with sessions() as session:
        assert session.get(Delivery, delivery).status == "cancelled"


def test_retry_after_is_bounded_and_ignores_malformed_values():
    now = datetime(2026, 11, 27, tzinfo=UTC)
    assert retry_seconds("999999", now) == 3600
    assert retry_seconds("Fri, 27 Nov 2026 00:05:00 GMT", now) == 300
    assert retry_seconds("Fri, 27 Nov 2026 00:00:00", now) == 0
    for value in ("bad", "²", "", None):
        assert retry_seconds(value, now) == 0


def test_sender_error_codes_and_wall_clock_deadline(monkeypatch):
    from app.modules.webhooks.infrastructure import egress

    async def rejected(host, port):
        raise OSError("DNS down")

    result = asyncio.run(
        PinnedSender(EgressGuard(resolver=rejected)).send("https://receiver.example", {}, b"{}")
    )
    assert result.error_code == "dns_error"
    result = asyncio.run(PinnedSender(EgressGuard()).send("https://127.0.0.1", {}, b"{}"))
    assert result.error_code == "blocked_address"

    class SlowGuard:
        async def check(self, url):
            await asyncio.sleep(1)

    real_timeout = asyncio.timeout
    monkeypatch.setattr(egress.asyncio, "timeout", lambda _: real_timeout(0.02))
    result = asyncio.run(PinnedSender(SlowGuard()).send("https://receiver.example", {}, b"{}"))
    assert result.error_code == "timeout"
