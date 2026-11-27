import pytest

from app.modules.candidates.application.submit_application import valid_email


@pytest.mark.parametrize("email", ["a@example.test", "first.last+careers@example.test"])
def test_careers_email_accepts_valid_addresses(email):
    assert valid_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "x",
        "a..b@example.test",
        "a@example..test",
        "a@-example.test",
        "a@exam_ple.test",
        "a\x01@example.test",
        "a@localhost",
        "a b@example.test",
        "a" * 65 + "@example.test",
    ],
)
def test_careers_email_rejects_invalid_addresses(email):
    assert not valid_email(email)
