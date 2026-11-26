import logging
import os

from sqlalchemy import text

from app.modules.notifications.application.outbox_publisher import OutboxPublisher

# Register the FK targets even when this entrypoint runs outside the API process.
from app.modules.organization.persistence import Tenant, User  # noqa: F401
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging, configure_telemetry
from app.shared.rabbitmq import RabbitBroker
from app.shared.settings import settings
from app.shared.worker_runtime import WorkerLoop

logger = logging.getLogger(__name__)


def main() -> None:
    configure_telemetry(settings)
    configure_logging()
    sessions = build_session_factory(settings.database_url)
    broker = RabbitBroker(settings.rabbitmq_url.get_secret_value())
    publisher = OutboxPublisher(sessions, broker, batch_size=settings.outbox_batch_size)

    def cycle() -> int:
        published = publisher.publish_pending(should_stop=loop.stopping)
        backlog = publisher.pending_count()
        logger.info(
            "notification_outbox_published",
            extra={"event": "notification_outbox_published", "published": published},
        )
        return backlog

    def ready() -> None:
        if os.getenv("WORKER_RUN_ONCE") != "1":
            broker.connect()
        with sessions() as session:
            session.execute(text("SELECT 1"))

    try:
        loop = WorkerLoop(
            name="outbox",
            cycle=cycle,
            readiness_check=ready,
            poll_seconds=settings.worker_poll_seconds,
            max_backoff_seconds=settings.worker_max_backoff_seconds,
            grace_seconds=settings.worker_shutdown_grace_seconds,
            probe_port=8001,
        )
        loop.run(once=os.getenv("WORKER_RUN_ONCE") == "1")
    finally:
        broker.close()
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
