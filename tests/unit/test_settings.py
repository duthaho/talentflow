import pytest
from pydantic import ValidationError

from app.shared.settings import Settings


def test_production_rejects_development_header_auth() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=oidc_jwt"):
        Settings(app_env="production")


def test_oidc_mode_requires_provider_coordinates() -> None:
    with pytest.raises(ValidationError, match="OIDC issuer"):
        Settings(auth_mode="oidc_jwt")


def test_production_requires_non_sqlite_database_url() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL DATABASE_URL"):
        Settings(
            app_env="production",
            auth_mode="oidc_jwt",
            database_url="sqlite:///talentflow.db",
            cors_allowed_origins="https://console.example.test",
            oidc_issuer="https://issuer.example.test",
            oidc_audience="talentflow-api",
            oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        )


def test_production_requires_explicit_cors_origins() -> None:
    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        Settings(
            app_env="production",
            auth_mode="oidc_jwt",
            database_url="postgresql+psycopg://user:pass@db/talentflow",
            oidc_issuer="https://issuer.example.test",
            oidc_audience="talentflow-api",
            oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        )


def test_production_requires_attachment_malware_scanning() -> None:
    with pytest.raises(ValidationError, match="ATTACHMENT_SCAN_MODE=clamav"):
        Settings(
            app_env="production",
            auth_mode="oidc_jwt",
            database_url="postgresql+psycopg://user:pass@db/talentflow",
            cors_allowed_origins="https://console.example.test",
            oidc_issuer="https://issuer.example.test",
            oidc_audience="talentflow-api",
            oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
            redis_url="redis://redis:6379/0",
            attachment_storage_root="/var/lib/talentflow/attachments",
        )


def test_production_requires_https_calendar_public_base_url() -> None:
    with pytest.raises(ValidationError, match="CALENDAR_PUBLIC_BASE_URL"):
        Settings(
            app_env="production",
            auth_mode="oidc_jwt",
            database_url="postgresql+psycopg://user:pass@db/talentflow",
            cors_allowed_origins="https://console.example.test",
            oidc_issuer="https://issuer.example.test",
            oidc_audience="talentflow-api",
            oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
            redis_url="redis://redis:6379/0",
            attachment_storage_root="/var/lib/talentflow/attachments",
            attachment_scan_mode="clamav",
        )


def test_settings_rejects_sendgrid_without_an_api_key() -> None:
    with pytest.raises(ValidationError, match="SENDGRID_API_KEY"):
        Settings(notification_email_adapter="sendgrid")


def test_settings_rejects_incomplete_smtp_configuration() -> None:
    with pytest.raises(ValidationError, match="NOTIFICATION_SMTP_HOST"):
        Settings(notification_smtp_host="")


@pytest.mark.parametrize("port", [0, 65536])
def test_settings_rejects_smtp_port_outside_tcp_range(port: int) -> None:
    with pytest.raises(ValidationError, match="NOTIFICATION_SMTP_PORT"):
        Settings(notification_smtp_port=port)


def test_settings_redacts_database_url_and_sendgrid_secret_in_repr() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:db-password@db/talentflow",
        notification_email_adapter="sendgrid",
        sendgrid_api_key="super-secret-value",
        notification_from_email="notifications@example.test",
    )

    assert "db-password" not in repr(settings)
    assert "super-secret-value" not in repr(settings)


def test_settings_rejects_invalid_worker_timing() -> None:
    with pytest.raises(ValidationError, match="worker polling intervals"):
        Settings(worker_poll_seconds=10, worker_max_backoff_seconds=1)

    with pytest.raises(ValidationError, match="RETENTION_SCHEDULE_SECONDS"):
        Settings(retention_schedule_seconds=0)


def test_s3_attachment_storage_requires_credentials_and_bounded_download_ttl() -> None:
    with pytest.raises(ValidationError, match="S3 attachment storage requires"):
        Settings(attachment_storage_backend="s3")
    with pytest.raises(ValidationError, match="ATTACHMENT_DOWNLOAD_TTL_SECONDS"):
        Settings(attachment_download_ttl_seconds=301)
