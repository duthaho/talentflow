from app.modules.notifications.infrastructure.sendgrid_email import SendGridEmailAdapter


def test_sendgrid_adapter_builds_authorized_mail_request() -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, body: dict[str, object], headers: dict[str, str]) -> None:
        captured.update(url=url, body=body, headers=headers)

    adapter = SendGridEmailAdapter(api_key="test-key", sender="noreply@example.com", post=fake_post)
    adapter.send(
        recipient="candidate@example.com", subject="Offer approved", text="Congratulations"
    )

    assert captured["url"] == "https://api.sendgrid.com/v3/mail/send"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["body"] == {
        "personalizations": [{"to": [{"email": "candidate@example.com"}]}],
        "from": {"email": "noreply@example.com"},
        "subject": "Offer approved",
        "content": [{"type": "text/plain", "value": "Congratulations"}],
    }
