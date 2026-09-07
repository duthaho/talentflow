from sqlalchemy.orm import sessionmaker

from app.modules.notifications.infrastructure.sendgrid_email import SendGridEmailAdapter
from app.shared.models import NotificationDelivery, User


class SendGridDeliverySender:
    def __init__(self, sessions: sessionmaker, adapter: SendGridEmailAdapter):
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
