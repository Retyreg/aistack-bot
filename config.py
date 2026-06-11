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

    # Лид-магнит с вебинара 10.06: ссылка на Unlisted-запись эфира.
    replay_url: str = "https://youtu.be/lsA4xftUMCk"
    # Источники, на которых /start сразу отдаёт промт+реплей (см. is_webinar_source).
    # Дефолт-онли: НЕ задаём в .env — pydantic-settings попытается JSON-парсить
    # complex-type поле и упадёт на строке "a,b" (как admin_ids, но без NoDecode).
    webinar_leadmagnet_sources: set[str] = {"src_webinar", "src_ig", "src_tt", "src_shorts"}

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


def is_webinar_source(source: str | None) -> bool:
    """True, если с этого source отдаём промт+реплей сразу на входе.

    Матчим точные источники из WEBINAR_LEADMAGNET_SOURCES плюс любой source
    с префиксом ``src_yt`` (покрывает ``src_yt``, ``src_yt_webinar0610`` и т.п.).
    """
    if not source:
        return False
    if source.startswith("src_yt"):
        return True
    return source in get_settings().webinar_leadmagnet_sources
