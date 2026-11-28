from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.onboarding.domain.policy import (
    can_cancel,
    can_retry,
    decide,
    on_outcome,
    validate_start_date,
)


@pytest.mark.parametrize(
    "step,delays",
    [
        ("create_employee", (10, 30, 120, 300)),
        ("provision_account", (10, 30, 120, 300)),
        ("schedule_tasks", (10, 30)),
        ("notify", (10, 30, 120, 300)),
    ],
)
def test_retry_boundaries(step, delays):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for attempt, delay in enumerate(delays, 1):
        assert decide(
            now=now, deadline=None, attempts=attempt, step=step
        ).due_at == now + timedelta(seconds=delay)
        assert (
            decide(
                now=now, deadline=now + timedelta(seconds=delay), attempts=attempt, step=step
            ).action
            == "failed"
        )
    assert decide(now=now, deadline=None, attempts=len(delays) + 1, step=step).action == "failed"
    assert decide(now=now, deadline=None, attempts=1, step=step, permanent=True).action == "failed"


def test_compensation_policy_and_actions():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for i, delay in enumerate((10, 30, 120, 300, 300), 1):
        assert decide(
            now=now, deadline=now, attempts=i, step="create_employee", compensation=True
        ).due_at == now + timedelta(seconds=delay)
    assert (
        decide(now=now, deadline=None, attempts=6, step="create_employee", compensation=True).action
        == "failed"
    )
    assert can_retry("compensated", 4, None)
    assert not can_retry("compensated", 5, None)
    assert not can_retry("compensated", 1, now)
    assert can_cancel("running", False, None)
    assert not can_cancel("running", True, None)
    assert not can_cancel("running", False, "cancel_requested")
    assert on_outcome(step="notify", success=False) == "completed_with_warnings"
    assert on_outcome(step="notify", success=True) == "completed"
    assert on_outcome(step="create_employee", success=False) == "compensating"
    assert on_outcome(step="create_employee", success=True) == "running"
    assert (
        on_outcome(step="create_employee", success=True, compensation=True, reason="step_failed")
        == "compensated"
    )
    assert (
        on_outcome(
            step="create_employee",
            success=True,
            compensation=True,
            reason="step_failed",
            erased=True,
        )
        == "cancelled"
    )


def test_dates():
    today = date(2026, 1, 1)
    for value in (None, today, today + timedelta(days=365)):
        validate_start_date("hired", value, today)
    for value in (today - timedelta(days=1), today + timedelta(days=366)):
        with pytest.raises(ValueError):
            validate_start_date("hired", value, today)
    with pytest.raises(ValueError):
        validate_start_date("screening", today, today)
