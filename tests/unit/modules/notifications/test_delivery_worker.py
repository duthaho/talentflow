from datetime import UTC, datetime, timedelta

from app.modules.notifications.application.delivery_worker import DeliveryWorker
from app.shared.database import build_session_factory
from app.shared.models import Base, NotificationDelivery, OutboxEvent, Tenant, User


def test_failed_delivery_retries_then_dead_letters() -> None:
    sessions = build_session_factory("sqlite://")
    engine = sessions.kw["bind"]
    Base.metadata.create_all(engine)
    with sessions() as session:
        session.add_all(
            [
                Tenant(id="tenant", name="Acme", slug="acme"),
                User(id="user"),
                OutboxEvent(id="event", tenant_id="tenant", topic="test", payload_json={}),
            ]
        )
        session.flush()
        session.add(
            NotificationDelivery(
                outbox_event_id="event", tenant_id="tenant", recipient_id="user", payload_json={}
            )
        )
        session.commit()

    worker = DeliveryWorker(
        sessions,
        sender=lambda _: (_ for _ in ()).throw(RuntimeError("SMTP unavailable")),
        max_attempts=2,
    )
    assert worker.deliver_pending() == 0
    assert worker.deliver_pending() == 0
    with sessions() as session:
        delivery = session.query(NotificationDelivery).one()
        assert delivery.status == "dead_letter"
        assert delivery.attempts == 2
    engine.dispose()


def test_expired_processing_lease_is_reclaimed_once() -> None:
    sessions = build_session_factory("sqlite://")
    engine = sessions.kw["bind"]
    Base.metadata.create_all(engine)
    with sessions() as session:
        session.add_all(
            [
                Tenant(id="tenant", name="Acme", slug="acme"),
                User(id="user"),
                OutboxEvent(id="event", tenant_id="tenant", topic="test", payload_json={}),
            ]
        )
        session.flush()
        session.add(
            NotificationDelivery(
                outbox_event_id="event",
                tenant_id="tenant",
                recipient_id="user",
                payload_json={},
                status="processing",
                lease_owner="crashed-worker",
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        session.commit()

    delivered_ids: list[str] = []
    worker = DeliveryWorker(sessions, sender=lambda delivery: delivered_ids.append(delivery.id))

    assert worker.deliver_pending() == 1
    assert len(delivered_ids) == 1
    with sessions() as session:
        delivery = session.query(NotificationDelivery).one()
        assert delivery.status == "delivered"
        assert delivery.attempts == 1
        assert delivery.lease_owner is None
        assert delivery.lease_expires_at is None
    engine.dispose()
