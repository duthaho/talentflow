from app.modules.notifications.application import run_email_worker
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


def test_email_worker_entrypoint_uses_default_smtp_adapter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Loop:
        def __init__(self, **kwargs: object) -> None:
            captured["loop"] = kwargs

        def run(self) -> None:
            captured["ran"] = True

        def stopping(self) -> bool:
            return False

    def sender(_sessions: object, adapter: object) -> object:
        captured["adapter"] = adapter
        return lambda _delivery: None

    monkeypatch.setattr(run_email_worker, "settings", Settings(database_url="sqlite://"))
    monkeypatch.setattr(run_email_worker, "WorkerLoop", Loop)
    monkeypatch.setattr(run_email_worker, "EmailDeliverySender", sender)

    run_email_worker.main()

    assert isinstance(captured["adapter"], SmtpEmailAdapter)
    assert captured["ran"] is True
