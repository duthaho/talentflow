import logging
import os

from sqlalchemy import text

from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging
from app.shared.settings import settings
from app.shared.worker_runtime import WorkerLoop

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    sessions = build_session_factory(settings.database_url)
    publisher = OutboxPublisher(sessions)

    def cycle() -> int:
        published = publisher.publish_pending()
        backlog = publisher.pending_count()
        logger.info(
            "notification_outbox_published",
            extra={"event": "notification_outbox_published", "published": published},
        )
        return backlog

    def ready() -> None:
        with sessions() as session:
            session.execute(text("SELECT 1"))

    try:
        WorkerLoop(
            name="outbox",
            cycle=cycle,
            readiness_check=ready,
            poll_seconds=settings.worker_poll_seconds,
            max_backoff_seconds=settings.worker_max_backoff_seconds,
            grace_seconds=settings.worker_shutdown_grace_seconds,
            probe_port=8001,
        ).run(once=os.getenv("WORKER_RUN_ONCE") == "1")
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
