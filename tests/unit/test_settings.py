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


def test_settings_rejects_partial_notification_secret_configuration() -> None:
    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(sendgrid_api_key="super-secret-value")


def test_settings_redacts_database_url_and_sendgrid_secret_in_repr() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:db-password@db/talentflow",
        sendgrid_api_key="super-secret-value",
        notification_from_email="notifications@example.test",
    )

    assert "db-password" not in repr(settings)
    assert "super-secret-value" not in repr(settings)
