from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.calendar.application.calendar_subscription import (
    CalendarEvent,
    CalendarSubscription,
)
from app.shared.models import AuditEvent, Interview, Membership
from app.shared.models import CalendarSubscription as CalendarSubscriptionRecord


class SqlAlchemyCalendarRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def interviewer_exists(self, *, tenant_id: str, interviewer_id: str) -> bool:
        return (
            self._session.scalar(
                select(Membership.user_id).where(
                    Membership.tenant_id == tenant_id,
                    Membership.user_id == interviewer_id,
                    Membership.role == "interviewer",
                )
            )
            is not None
        )

    def add(self, subscription: CalendarSubscription) -> None:
        self._session.add(
            CalendarSubscriptionRecord(
                id=subscription.id,
                tenant_id=subscription.tenant_id,
                interviewer_id=subscription.interviewer_id,
                token_hash=subscription.token_hash,
                created_by=subscription.created_by,
                created_at=subscription.created_at,
                expires_at=subscription.expires_at,
            )
        )

    def get_owned(self, *, subscription_id: str, tenant_id: str) -> CalendarSubscription | None:
        row = self._session.scalar(
            select(CalendarSubscriptionRecord).where(
                CalendarSubscriptionRecord.id == subscription_id,
                CalendarSubscriptionRecord.tenant_id == tenant_id,
                CalendarSubscriptionRecord.revoked_at.is_(None),
            )
        )
        return _subscription(row) if row else None

    def revoke(self, subscription: CalendarSubscription) -> None:
        row = self._session.get(CalendarSubscriptionRecord, subscription.id)
        if row is not None:
            row.revoked_at = datetime.now(UTC)

    def get_active_by_token_hash(self, *, token_hash: str, now) -> CalendarSubscription | None:
        row = self._session.scalar(
            select(CalendarSubscriptionRecord).where(
                CalendarSubscriptionRecord.token_hash == token_hash,
                CalendarSubscriptionRecord.revoked_at.is_(None),
                CalendarSubscriptionRecord.expires_at > now,
            )
        )
        return _subscription(row) if row else None

    def events_for_interviewer(self, *, tenant_id: str, interviewer_id: str) -> list[CalendarEvent]:
        rows = self._session.scalars(
            select(Interview)
            .where(Interview.tenant_id == tenant_id, Interview.interviewer_id == interviewer_id)
            .order_by(Interview.scheduled_at)
        )
        return [CalendarEvent(id=row.id, scheduled_at=_utc(row.scheduled_at)) for row in rows]

    def audit(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        aggregate_id: str,
        metadata: dict[str, object],
    ) -> None:
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                aggregate_type="calendar_subscription",
                aggregate_id=aggregate_id,
                correlation_id=aggregate_id,
                metadata_json=metadata,
            )
        )

    def commit(self) -> None:
        self._session.commit()


def _subscription(row: CalendarSubscriptionRecord) -> CalendarSubscription:
    return CalendarSubscription(
        id=row.id,
        tenant_id=row.tenant_id,
        interviewer_id=row.interviewer_id,
        token_hash=row.token_hash,
        created_by=row.created_by,
        created_at=_utc(row.created_at),
        expires_at=_utc(row.expires_at),
    )


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)
