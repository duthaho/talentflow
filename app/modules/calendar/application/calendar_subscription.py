from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
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


class CalendarScope(StrEnum):
    MANAGE = "manage"
    SELF = "self"


class CalendarRepository(Protocol):
    def interviewer_exists(self, *, tenant_id: str, interviewer_id: str) -> bool: ...
    def add(self, subscription: CalendarSubscription) -> None: ...
    def get_owned(
        self, *, subscription_id: str, tenant_id: str, interviewer_id: str | None
    ) -> CalendarSubscription | None: ...
    def list_active(
        self, *, tenant_id: str, interviewer_id: str, now: datetime
    ) -> list[CalendarSubscription]: ...
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


class CalendarSubscriptionForbiddenError(PermissionError):
    pass


class CalendarSubscriptionService:
    def __init__(self, repository: CalendarRepository, *, lifetime_days: int) -> None:
        self._repository = repository
        self._lifetime_days = lifetime_days

    def create(
        self,
        *,
        tenant_id: str,
        interviewer_id: str | None,
        actor_id: str,
        scope: CalendarScope,
    ) -> tuple[CalendarSubscription, str]:
        target_id = self._target_id(interviewer_id=interviewer_id, actor_id=actor_id, scope=scope)
        if not self._repository.interviewer_exists(tenant_id=tenant_id, interviewer_id=target_id):
            raise CalendarSubscriptionNotFoundError(target_id)
        now = datetime.now(UTC)
        token = token_urlsafe(32)
        subscription = CalendarSubscription(
            id=token_urlsafe(18),
            tenant_id=tenant_id,
            interviewer_id=target_id,
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
                "interviewer_id": target_id,
                "expires_at": subscription.expires_at.isoformat(),
                "scope": scope.value,
            },
        )
        self._repository.commit()
        return subscription, token

    def revoke(
        self, *, subscription_id: str, tenant_id: str, actor_id: str, scope: CalendarScope
    ) -> None:
        self._validate_scope(scope)
        subscription = self._repository.get_owned(
            subscription_id=subscription_id,
            tenant_id=tenant_id,
            interviewer_id=actor_id if scope is CalendarScope.SELF else None,
        )
        if subscription is None:
            raise CalendarSubscriptionNotFoundError(subscription_id)
        self._repository.revoke(subscription)
        self._repository.audit(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="calendar_subscription.revoked",
            aggregate_id=subscription.id,
            metadata={"interviewer_id": subscription.interviewer_id, "scope": scope.value},
        )
        self._repository.commit()

    def list_active(
        self,
        *,
        tenant_id: str,
        interviewer_id: str,
        actor_id: str,
        scope: CalendarScope,
    ) -> list[CalendarSubscription]:
        target_id = self._target_id(interviewer_id=interviewer_id, actor_id=actor_id, scope=scope)
        return self._repository.list_active(
            tenant_id=tenant_id, interviewer_id=target_id, now=datetime.now(UTC)
        )

    def calendar_for_token(self, token: str) -> tuple[CalendarSubscription, list[CalendarEvent]]:
        subscription = self._repository.get_active_by_token_hash(
            token_hash=_hash(token), now=datetime.now(UTC)
        )
        if subscription is None:
            raise CalendarSubscriptionNotFoundError(token)
        return subscription, self._repository.events_for_interviewer(
            tenant_id=subscription.tenant_id, interviewer_id=subscription.interviewer_id
        )

    @staticmethod
    def _target_id(*, interviewer_id: str | None, actor_id: str, scope: CalendarScope) -> str:
        CalendarSubscriptionService._validate_scope(scope)
        target_id = interviewer_id or actor_id
        if scope is CalendarScope.SELF and target_id != actor_id:
            raise CalendarSubscriptionForbiddenError(
                "Calendar subscription access is limited to self"
            )
        return actor_id if scope is CalendarScope.SELF else target_id

    @staticmethod
    def _validate_scope(scope: CalendarScope) -> None:
        if not isinstance(scope, CalendarScope):
            raise ValueError("Calendar subscription scope is invalid")


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
