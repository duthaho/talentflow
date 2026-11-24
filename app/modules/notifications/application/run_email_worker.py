import logging

from app.modules.notifications.application.delivery_worker import DeliveryWorker
from app.modules.notifications.application.email_delivery import EmailAdapter, EmailDeliverySender
from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.modules.notifications.infrastructure.sendgrid_email import SendGridEmailAdapter
from app.modules.notifications.infrastructure.smtp_email import SmtpEmailAdapter
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging
from app.shared.settings import settings

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    adapter: EmailAdapter
    if settings.notification_email_adapter == "sendgrid":
        adapter = SendGridEmailAdapter(
            api_key=settings.sendgrid_api_key.get_secret_value()
            if settings.sendgrid_api_key
            else "",
            sender=settings.notification_from_email,
        )
    else:
        adapter = SmtpEmailAdapter(
            host=settings.notification_smtp_host,
            port=settings.notification_smtp_port,
            sender=settings.notification_from_email,
        )
    sessions = build_session_factory(settings.database_url)
    try:
        published = OutboxPublisher(sessions).publish_pending()
        worker = DeliveryWorker(
            sessions,
            sender=EmailDeliverySender(sessions, adapter),
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
