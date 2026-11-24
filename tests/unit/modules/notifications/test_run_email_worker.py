from app.modules.notifications.application.run_email_worker import build_email_adapter
from app.modules.notifications.infrastructure.sendgrid_email import SendGridEmailAdapter
from app.modules.notifications.infrastructure.smtp_email import SmtpEmailAdapter
from app.shared.settings import Settings


def test_build_email_adapter_uses_smtp_configuration_by_default() -> None:
    adapter = build_email_adapter(
        Settings(
            notification_smtp_host="smtp.example.test",
            notification_smtp_port=2525,
            notification_from_email="notifications@example.test",
        )
    )

    assert isinstance(adapter, SmtpEmailAdapter)
    assert adapter.host == "smtp.example.test"
    assert adapter.port == 2525
    assert adapter.sender == "notifications@example.test"


def test_build_email_adapter_uses_sendgrid_when_selected() -> None:
    adapter = build_email_adapter(
        Settings(
            notification_email_adapter="sendgrid",
            sendgrid_api_key="test-key",
            notification_from_email="notifications@example.test",
        )
    )

    assert isinstance(adapter, SendGridEmailAdapter)
    assert adapter.sender == "notifications@example.test"
