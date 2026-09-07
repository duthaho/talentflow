import pytest
from pydantic import ValidationError

from app.shared.settings import Settings


def test_production_rejects_development_header_auth() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=oidc_jwt"):
        Settings(app_env="production")


def test_oidc_mode_requires_provider_coordinates() -> None:
    with pytest.raises(ValidationError, match="OIDC issuer"):
        Settings(auth_mode="oidc_jwt")
