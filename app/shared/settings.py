from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["development_headers", "oidc_jwt"] = "development_headers"
    database_url: str = Field(default="sqlite:///talentflow.db", repr=False)
    cors_allowed_origins: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_jwks_cache_ttl_seconds: int = 300
    sendgrid_api_key: SecretStr | None = None
    notification_from_email: str = ""
    worker_lease_seconds: int = 60
    worker_max_attempts: int = 5
    redis_url: str = Field(default="", repr=False)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    rate_limit_trusted_proxy_cidrs: str = ""
    attachment_storage_root: str = "./data/attachments"
    attachment_max_bytes: int = 5 * 1024 * 1024
    attachment_scan_mode: Literal["noop", "clamav"] = "noop"
    attachment_scan_command: str = "clamscan"
    calendar_subscription_lifetime_days: int = 90
    calendar_interview_duration_minutes: int = 60
    calendar_public_base_url: str = ""

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(
            origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()
        )

    def trusted_proxy_cidrs(self) -> tuple[str, ...]:
        return tuple(
            cidr.strip() for cidr in self.rate_limit_trusted_proxy_cidrs.split(",") if cidr.strip()
        )

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        if self.app_env == "production":
            if self.auth_mode != "oidc_jwt":
                raise ValueError("Production requires AUTH_MODE=oidc_jwt")
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("Production requires a PostgreSQL DATABASE_URL")
            if not self.cors_origins or "*" in self.cors_origins:
                raise ValueError("Production requires explicit CORS_ALLOWED_ORIGINS")
            if not all(origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production CORS_ALLOWED_ORIGINS must use HTTPS")
            if not self.redis_url.startswith(("redis://", "rediss://")):
                raise ValueError("Production requires a Redis REDIS_URL for rate limiting")
            if self.attachment_scan_mode != "clamav":
                raise ValueError("Production requires ATTACHMENT_SCAN_MODE=clamav")
            if not self.attachment_storage_root.startswith("/"):
                raise ValueError("Production requires an absolute ATTACHMENT_STORAGE_ROOT")
            if not self.calendar_public_base_url.startswith("https://"):
                raise ValueError("Production requires an HTTPS CALENDAR_PUBLIC_BASE_URL")
        if self.rate_limit_requests_per_minute < 1:
            raise ValueError("RATE_LIMIT_REQUESTS_PER_MINUTE must be positive")
        if self.attachment_max_bytes < 1:
            raise ValueError("ATTACHMENT_MAX_BYTES must be positive")
        if self.calendar_subscription_lifetime_days < 1:
            raise ValueError("CALENDAR_SUBSCRIPTION_LIFETIME_DAYS must be positive")
        if self.calendar_interview_duration_minutes < 1:
            raise ValueError("CALENDAR_INTERVIEW_DURATION_MINUTES must be positive")
        if self.auth_mode == "oidc_jwt" and not all(
            (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        ):
            raise ValueError("OIDC issuer, audience, and JWKS URL are required")
        if self.app_env == "production" and self.auth_mode == "oidc_jwt":
            if not self.oidc_issuer.startswith("https://") or not self.oidc_jwks_url.startswith(
                "https://"
            ):
                raise ValueError("Production OIDC issuer and JWKS URL must use HTTPS")
        if bool(self.sendgrid_api_key) != bool(self.notification_from_email):
            raise ValueError(
                "SENDGRID_API_KEY and NOTIFICATION_FROM_EMAIL must be configured together"
            )
        return self


settings = Settings()
