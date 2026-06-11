"""Хелперы над таблицей events: проверка наличия и запись события.

Остальной код пишет события инлайном через ``session.add(Event(...))``;
здесь — то, что переиспользуется (идемпотентность лид-магнита) и читается
понятнее именованной функцией.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Event


async def event_exists(
    session: AsyncSession,
    telegram_id: int,
    event_type: str,
    *,
    meta_kind: str | None = None,
) -> bool:
    """Есть ли событие ``event_type`` у юзера (опц. с ``meta->>'kind' = meta_kind``).

    Для JSONB ``Event.meta["kind"].astext`` → ``meta ->> 'kind'``; у строк с
    NULL-meta (напр. leadmagnet_sent из диагностики) это NULL и никогда не
    совпадёт с meta_kind — две ветки лид-магнита не пересекаются.
    """
    stmt = select(Event.id).where(
        Event.telegram_id == telegram_id,
        Event.event_type == event_type,
    )
    if meta_kind is not None:
        stmt = stmt.where(Event.meta["kind"].astext == meta_kind)
    return await session.scalar(stmt.limit(1)) is not None


async def log_event(
    session: AsyncSession,
    telegram_id: int,
    event_type: str,
    *,
    meta: dict[str, Any] | None = None,
) -> None:
    """Записать событие (коммит — на стороне вызывающего get_session-блока)."""
    session.add(Event(telegram_id=telegram_id, event_type=event_type, meta=meta))
