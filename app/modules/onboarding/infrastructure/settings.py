"""Worker-only provisioning credentials; never required by the API process."""

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.onboarding.domain.policy import STEPS

DEV_DIRECTORY_SECRET = "dev-onboarding-client-secret"
DEV_HRIS_TOKEN = "dev-hris-stub-token"


class OnboardingSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    app_env: str = "development"
    keycloak_admin_url: str = "http://keycloak:8080"
    keycloak_onboarding_realm: str = "employees"
    keycloak_onboarding_client_id: str = "talentflow-onboarding"
    keycloak_onboarding_client_secret: SecretStr = SecretStr(DEV_DIRECTORY_SECRET)
    hris_stub_url: str = "http://hris-stub:8090"
    hris_stub_token: SecretStr = SecretStr(DEV_HRIS_TOKEN)
    onboarding_fault_injection: str = ""

    @property
    def faults(self):
        return frozenset(x.strip() for x in self.onboarding_fault_injection.split(",") if x.strip())

    @model_validator(mode="after")
    def valid(self):
        if self.faults and (
            self.app_env not in {"development", "test"} or self.faults - set(STEPS)
        ):
            raise ValueError("Invalid onboarding fault injection")
        if self.app_env == "production":
            if self.keycloak_onboarding_client_secret.get_secret_value() in {
                "",
                DEV_DIRECTORY_SECRET,
            } or self.hris_stub_token.get_secret_value() in {"", DEV_HRIS_TOKEN}:
                raise ValueError("Production provisioning requires private credentials")
            if not all(
                url.startswith("https://") for url in (self.keycloak_admin_url, self.hris_stub_url)
            ):
                raise ValueError("Production provisioning requires HTTPS")
        return self
