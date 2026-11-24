from typing import Protocol

from sqlalchemy.orm import sessionmaker

from app.modules.notifications.persistence import NotificationDelivery
from app.modules.organization.persistence import User


class EmailAdapter(Protocol):
    def send(self, *, recipient: str, subject: str, text: str) -> None: ...


class EmailDeliverySender:
    """Maps a notification delivery into an email through the application port."""

    def __init__(self, sessions: sessionmaker, adapter: EmailAdapter):
        self.sessions = sessions
        self.adapter = adapter

    def __call__(self, delivery: NotificationDelivery) -> None:
        with self.sessions() as session:
            recipient = session.get(User, delivery.recipient_id)
            if recipient is None or not recipient.email:
                raise ValueError("Notification recipient has no email address")
        decision = str(delivery.payload_json.get("decision", "updated"))
        self.adapter.send(
            recipient=recipient.email,
            subject="TalentFlow offer approval update",
            text=f"An offer approval was recorded with decision: {decision}.",
        )
