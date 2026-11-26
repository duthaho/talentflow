import pytest

from app.modules.calendar.application.calendar_subscription import (
    CalendarScope,
    CalendarSubscriptionForbiddenError,
    CalendarSubscriptionService,
)


class SpyRepository:
    def __init__(self) -> None:
        self.calls = 0

    def interviewer_exists(self, **_: object) -> bool:
        self.calls += 1
        return True


def test_self_scope_rejects_foreign_create_before_repository_access() -> None:
    repository = SpyRepository()
    service = CalendarSubscriptionService(repository, lifetime_days=30)  # type: ignore[arg-type]

    with pytest.raises(CalendarSubscriptionForbiddenError):
        service.create(
            tenant_id="tenant-1",
            interviewer_id="interviewer-2",
            actor_id="interviewer-1",
            scope=CalendarScope.SELF,
        )

    assert repository.calls == 0


@pytest.mark.parametrize("scope", [None, "self"])
def test_service_fails_closed_for_unknown_scope(scope: object) -> None:
    repository = SpyRepository()
    service = CalendarSubscriptionService(repository, lifetime_days=30)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        service.create(
            tenant_id="tenant-1",
            interviewer_id=None,
            actor_id="interviewer-1",
            scope=scope,  # type: ignore[arg-type]
        )

    assert repository.calls == 0
