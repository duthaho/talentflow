from uuid import uuid4

import pika
import pytest
from sqlalchemy import select

from app.modules.notifications.application.event_consumer import NotificationConsumer, decode_event
from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.shared.database import build_session_factory
from app.shared.events import envelope
from app.shared.models import Base, InboxMessage, NotificationDelivery, OutboxEvent


class Broker:
    def __init__(self):
        self.events = []
        self.sent = []
        self.acks = []
        self.requeued = []
        self.messages = []
        self.fail_publish = False

    def publish_event(self, event):
        self.events.append(event)

    def publish(self, exchange, key, body, properties):
        if self.fail_publish:
            raise OSError("sensitive information")
        self.sent.append((exchange, key, body, properties))

    def get(self):
        return self.messages.pop(0) if self.messages else (None, None, None)

    def ack(self, tag):
        self.acks.append(tag)

    def requeue(self, tag):
        self.requeued.append(tag)

    def depths(self):
        return {"notifications.events": 0, "notifications.dlq": 0, "talentflow.unrouted": 0}


@pytest.fixture
def storage():
    sessions = build_session_factory("sqlite://")
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions.begin() as session:
        for _ in range(2):
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
    yield sessions
    sessions.kw["bind"].dispose()


def test_confirm_then_crash_rolls_back_batch_and_replays_stable_ids(storage):
    broker = Broker()
    original = broker.publish_event

    def crash(event):
        original(event)
        if len(broker.events) == 2:
            raise SystemExit("killed after broker confirmed")

    broker.publish_event = crash
    with pytest.raises(SystemExit):
        OutboxPublisher(storage, broker).publish_pending()
    with storage() as session:
        assert all(row.status == "pending" for row in session.scalars(select(OutboxEvent)))
    broker.publish_event = original
    publisher = OutboxPublisher(storage, broker)
    assert publisher.publish_pending() == 2
    assert publisher.publish_pending() == 0
    assert broker.events[:2] == broker.events[2:]
    consumer = NotificationConsumer(storage, broker)
    for event in broker.events:
        consumer.apply(event)
    with storage() as session:
        assert session.query(NotificationDelivery).count() == 2
        assert session.query(InboxMessage).count() == 2
        assert all(row.published_at is not None for row in session.scalars(select(OutboxEvent)))


def test_failed_confirm_stays_pending_and_logs_only_error_class(storage):
    broker = Broker()

    def fail(event):
        raise OSError("sensitive information")

    broker.publish_event = fail
    with pytest.raises(RuntimeError, match="outbox_publish_failed"):
        OutboxPublisher(storage, broker).publish_pending()
    with storage() as session:
        rows = session.scalars(select(OutboxEvent)).all()
        assert all(row.status == "pending" for row in rows)
        failed = next(row for row in rows if row.publish_attempts)
        assert failed.last_error == "OSError"


def message(body, attempt=0):
    from types import SimpleNamespace

    return (
        SimpleNamespace(delivery_tag=42),
        pika.BasicProperties(headers={"x-tf-attempt": attempt}),
        body,
    )


@pytest.mark.parametrize(
    "attempt,exchange,key,outcome",
    [
        (0, "talentflow.retry", "notifications.retry.1", "retry"),
        (1, "talentflow.retry", "notifications.retry.2", "retry"),
        (2, "talentflow.retry", "notifications.retry.3", "retry"),
        (3, "talentflow.dead-letter", "notifications", "exhausted"),
    ],
)
def test_transient_retries_confirm_before_ack_and_eventually_dlq(
    storage, attempt, exchange, key, outcome
):
    import json

    broker = Broker()
    with storage() as session:
        event = envelope(session.scalars(select(OutboxEvent)).first())
    body = json.dumps(event).encode()
    broker.messages = [message(body, attempt)]
    consumer = NotificationConsumer(storage, broker)

    def fail(event):
        raise OSError("secret error text")

    consumer.apply = fail
    consumer.drain()
    sent = broker.sent[0]
    assert sent[:3] == (exchange, key, body)
    assert broker.acks == [42]
    if outcome == "exhausted":
        assert sent[3].headers["x-tf-failure"] == "exhausted"
        assert sent[3].headers["x-tf-error"] == "OSError"
        assert "secret" not in str(sent[3].headers)
    else:
        assert sent[3].headers["x-tf-attempt"] == attempt + 1


def test_poison_immediately_dead_letters_and_failed_republish_does_not_ack(storage):
    broker = Broker()
    broker.messages = [message(b"not json")]
    NotificationConsumer(storage, broker).drain()
    assert broker.sent[0][0] == "talentflow.dead-letter"
    assert broker.sent[0][3].headers["x-tf-failure"] == "poison"
    assert broker.acks == [42]
    broker.messages = [message(b"not json")]
    broker.acks.clear()
    broker.fail_publish = True
    with pytest.raises(RuntimeError, match="consumer_republish_failed"):
        NotificationConsumer(storage, broker).drain()
    assert broker.acks == []
    assert broker.requeued == [42]


def test_consumer_commit_before_ack_crash_redelivers_without_second_effect(storage):
    import json

    broker = Broker()
    with storage() as session:
        event = envelope(session.scalars(select(OutboxEvent)).first())
    broker.messages = [message(json.dumps(event).encode())]

    def crash(tag):
        raise SystemExit()

    ack = broker.ack
    broker.ack = crash
    with pytest.raises(SystemExit):
        NotificationConsumer(storage, broker).drain()
    broker.ack = ack
    broker.messages = [message(json.dumps(event).encode())]
    NotificationConsumer(storage, broker).drain()
    with storage() as session:
        assert session.query(NotificationDelivery).count() == 1
        assert session.query(InboxMessage).count() == 1
    assert broker.acks == [42]


def test_tenant_mismatch_rolls_back_inbox(storage):
    from app.modules.notifications.application.event_consumer import PoisonMessage

    with storage() as session:
        event = envelope(session.scalars(select(OutboxEvent)).first())
    event["tenantid"] = str(uuid4())
    with pytest.raises(PoisonMessage):
        NotificationConsumer(storage, Broker()).apply(event)
    with storage() as session:
        assert session.query(InboxMessage).count() == 0
        assert session.query(NotificationDelivery).count() == 0


def test_shutdown_stops_before_next_event(storage):
    broker = Broker()
    assert OutboxPublisher(storage, broker).publish_pending(should_stop=lambda: True) == 0
    assert broker.events == []


def test_legacy_envelope_and_future_enum(storage):
    import json

    with storage() as session:
        event = envelope(session.scalars(select(OutboxEvent)).first())
    assert event["correlationid"] == event["id"] == event["causationid"]
    event["data"]["decision"] = "future_decision"
    assert decode_event(json.dumps(event).encode()) == event
    NotificationConsumer(storage, Broker()).apply(event)
    with storage() as session:
        assert session.query(InboxMessage).count() == 1
        assert session.query(NotificationDelivery).count() == 0


def test_tolerant_reader_ignores_added_payload_fields(storage):
    with storage() as session:
        event = envelope(session.scalars(select(OutboxEvent)).first())
    event["data"] = {**event["data"], "future_optional_id": str(uuid4())}
    assert NotificationConsumer(storage, Broker()).apply(event)
    with storage() as session:
        assert session.query(NotificationDelivery).count() == 1


def test_business_transaction_rollback_removes_its_event(storage):
    from app.shared.events import record_event

    with storage() as session:
        record_event(
            session,
            topic="candidate_case.created.v1",
            tenant_id=str(uuid4()),
            subject=str(uuid4()),
            data={},
        )
        session.flush()
        session.rollback()
    with storage() as session:
        assert session.query(OutboxEvent).filter_by(topic="candidate_case.created.v1").count() == 0
