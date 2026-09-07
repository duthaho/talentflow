from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.shared.database import build_session_factory
from app.shared.models import Base, OutboxEvent


def test_publisher_creates_one_idempotent_notification_delivery() -> None:
    sessions = build_session_factory("sqlite://")
    Base.metadata.create_all(sessions.kw["bind"])
    with sessions() as session:
        session.add(
            OutboxEvent(
                tenant_id="tenant-1",
                topic="offer.approval_recorded.v1",
                payload_json={"offer_id": "offer-1", "decision": "approved", "actor_id": "manager"},
            )
        )
        session.commit()

    publisher = OutboxPublisher(sessions)
    assert publisher.publish_pending() == 1
    assert publisher.publish_pending() == 0

    with sessions() as session:
        from app.shared.models import NotificationDelivery

        delivery = session.query(NotificationDelivery).one()
        assert delivery.recipient_id == "manager"
        assert delivery.status == "pending"
