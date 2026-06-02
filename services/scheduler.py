"""APScheduler: drip_sweep раз в DRIP_INTERVAL_MINUTES.

drip_sweep: подбирает warming-лидов с next_action_at <= now() и шлёт очередное
касание прогрева. Касание 4 = оффер → funnel_stage='offered'.

Идемпотентность: повтор сообщения возможен только если сбой DB-коммита после
успешного send_message; этого избегаем коммитом сразу после send в одной
транзакции на лида.

Броадкасты по абсолютным датам (09.06, 11.06, 23.06) — на шаге 5.
"""

import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from config import get_settings
from db.models import Event, Lead
from db.session import SessionLocal
from services.broadcasts import register_broadcasts
from services.funnel import DripMode, drip_mode, next_interval, render_offer
from texts import messages

logger = logging.getLogger(__name__)

_settings = get_settings()


async def drip_sweep(bot: Bot) -> None:
    """Один проход sweep'а: отрабатываем все просроченные next_action_at."""
    now = datetime.now(timezone.utc)

    # после старта курса прогрев не шлём (edge case §12)
    settings = get_settings()
    from zoneinfo import ZoneInfo

    local_today = now.astimezone(ZoneInfo(settings.timezone)).date()
    if local_today >= settings.course_start:
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(Lead).where(
                Lead.funnel_stage == "warming",
                Lead.is_subscribed.is_(True),
                Lead.next_action_at.is_not(None),
                Lead.next_action_at <= now,
            )
        )
        leads = result.scalars().all()

        for lead in leads:
            try:
                await _send_touch(bot, session, lead, now)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("drip_sweep failed for lead %s", lead.telegram_id)


async def _send_touch(bot: Bot, session, lead: Lead, now: datetime) -> None:
    """Шлёт текущее касание и сдвигает next_touch/next_action_at."""
    mode = drip_mode(now)
    n = lead.next_touch

    # после EB-дедлайна — сразу к офферу, прогрев не шлём
    if mode == "post" and n < 4:
        n = 4

    try:
        if n == 1:
            if mode == "ultra":
                # склеенное касание 1+2+3 → потом сразу оффер
                await bot.send_message(lead.telegram_id, messages.WARMING_COMBINED)
                lead.next_touch = 4
            else:
                await bot.send_message(lead.telegram_id, messages.WARMING_1)
                lead.next_touch = 2
        elif n == 2:
            await bot.send_message(lead.telegram_id, messages.WARMING_2)
            lead.next_touch = 3
        elif n == 3:
            await bot.send_message(lead.telegram_id, messages.WARMING_3)
            lead.next_touch = 4
        elif n == 4:
            text, kb = render_offer(now)
            await bot.send_message(lead.telegram_id, text, reply_markup=kb)
            lead.funnel_stage = "offered"
            lead.next_action_at = None
            session.add(Event(telegram_id=lead.telegram_id, event_type="offer_shown"))
            session.add(
                Event(
                    telegram_id=lead.telegram_id,
                    event_type="touch_sent",
                    meta={"n": 4, "mode": mode},
                )
            )
            lead.last_touch_at = now
            return
        else:
            logger.warning("Unexpected next_touch=%s for lead %s", n, lead.telegram_id)
            return

        session.add(
            Event(
                telegram_id=lead.telegram_id,
                event_type="touch_sent",
                meta={"n": n, "mode": mode},
            )
        )
        lead.last_touch_at = now
        lead.next_action_at = now + next_interval(mode)

    except TelegramForbiddenError:
        lead.is_subscribed = False
        session.add(
            Event(
                telegram_id=lead.telegram_id,
                event_type="unsubscribed",
                meta={"reason": "blocked"},
            )
        )


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Запустить APScheduler с заданным интервалом drip_sweep."""
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        drip_sweep,
        "interval",
        minutes=settings.drip_interval_minutes,
        kwargs={"bot": bot},
        id="drip_sweep",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    register_broadcasts(scheduler, bot)
    scheduler.start()
    logger.info("Scheduler started: drip_sweep every %s min", settings.drip_interval_minutes)
    return scheduler
