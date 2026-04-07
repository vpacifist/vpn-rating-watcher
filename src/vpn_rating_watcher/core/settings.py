from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")

    database_url: str = Field(alias="DATABASE_URL")

    source_url: str = Field(default="https://vpn.maximkatz.com/", alias="SOURCE_URL")
    source_timezone: str = Field(default="UTC", alias="SOURCE_TIMEZONE")

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegram_default_chat_ids: str | None = Field(
        default=None, alias="TELEGRAM_DEFAULT_CHAT_IDS"
    )
    web_app_url: str | None = Field(default=None, alias="WEB_APP_URL")

    scrape_times_utc: str = Field(default="00:00,06:00,12:00,18:00", alias="SCRAPE_TIMES_UTC")
    daily_post_time_utc: str = Field(default="19:00", alias="DAILY_POST_TIME_UTC")


@lru_cache
def get_settings() -> Settings:
    return Settings()
