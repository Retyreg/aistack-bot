from datetime import date
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    database_url: str
    # NoDecode: запретить pydantic-settings парсить как JSON.
    # Сырая строка вида "11,22" → list[int] через _parse_admin_ids ниже.
    admin_ids: Annotated[list[int], NoDecode] = []
    timezone: str = "Asia/Almaty"
    earlybird_deadline: date
    course_start: date
    drip_interval_minutes: int = 15
    # HTTP-эндпоинт для приёма заявок с лендинга. webhook_secret обязателен,
    # без него /api/lead отдаст 401.
    webhook_secret: str = ""
    webhook_port: int = 8081
    landing_url: str = "https://aistackca.com"
    landing_self: str = "https://aistackca.com/#lead-self"
    landing_supported: str = "https://aistackca.com/#lead-supported"
    landing_personal: str = "https://aistackca.com/#lead-personal"
    author_contact: str = "@vatyutov"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> list[int]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
