import logging

from sqlalchemy import text

from app.modules.notifications.application.delivery_worker import DeliveryWorker
from app.modules.notifications.application.email_delivery import EmailAdapter, EmailDeliverySender
from app.modules.notifications.application.outbox_publisher import OutboxPublisher
from app.modules.notifications.infrastructure.sendgrid_email import SendGridEmailAdapter
from app.modules.notifications.infrastructure.smtp_email import SmtpEmailAdapter
from app.shared.database import build_session_factory
from app.shared.observability import configure_logging, configure_telemetry
from app.shared.settings import Settings, settings
from app.shared.worker_runtime import WorkerLoop

logger = logging.getLogger(__name__)


def build_email_adapter(runtime_settings: Settings) -> EmailAdapter:
    if runtime_settings.notification_email_adapter == "sendgrid":
        return SendGridEmailAdapter(
            api_key=runtime_settings.sendgrid_api_key.get_secret_value()
            if runtime_settings.sendgrid_api_key
            else "",
            sender=runtime_settings.notification_from_email,
        )
    return SmtpEmailAdapter(
        host=runtime_settings.notification_smtp_host,
        port=runtime_settings.notification_smtp_port,
        sender=runtime_settings.notification_from_email,
    )


def main() -> None:
    configure_telemetry(settings)
    configure_logging()
    adapter = build_email_adapter(settings)
    sessions = build_session_factory(settings.database_url)
    publisher = OutboxPublisher(sessions)
    worker = DeliveryWorker(
        sessions,
        sender=EmailDeliverySender(sessions, adapter),
        max_attempts=settings.worker_max_attempts,
        lease_seconds=settings.worker_lease_seconds,
    )
    loop: WorkerLoop

    def cycle() -> int:
        published = publisher.publish_pending()
        delivered = worker.deliver_pending(should_stop=loop.stopping)
        backlog = publisher.pending_count() + worker.pending_count()
        logger.info(
            "notification_worker_completed",
            extra={
                "event": "notification_worker_completed",
                "published": published,
                "delivered": delivered,
            },
        )
        return backlog

    def ready() -> None:
        with sessions() as session:
            session.execute(text("SELECT 1"))

    try:
        loop = WorkerLoop(
            name="email",
            cycle=cycle,
            readiness_check=ready,
            shutdown=worker.release_leases,
            poll_seconds=settings.worker_poll_seconds,
            max_backoff_seconds=settings.worker_max_backoff_seconds,
            grace_seconds=settings.worker_shutdown_grace_seconds,
            probe_port=8002,
        )
        loop.run()
    finally:
        sessions.kw["bind"].dispose()


if __name__ == "__main__":
    main()
