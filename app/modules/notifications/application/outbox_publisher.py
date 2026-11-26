from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from app.modules.notifications.persistence import OutboxEvent
from app.shared.events import envelope
from app.shared.observability import outbox_backlog


class OutboxPublisher:
    """The only outbox reader. A crash after confirm intentionally republishes stable ids."""

    def __init__(self, sessions: sessionmaker, broker, *, batch_size: int = 100):
        self.sessions = sessions
        self.broker = broker
        self.batch_size = batch_size

    def publish_pending(self, *, should_stop=lambda: False) -> int:
        event_id = None
        try:
            with self.sessions.begin() as session:
                events = session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.status == "pending")
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                ).all()
                published = 0
                for event in events:
                    if should_stop():
                        break
                    event_id = event.id
                    self.broker.publish_event(envelope(event))
                    event.status = "published"
                    event.published_at = datetime.now(UTC)
                    event.publish_attempts += 1
                    event.last_error = None
                    published += 1
        except Exception as error:
            if event_id is not None:
                with self.sessions.begin() as session:
                    session.execute(
                        update(OutboxEvent)
                        .where(OutboxEvent.id == event_id, OutboxEvent.status == "pending")
                        .values(
                            publish_attempts=OutboxEvent.publish_attempts + 1,
                            last_error=type(error).__name__,
                        )
                    )
            raise RuntimeError("outbox_publish_failed") from None
        outbox_backlog.set(self.pending_count())
        return published

    def pending_count(self) -> int:
        with self.sessions() as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.status == "pending")
                )
                or 0
            )
