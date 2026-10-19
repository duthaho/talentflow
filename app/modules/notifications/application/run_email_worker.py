import logging

from app.modules.notifications.application.delivery_worker import DeliveryWorker
from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.modules.notifications.application.sendgrid_delivery import SendGridDeliverySender
from app.modules.notifications.infrastructure.sendgrid_email import SendGridEmailAdapter
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging
from app.shared.settings import settings

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    adapter = SendGridEmailAdapter(
        api_key=settings.sendgrid_api_key.get_secret_value() if settings.sendgrid_api_key else "",
        sender=settings.notification_from_email,
    )
    sessions = build_session_factory(settings.database_url)
    try:
        published = OutboxPublisher(sessions).publish_pending()
        worker = DeliveryWorker(
            sessions,
            sender=SendGridDeliverySender(sessions, adapter),
            max_attempts=settings.worker_max_attempts,
            lease_seconds=settings.worker_lease_seconds,
        )
        delivered = worker.deliver_pending()
        logger.info(
            "notification_worker_completed",
            extra={
                "event": "notification_worker_completed",
                "published": published,
                "delivered": delivered,
            },
        )
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
