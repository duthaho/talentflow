from app.modules.notifications.application.delivery_worker import DeliveryWorker
from app.modules.notifications.application.sendgrid_delivery import SendGridDeliverySender
from app.modules.notifications.infrastructure.sendgrid_email import SendGridEmailAdapter
from app.shared.database import build_session_factory
from app.shared.settings import settings


def main() -> None:
    adapter = SendGridEmailAdapter(
        api_key=settings.sendgrid_api_key, sender=settings.notification_from_email
    )
    sessions = build_session_factory(settings.database_url)
    worker = DeliveryWorker(
        sessions,
        sender=SendGridDeliverySender(sessions, adapter),
    )
    print(f"delivered={worker.deliver_pending()}")


if __name__ == "__main__":
    main()
