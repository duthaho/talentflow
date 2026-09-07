from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["development_headers", "oidc_jwt"] = "development_headers"
    database_url: str = "sqlite:///talentflow.db"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_jwks_cache_ttl_seconds: int = 300
    sendgrid_api_key: str = ""
    notification_from_email: str = ""

    @model_validator(mode="after")
    def validate_production_auth(self) -> "Settings":
        if self.app_env == "production" and self.auth_mode != "oidc_jwt":
            raise ValueError("Production requires AUTH_MODE=oidc_jwt")
        if self.auth_mode == "oidc_jwt" and not all(
            (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        ):
            raise ValueError("OIDC issuer, audience, and JWKS URL are required")
        return self


settings = Settings()
