"""Bounded-label, commit-only onboarding counters and a persisted-state gauge."""

from prometheus_client import Counter, Gauge
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.modules.onboarding.infrastructure.models import Saga

sagas = Counter("talentflow_onboarding_sagas_total", "Terminal saga outcomes", ["status"])
attempts = Counter(
    "talentflow_onboarding_step_attempts_total", "Step outcomes", ["step", "outcome"]
)
running = Gauge("talentflow_onboarding_running", "Persisted active sagas")
cleanup = Counter(
    "talentflow_onboarding_erasure_cleanup_required", "Erasure requires external cleanup"
)


@event.listens_for(Session, "after_commit")
def committed(session):
    if session.in_nested_transaction():
        return
    for status in session.info.pop("onboarding_outcomes", []):
        sagas.labels(status).inc()
    for step, outcome in session.info.pop("onboarding_attempts", []):
        attempts.labels(step, outcome).inc()
    count = session.info.pop("onboarding_cleanup", 0)
    if count:
        cleanup.inc(count)


@event.listens_for(Session, "after_soft_rollback")
def rolled_back(session, previous_transaction):
    if previous_transaction.parent is not None:
        return
    for key in ("onboarding_outcomes", "onboarding_attempts", "onboarding_cleanup"):
        session.info.pop(key, None)


def refresh_running(sessions):
    with sessions() as session:
        running.set(
            session.scalar(
                select(func.count())
                .select_from(Saga)
                .where(Saga.status.in_(["running", "compensating"]))
            )
            or 0
        )
