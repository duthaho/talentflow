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
