"""Real broker + SIGKILL regression. Use a disposable RabbitMQ vhost only."""

import os
import signal
from multiprocessing import get_context
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.notifications.application.event_consumer import NotificationConsumer
from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.shared.database import build_session_factory
from app.shared.models import Base, InboxMessage, NotificationDelivery, OutboxEvent
from app.shared.rabbitmq import RabbitBroker


def _kill_relay_after_confirm(url, db_url):
    broker = RabbitBroker(url)
    original = broker.publish_event

    def kill_after_confirm(event):
        original(event)
        os.kill(os.getpid(), signal.SIGKILL)

    broker.publish_event = kill_after_confirm
    OutboxPublisher(build_session_factory(db_url), broker).publish_pending()


@pytest.mark.skipif(
    not os.getenv("DUTH59_TEST_RABBITMQ_URL"), reason="requires disposable RabbitMQ vhost"
)
def test_sigkill_after_real_publisher_confirm_replays_and_deduplicates(tmp_path: Path):
    url = os.environ["DUTH59_TEST_RABBITMQ_URL"]
    db_url = f"sqlite:///{tmp_path / 'events.db'}"
    sessions = build_session_factory(db_url)
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions.begin() as session:
        for _ in range(3):
            session.add(
                OutboxEvent(
                    tenant_id=str(uuid4()),
                    topic="offer.approval_recorded.v1",
                    payload_json={
                        "offer_id": str(uuid4()),
                        "decision": "approved",
                        "actor_id": "manager",
                    },
                )
            )
    broker = RabbitBroker(url)
    broker.connect()
    # Fork the already-imported test harness; the child opens its own DB/AMQP connections.
    # This avoids charging repeated framework imports to the crash-recovery deadline.
    child = get_context("fork").Process(target=_kill_relay_after_confirm, args=(url, db_url))
    try:
        child.start()
        child.join(timeout=30)
        if child.is_alive():
            child.kill()
            child.join()
            pytest.fail("relay child did not reach its publisher-confirm boundary")
        assert child.exitcode == -signal.SIGKILL
        assert broker.depths()["notifications.events"] == 1
        with sessions() as session:
            assert all(row.status == "pending" for row in session.scalars(select(OutboxEvent)))
        assert OutboxPublisher(sessions, broker).publish_pending() == 3
        consumer = NotificationConsumer(sessions, broker)
        assert consumer.drain() == 0
        with sessions() as session:
            assert session.query(InboxMessage).count() == 3
            assert session.query(NotificationDelivery).count() == 3
        from app.modules.notifications.application.delivery_worker import DeliveryWorker

        delivered = []
        delivery_worker = DeliveryWorker(sessions, sender=lambda row: delivered.append(row.id))
        assert delivery_worker.deliver_pending() == 3
        assert delivery_worker.deliver_pending() == 0
        assert len(set(delivered)) == 3
        # Exercise the actual broker's poison DLQ and metric surface too.
        import pika

        broker.publish(
            "talentflow.events",
            "offer.approval_recorded.v1",
            b"not json",
            pika.BasicProperties(delivery_mode=2),
        )
        consumer.drain()
        assert broker.depths()["notifications.dlq"] == 1
        from prometheus_client import generate_latest

        metrics = generate_latest().decode()
        assert 'talentflow_broker_queue_depth{queue="notifications.dlq"} 1.0' in metrics
        method, props, body = broker.channel.basic_get("notifications.dlq", auto_ack=False)
        assert body == b"not json"
        assert props.headers["x-tf-failure"] == "poison"
        broker.ack(method.delivery_tag)
        # A broker nack/return never marks an outbox event published.
        with pytest.raises(pika.exceptions.UnroutableError):
            broker.publish("talentflow.retry", "missing.binding", b"{}", pika.BasicProperties())
    finally:
        broker.close()
        sessions.kw["bind"].dispose()


@pytest.mark.skipif(
    not os.getenv("DUTH59_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL database"
)
def test_postgres_inbox_race_and_relay_skip_locked():
    from concurrent.futures import ThreadPoolExecutor

    from app.shared.events import envelope
    from app.shared.models import Tenant, User

    sessions = build_session_factory(os.environ["DUTH59_TEST_POSTGRES_URL"])
    tenant_id, user_id, event_id = str(uuid4()), str(uuid4()), str(uuid4())
    with sessions.begin() as session:
        session.add(Tenant(id=tenant_id, name="Messaging test", slug=tenant_id))
        session.add(User(id=user_id))
    with sessions.begin() as session:
        session.add(
            OutboxEvent(
                id=event_id,
                tenant_id=tenant_id,
                topic="offer.approval_recorded.v1",
                payload_json={
                    "offer_id": str(uuid4()),
                    "decision": "approved",
                    "actor_id": user_id,
                },
            )
        )
    try:
        with sessions() as session:
            event = envelope(session.get(OutboxEvent, event_id))
        consumer = NotificationConsumer(sessions, None)
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: consumer.apply(event), range(2)))
        assert sorted(outcomes) == [False, True]

        class Sink:
            def __init__(self):
                self.events = []

            def publish_event(self, event):
                self.events.append(event)

        sink = Sink()
        with sessions.begin() as locker:
            locker.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
            OutboxPublisher(sessions, sink).publish_pending()
            assert event_id not in [e["id"] for e in sink.events]
        OutboxPublisher(sessions, sink).publish_pending()
        assert [e["id"] for e in sink.events].count(event_id) == 1
        with sessions() as session:
            assert (
                len(
                    session.scalars(
                        select(NotificationDelivery).where(
                            NotificationDelivery.outbox_event_id == event_id
                        )
                    ).all()
                )
                == 1
            )
    finally:
        from sqlalchemy import delete

        with sessions.begin() as session:
            session.execute(delete(InboxMessage).where(InboxMessage.event_id == event_id))
            session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            session.execute(delete(User).where(User.id == user_id))
        sessions.kw["bind"].dispose()
