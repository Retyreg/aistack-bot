from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Внутри тела Settings имя ``timezone`` занято полем настроек, поэтому
# tzinfo для МСК считаем здесь, снаружи класса.
MSK = timezone(timedelta(hours=3))


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

    # ─── Вебинар 27.08 + цепочка напоминаний ──────────────────────────────
    # ЕДИНСТВЕННЫЙ источник правды по времени: все четыре напоминания
    # считаются от него (services.webinar.stage_time). Обязательно с offset —
    # +03:00 это МСК; 18:00 МСК = 20:00 Алматы = 15:00 UTC.
    webinar_at: datetime = datetime(2026, 8, 27, 18, 0, tzinfo=MSK)
    webinar_title: str = "Запуск продукта с AI-командой"
    # Ссылка на комнату; пустая — кнопку «Подключиться» не рисуем.
    webinar_join_url: str = ""

    # ─── LLM для черновика вердикта (OpenRouter) ──────────────────────────
    # Один вызов на аудит, качество важнее цены → модель сильная, id в env.
    # Без ключа аудит не падает: админу уедут сырые ответы (см. services/llm.py).
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-5"
    openrouter_timeout_seconds: int = 90

    @field_validator("webinar_at")
    @classmethod
    def _webinar_at_aware(cls, v: datetime) -> datetime:
        """Наивный WEBINAR_AT ломает все сравнения в sweep'е — трактуем как МСК.

        Пиши в .env с offset: ``WEBINAR_AT=2026-08-27T18:00:00+03:00``.
        """
        if v.tzinfo is None:
            return v.replace(tzinfo=MSK)
        return v

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
