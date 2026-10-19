from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from opentelemetry import trace
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import sessionmaker

from app.shared.models import NotificationDelivery
from app.shared.observability import dead_letters, delivery_attempts, worker_claims

Sender = Callable[[NotificationDelivery], None]
tracer = trace.get_tracer(__name__)


class DeliveryWorker:
    def __init__(
        self,
        sessions: sessionmaker,
        *,
        sender: Sender,
        max_attempts: int = 5,
        lease_seconds: int = 60,
        worker_id: str | None = None,
    ):
        self.sessions = sessions
        self.sender = sender
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.worker_id = worker_id or str(uuid4())

    def deliver_pending(self) -> int:
        delivered = 0
        while delivery := self._claim_next():
            with tracer.start_as_current_span("notification.delivery") as span:
                span.set_attribute("notification.delivery_id", delivery.id)
                try:
                    self.sender(delivery)
                except Exception as error:
                    self._fail(delivery.id, str(error))
                else:
                    self._mark_delivered(delivery.id)
                    delivered += 1
        return delivered

    def _claim_next(self) -> NotificationDelivery | None:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.lease_seconds)
        eligible = or_(
            NotificationDelivery.status.in_(("pending", "retry")),
            and_(
                NotificationDelivery.status == "processing",
                NotificationDelivery.lease_expires_at.is_not(None),
                NotificationDelivery.lease_expires_at <= now,
            ),
        )
        with self.sessions() as session:
            candidate_id = session.scalar(
                select(NotificationDelivery.id)
                .where(eligible)
                .order_by(NotificationDelivery.created_at)
                .limit(1)
            )
            if candidate_id is None:
                worker_claims.labels("empty").inc()
                return None
            result = session.execute(
                update(NotificationDelivery)
                .where(NotificationDelivery.id == candidate_id, eligible)
                .values(
                    status="processing",
                    attempts=NotificationDelivery.attempts + 1,
                    lease_owner=self.worker_id,
                    lease_expires_at=expires_at,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                worker_claims.labels("contended").inc()
                return None
            delivery = session.get(NotificationDelivery, candidate_id)
            session.commit()
            worker_claims.labels("claimed").inc()
            return delivery

    def _mark_delivered(self, delivery_id: str) -> None:
        with self.sessions() as session:
            result = session.execute(
                update(NotificationDelivery)
                .where(
                    NotificationDelivery.id == delivery_id,
                    NotificationDelivery.status == "processing",
                    NotificationDelivery.lease_owner == self.worker_id,
                )
                .values(
                    status="delivered", lease_owner=None, lease_expires_at=None, last_error=None
                )
            )
            session.commit()
        if result.rowcount == 1:
            delivery_attempts.labels("delivered").inc()

    def _fail(self, delivery_id: str, error: str) -> None:
        with self.sessions() as session:
            delivery = session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.id == delivery_id,
                    NotificationDelivery.status == "processing",
                    NotificationDelivery.lease_owner == self.worker_id,
                )
            )
            if delivery is None:
                return
            delivery.last_error = error[:1000]
            delivery.status = "dead_letter" if delivery.attempts >= self.max_attempts else "retry"
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            session.commit()
            terminal = delivery.status == "dead_letter"
        delivery_attempts.labels("dead_letter" if terminal else "retry").inc()
        if terminal:
            dead_letters.inc()
