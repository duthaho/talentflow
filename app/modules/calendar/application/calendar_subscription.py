from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol


@dataclass(frozen=True)
class CalendarSubscription:
    id: str
    tenant_id: str
    interviewer_id: str
    token_hash: str
    created_by: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    scheduled_at: datetime


class CalendarRepository(Protocol):
    def interviewer_exists(self, *, tenant_id: str, interviewer_id: str) -> bool: ...
    def add(self, subscription: CalendarSubscription) -> None: ...
    def get_owned(self, *, subscription_id: str, tenant_id: str) -> CalendarSubscription | None: ...
    def revoke(self, subscription: CalendarSubscription) -> None: ...
    def get_active_by_token_hash(
        self, *, token_hash: str, now: datetime
    ) -> CalendarSubscription | None: ...
    def events_for_interviewer(
        self, *, tenant_id: str, interviewer_id: str
    ) -> list[CalendarEvent]: ...
    def audit(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        aggregate_id: str,
        metadata: dict[str, object],
    ) -> None: ...
    def commit(self) -> None: ...


class CalendarSubscriptionNotFoundError(LookupError):
    pass


class CalendarSubscriptionService:
    def __init__(self, repository: CalendarRepository, *, lifetime_days: int) -> None:
        self._repository = repository
        self._lifetime_days = lifetime_days

    def create(
        self, *, tenant_id: str, interviewer_id: str, actor_id: str
    ) -> tuple[CalendarSubscription, str]:
        if not self._repository.interviewer_exists(
            tenant_id=tenant_id, interviewer_id=interviewer_id
        ):
            raise CalendarSubscriptionNotFoundError(interviewer_id)
        now = datetime.now(UTC)
        token = token_urlsafe(32)
        subscription = CalendarSubscription(
            id=token_urlsafe(18),
            tenant_id=tenant_id,
            interviewer_id=interviewer_id,
            token_hash=_hash(token),
            created_by=actor_id,
            created_at=now,
            expires_at=now + timedelta(days=self._lifetime_days),
        )
        self._repository.add(subscription)
        self._repository.audit(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="calendar_subscription.created",
            aggregate_id=subscription.id,
            metadata={
                "interviewer_id": interviewer_id,
                "expires_at": subscription.expires_at.isoformat(),
            },
        )
        self._repository.commit()
        return subscription, token

    def revoke(self, *, subscription_id: str, tenant_id: str, actor_id: str) -> None:
        subscription = self._repository.get_owned(
            subscription_id=subscription_id, tenant_id=tenant_id
        )
        if subscription is None:
            raise CalendarSubscriptionNotFoundError(subscription_id)
        self._repository.revoke(subscription)
        self._repository.audit(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="calendar_subscription.revoked",
            aggregate_id=subscription.id,
            metadata={"interviewer_id": subscription.interviewer_id},
        )
        self._repository.commit()

    def calendar_for_token(self, token: str) -> tuple[CalendarSubscription, list[CalendarEvent]]:
        subscription = self._repository.get_active_by_token_hash(
            token_hash=_hash(token), now=datetime.now(UTC)
        )
        if subscription is None:
            raise CalendarSubscriptionNotFoundError(token)
        return subscription, self._repository.events_for_interviewer(
            tenant_id=subscription.tenant_id, interviewer_id=subscription.interviewer_id
        )


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
