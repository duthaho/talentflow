from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["development_headers", "oidc_jwt"] = "development_headers"
    database_url: str = Field(default="sqlite:///talentflow.db", repr=False)
    cors_allowed_origins: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_jwks_cache_ttl_seconds: int = 300
    notification_email_adapter: Literal["smtp", "sendgrid"] = "smtp"
    sendgrid_api_key: SecretStr | None = None
    notification_from_email: str = "notifications@talentflow.local"
    notification_smtp_host: str = "mailpit"
    notification_smtp_port: int = 1025
    webhook_secret_keys: SecretStr = SecretStr("dev:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
    webhook_secret_active_key_id: str = "dev"
    webhook_allow_http: bool = False
    webhook_private_network_allowlist: str = ""
    webhook_delivery_retention_days: int = Field(default=30, ge=1)
    rabbitmq_url: SecretStr = SecretStr("amqp://talentflow:talentflow@rabbitmq:5672/%2Ftalentflow")
    outbox_batch_size: int = Field(default=100, gt=0, le=1000)
    worker_lease_seconds: int = 60
    worker_max_attempts: int = 5
    worker_poll_seconds: float = 1.0
    worker_max_backoff_seconds: float = 30.0
    worker_shutdown_grace_seconds: float = 30.0
    idempotency_key_ttl_seconds: int = Field(default=86400, gt=0)
    redis_url: str = Field(default="", repr=False)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    rate_limit_trusted_proxy_cidrs: str = ""
    careers_apply_limit_per_hour: int = Field(default=5, gt=0)
    careers_apply_limit_per_email_per_day: int = Field(default=3, gt=0)
    attachment_storage_root: str = "./data/attachments"
    attachment_storage_backend: Literal["filesystem", "s3"] = "filesystem"
    attachment_s3_endpoint_url: str = ""
    attachment_s3_public_endpoint_url: str = ""
    attachment_s3_access_key_id: str = ""
    attachment_s3_secret_access_key: SecretStr | None = None
    attachment_s3_bucket: str = "talentflow-attachments"
    attachment_s3_region: str = "us-east-1"
    attachment_download_ttl_seconds: int = 300
    attachment_max_bytes: int = 5 * 1024 * 1024
    attachment_scan_mode: Literal["noop", "clamav"] = "noop"
    attachment_scan_command: str = "clamscan"
    attachment_clamav_host: str = ""
    attachment_clamav_port: int = 3310
    calendar_subscription_lifetime_days: int = 90
    calendar_interview_duration_minutes: int = 60
    calendar_public_base_url: str = ""
    retention_worker_batch_size: int = 100
    retention_schedule_seconds: float = 3600.0
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_insecure: bool | None = None
    otel_service_name: str = "talentflow-api"

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
            if (
                self.attachment_storage_backend == "filesystem"
                and not self.attachment_storage_root.startswith("/")
            ):
                raise ValueError("Production requires an absolute ATTACHMENT_STORAGE_ROOT")
            if not self.calendar_public_base_url.startswith("https://"):
                raise ValueError("Production requires an HTTPS CALENDAR_PUBLIC_BASE_URL")
        if self.rate_limit_requests_per_minute < 1:
            raise ValueError("RATE_LIMIT_REQUESTS_PER_MINUTE must be positive")
        if self.attachment_max_bytes < 1:
            raise ValueError("ATTACHMENT_MAX_BYTES must be positive")
        if not 1 <= self.attachment_clamav_port <= 65535:
            raise ValueError("ATTACHMENT_CLAMAV_PORT must be between 1 and 65535")
        if not 1 <= self.attachment_download_ttl_seconds <= 300:
            raise ValueError("ATTACHMENT_DOWNLOAD_TTL_SECONDS must be between 1 and 300")
        if self.attachment_storage_backend == "s3" and not all(
            (
                self.attachment_s3_endpoint_url,
                self.attachment_s3_public_endpoint_url,
                self.attachment_s3_access_key_id,
                self.attachment_s3_secret_access_key,
                self.attachment_s3_bucket,
            )
        ):
            raise ValueError("S3 attachment storage requires endpoint, credentials, and bucket")
        if self.calendar_subscription_lifetime_days < 1:
            raise ValueError("CALENDAR_SUBSCRIPTION_LIFETIME_DAYS must be positive")
        if self.calendar_interview_duration_minutes < 1:
            raise ValueError("CALENDAR_INTERVIEW_DURATION_MINUTES must be positive")
        if self.retention_worker_batch_size < 1:
            raise ValueError("RETENTION_WORKER_BATCH_SIZE must be positive")
        if (
            self.worker_poll_seconds <= 0
            or self.worker_max_backoff_seconds < self.worker_poll_seconds
        ):
            raise ValueError("worker polling intervals must be positive and ordered")
        if self.worker_shutdown_grace_seconds <= 0:
            raise ValueError("WORKER_SHUTDOWN_GRACE_SECONDS must be positive")
        if self.retention_schedule_seconds <= 0:
            raise ValueError("RETENTION_SCHEDULE_SECONDS must be positive")
        if self.auth_mode == "oidc_jwt" and not all(
            (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        ):
            raise ValueError("OIDC issuer, audience, and JWKS URL are required")
        if self.app_env == "production" and self.auth_mode == "oidc_jwt":
            if not self.oidc_issuer.startswith("https://") or not self.oidc_jwks_url.startswith(
                "https://"
            ):
                raise ValueError("Production OIDC issuer and JWKS URL must use HTTPS")
        if not self.notification_from_email:
            raise ValueError("NOTIFICATION_FROM_EMAIL is required")
        if self.notification_email_adapter == "sendgrid" and not self.sendgrid_api_key:
            raise ValueError(
                "SENDGRID_API_KEY is required when NOTIFICATION_EMAIL_ADAPTER=sendgrid"
            )
        if self.notification_email_adapter == "smtp":
            if not self.notification_smtp_host:
                raise ValueError(
                    "NOTIFICATION_SMTP_HOST is required when NOTIFICATION_EMAIL_ADAPTER=smtp"
                )
            if not 1 <= self.notification_smtp_port <= 65535:
                raise ValueError("NOTIFICATION_SMTP_PORT must be between 1 and 65535")
        from app.modules.webhooks.infrastructure.cipher import parse_keyring
        from app.modules.webhooks.infrastructure.egress import parse_allowlist

        parse_keyring(
            self.webhook_secret_keys.get_secret_value(),
            self.webhook_secret_active_key_id,
            production=self.app_env == "production",
        )
        parse_allowlist(self.webhook_private_network_allowlist)
        if self.app_env == "production" and (
            self.webhook_allow_http or self.webhook_private_network_allowlist
        ):
            raise ValueError("Production forbids private webhook egress and HTTP")
        return self


settings = Settings()
