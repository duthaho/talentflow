from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.shared.models import NotificationDelivery, OutboxEvent


class OutboxPublisher:
    def __init__(self, sessions: sessionmaker):
        self.sessions = sessions

    def publish_pending(self) -> int:
        with self.sessions() as session:
            events = session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.status == "pending")
                .order_by(OutboxEvent.created_at)
            ).all()
            published = 0
            for event in events:
                existing = session.scalar(
                    select(NotificationDelivery).where(
                        NotificationDelivery.outbox_event_id == event.id
                    )
                )
                if existing is None:
                    recipient_id = str(event.payload_json["actor_id"])
                    session.add(
                        NotificationDelivery(
                            outbox_event_id=event.id,
                            tenant_id=event.tenant_id,
                            recipient_id=recipient_id,
                            payload_json=event.payload_json,
                        )
                    )
                    published += 1
                event.status = "published"
            session.commit()
            return published
