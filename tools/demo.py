"""Демо-режим — управление лидом для записи видео.

Использование (на сервере, после ssh):

    cd ~/apps/aistack-bot && .venv/bin/python -m tools.demo reset <telegram_id>
    cd ~/apps/aistack-bot && .venv/bin/python -m tools.demo nudge <telegram_id>
    cd ~/apps/aistack-bot && .venv/bin/python -m tools.demo wipe <telegram_id>

reset — funnel_stage='warming', tariff/контакт/booked_at очищены, next_touch=1,
        next_action_at = now() - 1min (драп подберёт на следующем sweep).
nudge — only next_action_at = now() - 1min, ничего не сбрасывает (для перехода
        к следующему касанию воронки).
wipe  — удалить лида и его события полностью (для чистого старта /start).
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from db.models import Event, Lead
from db.session import SessionLocal


async def _reset(telegram_id: int) -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(Lead).where(Lead.telegram_id == telegram_id))
        lead = result.scalar_one_or_none()
        if lead is None:
            print(f"lead {telegram_id} not found")
            return
        lead.funnel_stage = "warming"
        lead.next_touch = 1
        lead.next_action_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        lead.last_touch_at = None
        lead.tariff = None
        lead.contact_name = None
        lead.contact_phone = None
        lead.booked_at = None
        lead.paid_at = None
        lead.is_subscribed = True
        await session.commit()
    print(f"lead {telegram_id} reset to warming, next_touch=1, next_action_at in past")


async def _nudge(telegram_id: int) -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(Lead).where(Lead.telegram_id == telegram_id))
        lead = result.scalar_one_or_none()
        if lead is None:
            print(f"lead {telegram_id} not found")
            return
        if lead.funnel_stage != "warming":
            print(f"lead is at funnel_stage={lead.funnel_stage}, sweep won't touch it; use reset")
            return
        lead.next_action_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()
    print(f"lead {telegram_id} nudged: next_touch={lead.next_touch}, action_at in past")


async def _wipe(telegram_id: int) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Event).where(Event.telegram_id == telegram_id))
        await session.execute(delete(Lead).where(Lead.telegram_id == telegram_id))
        await session.commit()
    print(f"lead {telegram_id} and events wiped — /start создаст с нуля")


COMMANDS = {"reset": _reset, "nudge": _nudge, "wipe": _wipe}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python -m tools.demo <{' | '.join(COMMANDS)}> <telegram_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(COMMANDS[sys.argv[1]](int(sys.argv[2])))
