from app.modules.notifications.application.sendgrid_delivery import SendGridDeliverySender
from app.shared.database import build_session_factory
from app.shared.models import Base, NotificationDelivery, OutboxEvent, Tenant, User


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def send(self, *, recipient: str, subject: str, text: str) -> None:
        self.calls.append({"recipient": recipient, "subject": subject, "text": text})


def test_sendgrid_delivery_sender_uses_recipient_user_email() -> None:
    sessions = build_session_factory("sqlite://")
    engine = sessions.kw["bind"]
    Base.metadata.create_all(engine)
    with sessions() as session:
        session.add_all(
            [
                Tenant(id="tenant", name="Acme", slug="acme"),
                User(id="manager", email="manager@example.com"),
                OutboxEvent(
                    id="event",
                    tenant_id="tenant",
                    topic="offer.approval_recorded.v1",
                    payload_json={},
                ),
            ]
        )
        session.flush()
        session.add(
            NotificationDelivery(
                outbox_event_id="event",
                tenant_id="tenant",
                recipient_id="manager",
                payload_json={"decision": "approved"},
            )
        )
        session.commit()
        delivery = session.query(NotificationDelivery).one()
        adapter = FakeAdapter()
        SendGridDeliverySender(sessions, adapter)(delivery)
    assert adapter.calls[0]["recipient"] == "manager@example.com"
    assert "approved" in adapter.calls[0]["text"]
    engine.dispose()
