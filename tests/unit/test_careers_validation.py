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


def test_reserved_system_admin_rejected_before_any_repository_io():
    from unittest.mock import Mock

    from app.modules.organization.application.commands import (
        CreateTenantCommand,
        InvalidTenantAdminError,
        OrganizationService,
    )

    repository, unit_of_work = Mock(), Mock()
    with pytest.raises(InvalidTenantAdminError):
        OrganizationService(repository=repository, unit_of_work=unit_of_work).create_tenant(
            CreateTenantCommand("Demo", "demo", "system:careers")
        )
    assert repository.mock_calls == []
    assert unit_of_work.mock_calls == []
