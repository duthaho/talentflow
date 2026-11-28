"""RabbitMQ fanout and leased webhook HTTP delivery worker."""

from sqlalchemy import text

import app.shared.models  # noqa: F401
from app.modules.feature_flags.infrastructure.openfeature import OpenFeatureFlags
from app.modules.webhooks.application.contracts import EVENT_TYPES
from app.modules.webhooks.infrastructure.cipher import build_cipher
from app.modules.webhooks.infrastructure.consumer import WebhookConsumer
from app.modules.webhooks.infrastructure.egress import EgressGuard, PinnedSender, parse_allowlist
from app.modules.webhooks.infrastructure.maintenance import expire_secrets
from app.modules.webhooks.infrastructure.worker import WebhookWorker
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging, configure_telemetry
from app.shared.rabbitmq import RabbitBroker
from app.shared.settings import settings
from app.shared.worker_runtime import WorkerLoop


def main():
    configure_telemetry(settings)
    configure_logging()
    sessions = build_session_factory(settings.database_url)
    broker = RabbitBroker(
        settings.rabbitmq_url.get_secret_value(), consumer="webhooks", bindings=tuple(EVENT_TYPES)
    )
    consumer = WebhookConsumer(sessions, broker)
    flags = OpenFeatureFlags(settings)
    worker = WebhookWorker(
        sessions,
        PinnedSender(
            EgressGuard(
                allow_http=settings.webhook_allow_http,
                allowlist=parse_allowlist(settings.webhook_private_network_allowlist),
            )
        ),
        build_cipher(settings),
        flags=flags,
    )
    loop: WorkerLoop

    def cycle():
        remaining = consumer.drain(should_stop=loop.stopping)
        worker.deliver_pending(should_stop=loop.stopping)
        with sessions() as session:
            expire_secrets(session, settings.retention_worker_batch_size)
        return remaining + worker.pending_count()

    def ready():
        broker.connect()
        with sessions() as session:
            session.execute(text("SELECT 1"))

    try:
        loop = WorkerLoop(
            name="webhooks",
            cycle=cycle,
            readiness_check=ready,
            shutdown=worker.release_leases,
            poll_seconds=settings.worker_poll_seconds,
            max_backoff_seconds=settings.worker_max_backoff_seconds,
            grace_seconds=settings.worker_shutdown_grace_seconds,
            probe_port=8004,
        )
        loop.run()
    finally:
        flags.close()
        broker.close()
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
