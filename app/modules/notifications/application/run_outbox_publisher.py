import logging

from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging
from app.shared.settings import settings

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    sessions = build_session_factory(settings.database_url)
    try:
        published = OutboxPublisher(sessions).publish_pending()
        logger.info(
            "notification_outbox_published",
            extra={"event": "notification_outbox_published", "published": published},
        )
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
