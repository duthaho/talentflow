"""Stable retry policy. Time is supplied by callers, never read here."""

from dataclasses import dataclass
from datetime import datetime, timedelta

STEPS = ("create_employee", "provision_account", "schedule_tasks", "notify")
TASKS = {
    "laptop": "Prepare laptop",
    "accounts": "Prepare accounts",
    "buddy": "Assign buddy",
    "orientation": "Schedule orientation",
}
TERMINAL = frozenset(
    {"compensated", "completed", "completed_with_warnings", "cancelled", "compensation_failed"}
)


@dataclass(frozen=True)
class StepPolicy:
    timeout: int | None
    delays: tuple[int, ...]
    deadline: int
    compensable: bool


STEP_POLICIES = {
    "create_employee": StepPolicy(5, (10, 30, 120, 300), 900, True),
    "provision_account": StepPolicy(5, (10, 30, 120, 300), 900, True),
    "schedule_tasks": StepPolicy(None, (10, 30), 300, True),
    "notify": StepPolicy(None, (10, 30, 120, 300), 1800, False),
}
COMPENSATION_DELAYS = (10, 30, 120, 300, 300)


class TransientStepError(Exception):
    pass


class PermanentStepError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class AttemptTimeout(TransientStepError):
    pass


class DirectoryConflict(PermanentStepError):
    def __init__(self):
        super().__init__("directory_conflict")


def can_retry(status, attempt, erased_at):
    return status == "compensated" and attempt < 5 and erased_at is None


def can_cancel(status, past_pivot, reason):
    return status == "running" and not past_pivot and reason is None


@dataclass(frozen=True)
class Decision:
    action: str
    due_at: datetime | None = None


def decide(*, now, deadline, attempts, step, compensation=False, permanent=False):
    """Decide the next action after a failed attempt, including deadline boundaries."""
    delays = COMPENSATION_DELAYS if compensation else STEP_POLICIES[step].delays
    if permanent or attempts > len(delays):
        return Decision("failed")
    due = now + timedelta(seconds=delays[max(0, attempts - 1)])
    if not compensation and deadline is not None and due >= deadline:
        return Decision("failed")
    return Decision("retry", due)


def on_outcome(*, step, success, compensation=False, reason=None, erased=False):
    """Terminal outcome rule, independent of persistence and external adapters."""
    if compensation:
        return "cancelled" if erased or reason != "step_failed" else "compensated"
    if step == "notify":
        return "completed" if success else "completed_with_warnings"
    return "running" if success else "compensating"
