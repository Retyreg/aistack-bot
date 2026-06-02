from datetime import date
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    database_url: str
    admin_ids: list[int] = []
    timezone: str = "Asia/Almaty"
    earlybird_deadline: date
    course_start: date
    landing_url: str = "https://aistackca.com"
    landing_self: str = "https://aistackca.com/#lead-self"
    landing_supported: str = "https://aistackca.com/#lead-supported"
    landing_personal: str = "https://aistackca.com/#lead-personal"
    author_contact: str = "@vatyutov"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> list[int]:
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
