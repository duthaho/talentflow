from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///talentflow.db"
    sendgrid_api_key: str = ""
    notification_from_email: str = ""


settings = Settings()
