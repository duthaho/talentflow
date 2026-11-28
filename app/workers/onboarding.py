"""Composition root for broker ingress and durable onboarding timers."""

from sqlalchemy import text

import app.shared.models  # noqa: F401
from app.modules.feature_flags.infrastructure.openfeature import OpenFeatureFlags
from app.modules.onboarding.application.run_due import DueStepRunner
from app.modules.onboarding.infrastructure.adapters import HttpHris, KeycloakDirectory
from app.modules.onboarding.infrastructure.consumer import OnboardingConsumer
from app.modules.onboarding.infrastructure.faults import FaultInjectingDirectory, FaultInjectingHris
from app.modules.onboarding.infrastructure.repository import SqlAlchemySagaRepository
from app.modules.onboarding.infrastructure.settings import OnboardingSettings
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging, configure_telemetry
from app.shared.rabbitmq import RabbitBroker
from app.shared.settings import settings
from app.shared.worker_runtime import WorkerLoop


def main():
    configuration = OnboardingSettings()
    configure_logging()
    configure_telemetry(settings)
    # Importing registers commit-only metric hooks in this process.
    from app.modules.onboarding.infrastructure.metrics import refresh_running

    sessions = build_session_factory(settings.database_url)
    broker = RabbitBroker(
        settings.rabbitmq_url.get_secret_value(),
        consumer="onboarding",
        bindings=("candidate_case.stage_changed.v1", "candidate_case.erased.v1"),
    )
    flags = OpenFeatureFlags(settings)
    repository = SqlAlchemySagaRepository(sessions, faults=configuration.faults)
    consumer = OnboardingConsumer(sessions, broker, repository, flags)
    runner = DueStepRunner(
        repository,
        FaultInjectingHris(HttpHris(configuration), configuration.faults),
        FaultInjectingDirectory(KeycloakDirectory(configuration), configuration.faults),
    )

    def cycle():
        remaining = consumer.drain(should_stop=loop.stopping)
        count = runner.run_due()
        refresh_running(sessions)
        return remaining + count

    def ready():
        broker.connect()
        with sessions() as session:
            session.execute(text("SELECT 1"))

    try:
        loop = WorkerLoop(
            name="onboarding",
            cycle=cycle,
            readiness_check=ready,
            poll_seconds=settings.worker_poll_seconds,
            max_backoff_seconds=settings.worker_max_backoff_seconds,
            grace_seconds=settings.worker_shutdown_grace_seconds,
            probe_port=8005,
        )
        loop.run()
    finally:
        flags.close()
        broker.close()
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
