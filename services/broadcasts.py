"""Броадкасты по абсолютным датам (SPEC §8.2):
- 2026-06-09 19:00 local — push_earlybird_closing (EB закрывается завтра)
- 2026-06-11 12:00 local — push_post_earlybird (ре-энгейдж после дедлайна)
- 2026-06-23 19:00 local — push_last_call (финальный заход до старта)

Идемпотентность: per-lead per-kind, 24-часовое окно. Повторное срабатывание
job'а (рестарт бота в окне misfire) не приводит к дублю — те, кому уже
доставлено сегодня, пропускаются.

Цена в оффере после дедлайна автоматически переключается на $300 — это
работает в services.funnel.render_offer через is_early_bird_active(now).
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from config import get_settings
from db.models import Event, Lead
from db.session import SessionLocal
from keyboards.inline import book_now_self_eb_kb, offer_kb
from texts import messages

logger = logging.getLogger(__name__)

# Лимит Telegram ~30/sec на бота; держим ~20/sec с запасом.
THROTTLE_DELAY = 0.05
DEDUP_WINDOW = timedelta(hours=24)


async def _broadcast(bot: Bot, kind: str, text: str, reply_markup) -> None:
    """Шлёт text+reply_markup всем eligible-лидам. Идемпотентно per-lead per-kind."""
    now = datetime.now(timezone.utc)
    threshold = now - DEDUP_WINDOW

    async with SessionLocal() as session:
        result = await session.execute(
            select(Lead).where(
                Lead.is_subscribed.is_(True),
                Lead.funnel_stage.notin_(["booked", "paid"]),
            )
        )
        leads = list(result.scalars().all())

    sent = skipped = blocked = errored = 0

    for lead in leads:
        # per-lead dedup
        async with SessionLocal() as session:
            already = await session.execute(
                select(Event.id)
                .where(
                    Event.telegram_id == lead.telegram_id,
                    Event.event_type == "broadcast_sent",
                    Event.meta["kind"].astext == kind,
                    Event.created_at >= threshold,
                )
                .limit(1)
            )
            if already.scalar_one_or_none() is not None:
                skipped += 1
                continue

        try:
            await bot.send_message(lead.telegram_id, text, reply_markup=reply_markup)
            sent += 1
            async with SessionLocal() as session:
                session.add(
                    Event(
                        telegram_id=lead.telegram_id,
                        event_type="broadcast_sent",
                        meta={"kind": kind},
                    )
                )
                await session.commit()
        except TelegramForbiddenError:
            blocked += 1
            async with SessionLocal() as session:
                res = await session.execute(
                    select(Lead).where(Lead.telegram_id == lead.telegram_id)
                )
                l = res.scalar_one()
                l.is_subscribed = False
                session.add(
                    Event(
                        telegram_id=lead.telegram_id,
                        event_type="unsubscribed",
                        meta={"reason": "blocked", "during": kind},
                    )
                )
                await session.commit()
        except Exception:
            errored += 1
            logger.exception("Broadcast %s failed for lead %s", kind, lead.telegram_id)

        await asyncio.sleep(THROTTLE_DELAY)

    logger.info(
        "Broadcast %s done: sent=%d skipped=%d blocked=%d errored=%d",
        kind,
        sent,
        skipped,
        blocked,
        errored,
    )


async def push_earlybird_closing(bot: Bot) -> None:
    await _broadcast(
        bot,
        "earlybird_closing",
        messages.PUSH_EARLYBIRD_CLOSING,
        book_now_self_eb_kb(),
    )


async def push_post_earlybird(bot: Bot) -> None:
    await _broadcast(
        bot,
        "post_earlybird",
        messages.PUSH_POST_EARLYBIRD,
        offer_kb(early_bird_active=False),
    )


async def push_last_call(bot: Bot) -> None:
    await _broadcast(
        bot,
        "last_call",
        messages.PUSH_LAST_CALL,
        offer_kb(early_bird_active=False),
    )


def register_broadcasts(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Считает даты из EARLYBIRD_DEADLINE/COURSE_START и регистрирует DateTrigger'ы.

    Если дата уже в прошлом — пропускаем регистрацию (misfire_grace_time=3600
    защищает от потери при рестарте, но крайне-старые даты не воскрешаем).
    """
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    now_local = datetime.now(tz)

    schedule = [
        (
            datetime.combine(settings.earlybird_deadline - timedelta(days=1), time(19, 0), tzinfo=tz),
            push_earlybird_closing,
            "push_earlybird_closing",
        ),
        (
            datetime.combine(settings.earlybird_deadline + timedelta(days=1), time(12, 0), tzinfo=tz),
            push_post_earlybird,
            "push_post_earlybird",
        ),
        (
            datetime.combine(settings.course_start - timedelta(days=2), time(19, 0), tzinfo=tz),
            push_last_call,
            "push_last_call",
        ),
    ]

    for run_at, func, jid in schedule:
        if run_at <= now_local - timedelta(hours=1):
            logger.info("Skip broadcast %s — %s уже прошёл", jid, run_at)
            continue
        scheduler.add_job(
            func,
            DateTrigger(run_date=run_at),
            kwargs={"bot": bot},
            id=jid,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Broadcast %s scheduled at %s", jid, run_at)
