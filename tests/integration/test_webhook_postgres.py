"""Opt-in verification against an isolated, migrated PostgreSQL DB and RabbitMQ vhost."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.modules.webhooks.application.signing import verify
from app.modules.webhooks.infrastructure.cipher import build_cipher
from app.modules.webhooks.infrastructure.consumer import WebhookConsumer
from app.modules.webhooks.infrastructure.egress import EgressGuard, PinnedSender, parse_allowlist
from app.modules.webhooks.infrastructure.management import aware
from app.modules.webhooks.infrastructure.models import Delivery, Event, Subscription
from app.modules.webhooks.infrastructure.worker import WebhookWorker
from app.shared.rabbitmq import RabbitBroker
from app.shared.settings import Settings

DB_URL = os.getenv("DUTH62_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DB_URL.startswith("postgresql"), reason="requires disposable DUTH62_TEST_DATABASE_URL"
)


@pytest.fixture
def pg_api():
    app = create_app(DB_URL, Settings(app_env="test", rate_limit_enabled=False))

    async def resolver(host, port):
        return ["93.184.216.34"]

    app.state.webhook_egress_guard = EgressGuard(resolver=resolver)
    with TestClient(app) as client:
        suffix = uuid4().hex
        tenant = client.post(
            "/v1/tenants", json={"name": "Webhook PG", "slug": suffix, "admin_id": "a" + suffix}
        ).json()
        headers = {"X-Tenant-Id": tenant["id"], "X-Actor-Id": "a" + suffix}
        yield app, client, headers


def register(pg_api, url="https://receiver.example/hook"):
    _, client, headers = pg_api
    result = client.post(
        "/v1/webhook-endpoints",
        headers=headers,
        json={"url": url, "event_types": ["offer.created.v1"]},
    )
    assert result.status_code == 201, result.text
    return result.json()


def queue(pg_api, endpoint, count=1):
    now = datetime.now(UTC)
    with pg_api[0].state.session_factory.begin() as session:
        for _ in range(count):
            ident = str(uuid4())
            session.add(
                Event(
                    tenant_id=endpoint["tenant_id"]
                    if "tenant_id" in endpoint
                    else pg_api[2]["X-Tenant-Id"],
                    event_id=ident,
                    event_type="offer.created.v1",
                    body={},
                    occurred_at=now,
                    received_at=now,
                )
            )
            session.flush()
            session.add(
                Delivery(
                    id=str(uuid4()),
                    tenant_id=pg_api[2]["X-Tenant-Id"],
                    endpoint_id=endpoint["id"],
                    event_id=ident,
                    event_type="offer.created.v1",
                    kind="fanout",
                    status="pending",
                    created_at=now,
                    next_attempt_at=now,
                )
            )


def test_same_version_writes_serialize_and_quota_survives_concurrent_creates(pg_api):
    app, client, headers = pg_api
    endpoint = register(pg_api)
    path = "/v1/webhook-endpoints/" + endpoint["id"]
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda value: client.patch(
                    path, headers={**headers, "If-Match": '"1"'}, json={"description": value}
                ),
                ["one", "two"],
            )
        )
    assert sorted(r.status_code for r in results) == [200, 412]
    for i in range(8):
        register(pg_api, url=f"https://receiver.example/{i}")
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda i: client.post(
                    "/v1/webhook-endpoints",
                    headers=headers,
                    json={
                        "url": f"https://receiver.example/last{i}",
                        "event_types": ["offer.created.v1"],
                    },
                ),
                range(2),
            )
        )
    assert sorted(r.status_code for r in results) == [201, 409]
    assert len(client.get("/v1/webhook-endpoints", headers=headers).json()["items"]) == 10


def test_redelivery_pending_uniqueness_and_four_inflight_leases(pg_api):
    app, client, headers = pg_api
    endpoint = register(pg_api)
    queue(pg_api, endpoint, 5)
    runners = [
        WebhookWorker(
            app.state.session_factory,
            None,
            build_cipher(app.state.runtime_settings),
            flags=app.state.feature_flags,
        )
        for _ in range(5)
    ]
    # The query is global, so isolate every other tenant's pending fixtures first.
    with app.state.session_factory.begin() as session:
        for row in session.scalars(
            select(Delivery).where(
                Delivery.tenant_id != headers["X-Tenant-Id"], Delivery.status == "pending"
            )
        ):
            row.status = "cancelled"
            row.next_attempt_at = None
            row.completed_at = datetime.now(UTC)
    claims = [runner.claim() for runner in runners]
    assert sum(c is not None for c in claims) == 4
    assert len({c[0] for c in claims if c}) == 4
    for runner in runners:
        runner.release_leases()
    with app.state.session_factory.begin() as session:
        rows = list(
            session.scalars(select(Delivery).where(Delivery.tenant_id == headers["X-Tenant-Id"]))
        )
        ident = rows[0].id
        rows[0].status = "succeeded"
        rows[0].next_attempt_at = None
        rows[0].completed_at = datetime.now(UTC)
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda _: client.post(
                    "/v1/webhook-deliveries/" + ident + "/redeliveries", headers=headers
                ),
                range(2),
            )
        )
    assert sorted(r.status_code for r in results) == [202, 409]
    with app.state.session_factory.begin() as session:
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(
                Subscription(
                    tenant_id=str(uuid4()),
                    endpoint_id=endpoint["id"],
                    event_type="offer.created.v1",
                    created_at=datetime.now(UTC),
                )
            )
            session.flush()


@pytest.mark.skipif(
    not os.getenv("DUTH62_TEST_RABBITMQ_URL") or not os.getenv("DUTH62_TEST_RECEIVER_IP"),
    reason="requires disposable RabbitMQ and private receiver interface",
)
def test_real_rabbit_fanout_and_pinned_signed_http(pg_api):
    app, client, headers = pg_api
    host = os.environ["DUTH62_TEST_RECEIVER_IP"]
    seen = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(
                (
                    dict((k.lower(), v) for k, v in self.headers.items()),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, 0), Receiver)
    thread = Thread(target=server.serve_forever)
    thread.start()
    broker = RabbitBroker(
        os.environ["DUTH62_TEST_RABBITMQ_URL"], consumer="webhooks", bindings=("offer.created.v1",)
    )
    try:

        async def resolver(name, port):
            return [host]

        guard = EgressGuard(
            allow_http=True, allowlist=parse_allowlist(host + "/32"), resolver=resolver
        )
        app.state.webhook_egress_guard = guard
        endpoint = register(pg_api, url=f"http://receiver.example:{server.server_port}/hook")
        event = {
            "specversion": "1.0",
            "id": str(uuid4()),
            "tenantid": headers["X-Tenant-Id"],
            "subject": str(uuid4()),
            "source": "urn:talentflow:offers",
            "type": "offer.created.v1",
            "time": datetime.now(UTC).isoformat(),
            "datacontenttype": "application/json",
            "correlationid": "req-1",
            "causationid": "req-1",
            "data": {
                "offer_id": str(uuid4()),
                "candidate_case_id": str(uuid4()),
                "offer_status": "pending_approval",
                "approval_step": 1,
                "version": 1,
            },
        }
        broker.connect()
        broker.publish_event(event)
        broker.publish_event(event)
        consumer = WebhookConsumer(app.state.session_factory, broker)
        # Publisher confirms and queue ordering make both messages available without polling.
        consumer.drain()
        with app.state.session_factory() as session:
            rows = list(
                session.scalars(
                    select(Delivery).where(
                        Delivery.tenant_id == headers["X-Tenant-Id"],
                        Delivery.event_id == event["id"],
                    )
                )
            )
            assert len(rows) == 1
            ident = rows[0].id
        runner = WebhookWorker(
            app.state.session_factory,
            PinnedSender(guard),
            build_cipher(app.state.runtime_settings),
            flags=app.state.feature_flags,
        )
        # Claim directly to avoid unrelated pending fixtures from earlier tests.
        now = datetime.now(UTC)
        with app.state.session_factory.begin() as session:
            row = session.get(Delivery, ident)
            row.leased_until = now + timedelta(seconds=60)
            lease = aware(row.leased_until)
        assert asyncio.run(runner.attempt((ident, headers["X-Tenant-Id"], endpoint["id"], lease)))
        assert len(seen) == 1
        verify(endpoint["secret"]["value"], seen[0][0], seen[0][1])
        assert seen[0][0]["webhook-id"] == event["id"]
        with app.state.session_factory() as session:
            assert session.get(Delivery, ident).status == "succeeded"
    finally:
        broker.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
