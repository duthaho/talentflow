from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.shared.models import NotificationDelivery

Sender = Callable[[NotificationDelivery], None]


class DeliveryWorker:
    def __init__(self, sessions: sessionmaker, *, sender: Sender, max_attempts: int = 5):
        self.sessions = sessions
        self.sender = sender
        self.max_attempts = max_attempts

    def deliver_pending(self) -> int:
        delivered = 0
        with self.sessions() as session:
            deliveries = session.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.status.in_(("pending", "retry"))
                )
            ).all()
            for delivery in deliveries:
                try:
                    self.sender(delivery)
                except Exception as error:
                    delivery.attempts += 1
                    delivery.last_error = str(error)[:1000]
                    delivery.status = (
                        "dead_letter" if delivery.attempts >= self.max_attempts else "retry"
                    )
                else:
                    delivery.status = "delivered"
                    delivered += 1
            session.commit()
        return delivered
