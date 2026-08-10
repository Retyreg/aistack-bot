"""Вебинар: расписание напоминаний и sweep, который их шлёт.

Одна константа времени — ``settings.webinar_at``. Все четыре касания
считаются от неё (``stage_time``), в БД лежит UTC. Руками вбитых локальных
времён нет нигде: иначе «за час до начала» рано или поздно уезжает на час.

Почему отдельный job, а не ветка в drip_sweep: тот в самом начале делает
``if local_today >= settings.course_start: return`` — на проде COURSE_START
сейчас 2026-06-25, то есть drip_sweep выходит на каждом тике. Напоминания
внутри него никогда бы не выстрелили.

Переживает рестарт: позиция в цепочке — строка в webinar_registrations
(next_reminder_stage/next_reminder_at), а не таймер в памяти. Сдвиг стадии
коммитится сразу после успешной отправки, поэтому худший случай сбоя —
одно неотправленное напоминание, а не дубль всей цепочки.

Чтобы добавить/сдвинуть напоминание — правь STAGES ниже (и текст в
texts/webinar.py). Больше нигде ничего менять не нужно.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select

from config import get_settings
from db.models import Event, Lead, WebinarRegistration
from db.session import SessionLocal
from keyboards.inline import webinar_reminder_kb
from texts import webinar as texts

logger = logging.getLogger(__name__)

# (stage, за сколько до эфира, шаблон текста, есть ли кнопка «Подключиться»).
# Стадия 0 — подтверждение, оно уходит синхронно при регистрации и в sweep
# не участвует. Стадия STAGE_DONE означает «цепочка отработана».
STAGES: list[tuple[int, timedelta, str, bool]] = [
    (1, timedelta(days=3), texts.REMINDER_3D, False),
    (2, timedelta(days=1), texts.REMINDER_1D, False),
    (3, timedelta(hours=1), texts.REMINDER_1H, True),
]
STAGE_DONE = 99

_MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_WEEKDAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

MSK = timezone(timedelta(hours=3))


def webinar_at() -> datetime:
    """Момент эфира, tz-aware."""
    return get_settings().webinar_at


def webinar_key() -> str:
    """Ключ эфира для БД: дата по локальному времени курса (Алматы)."""
    tz = ZoneInfo(get_settings().timezone)
    return webinar_at().astimezone(tz).date().isoformat()


def stage_time(delta: timedelta) -> datetime:
    """Момент касания «за delta до эфира», в UTC."""
    return (webinar_at() - delta).astimezone(timezone.utc)


def human_date() -> str:
    """«27 августа» — короткая форма для CTA и меню. Тоже из WEBINAR_AT:
    дата эфира не должна быть вбита руками ни в одном тексте."""
    msk = webinar_at().astimezone(MSK)
    return f"{msk.day} {_MONTHS_RU[msk.month - 1]}"


def human_when() -> str:
    """«чт 27 августа, 18:00 МСК / 20:00 Алматы» — из одной константы."""
    settings = get_settings()
    at = webinar_at()
    msk = at.astimezone(MSK)
    local = at.astimezone(ZoneInfo(settings.timezone))
    city = settings.timezone.split("/")[-1].replace("_", " ")
    city_ru = {"Almaty": "Алматы", "Tashkent": "Ташкент", "Bishkek": "Бишкек"}.get(city, city)
    return (
        f"{_WEEKDAYS_RU[msk.weekday()]} {msk.day} {_MONTHS_RU[msk.month - 1]}, "
        f"{msk:%H:%M} МСК / {local:%H:%M} {city_ru}"
    )


def fmt(template: str, **extra: str) -> str:
    """Подставить {when}/{title} (и что передали сверху) в шаблон текста."""
    return template.format(when=human_when(), title=get_settings().webinar_title, **extra)


def is_over(now: datetime | None = None) -> bool:
    """Эфир уже начался? Тогда регистрацию не предлагаем."""
    now = now or datetime.now(timezone.utc)
    return now >= webinar_at().astimezone(timezone.utc)


def next_stage_after(now: datetime, *, after_stage: int = 0) -> tuple[int, datetime | None]:
    """Первая стадия, которая и позже ``after_stage``, и ещё впереди по времени.

    Два разных «дальше» намеренно разведены:
    - при регистрации (after_stage=0) — просто пропускаем всё, что уже прошло:
      человек, записавшийся 26.08, не должен получить «за 3 дня» задним числом;
    - после отправки касания N (after_stage=N) — двигаемся строго дальше по
      цепочке. Без этого условия отправленная досрочно стадия пересчиталась бы
      сама в себя и осталась бы на месте.
    """
    for stage, delta, _text, _join in STAGES:
        if stage <= after_stage:
            continue
        run_at = stage_time(delta)
        if run_at > now:
            return stage, run_at
    return STAGE_DONE, None


def _stage_spec(stage: int) -> tuple[timedelta, str, bool] | None:
    for s, delta, text, join in STAGES:
        if s == stage:
            return delta, text, join
    return None


# Насколько поздно напоминание ещё имеет смысл. Если бот лежал сутки, текст
# «через 3 дня» уже врёт — такое касание пропускаем, а не досылаем.
STALE_GRACE = timedelta(hours=6)


async def reminder_sweep(bot: Bot) -> None:
    """Один проход: разослать все просроченные напоминания.

    Не зависит от course_start — цепочка обязана отработать 27.08 независимо
    от того, в каком состоянии дожил основной прогрев.
    """
    now = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        # Отписавшийся через /stop (или заблокировавший бота) не должен
        # получать напоминания. Условие через NOT EXISTS, а не JOIN: у
        # регистрации может не быть строки в leads, и терять её нельзя —
        # молчим только когда лид есть и явно отписан.
        unsubscribed = (
            select(Lead.id)
            .where(
                Lead.telegram_id == WebinarRegistration.telegram_id,
                Lead.is_subscribed.is_(False),
            )
            .exists()
        )
        result = await session.execute(
            select(WebinarRegistration).where(
                WebinarRegistration.is_active.is_(True),
                WebinarRegistration.webinar_key == webinar_key(),
                WebinarRegistration.next_reminder_stage != STAGE_DONE,
                WebinarRegistration.next_reminder_at.is_not(None),
                WebinarRegistration.next_reminder_at <= now,
                ~unsubscribed,
            )
        )
        registrations = list(result.scalars().all())

    if not registrations:
        return

    sent = skipped = stale = blocked = errored = 0
    for reg in registrations:
        stage_now = reg.next_reminder_stage
        spec = _stage_spec(stage_now)
        if spec is None:
            logger.warning("Unknown reminder stage %s for registration %s", stage_now, reg.id)
            skipped += 1
            continue
        delta, template, with_join = spec

        # Протухшее касание не досылаем, но по цепочке двигаем — иначе
        # застрянем на нём и не отправим следующее, более важное.
        if now - stage_time(delta) > STALE_GRACE or is_over(now):
            stale += 1
            await _advance(reg.id, stage_now, now, sent_ok=False)
            continue

        try:
            await bot.send_message(
                reg.telegram_id,
                fmt(template, name=reg.name or ""),
                reply_markup=webinar_reminder_kb(with_join=with_join),
            )
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            async with SessionLocal() as session:
                fresh = await session.get(WebinarRegistration, reg.id)
                if fresh is not None:
                    fresh.is_active = False
                session.add(
                    Event(
                        telegram_id=reg.telegram_id,
                        event_type="unsubscribed",
                        meta={"reason": "blocked", "during": "webinar_reminder"},
                    )
                )
                await session.commit()
            continue
        except Exception:
            errored += 1
            logger.exception("Webinar reminder failed for %s", reg.telegram_id)
            # стадию не двигаем — попробуем на следующем тике
            continue

        # Коммитим сдвиг сразу после отправки: краш между send и commit
        # повторит одно напоминание, а не всю цепочку.
        await _advance(reg.id, stage_now, now, sent_ok=True)

    logger.info(
        "Webinar reminder sweep: sent=%d stale=%d skipped=%d blocked=%d errored=%d",
        sent,
        stale,
        skipped,
        blocked,
        errored,
    )


async def _advance(reg_id: int, stage_done: int, now: datetime, *, sent_ok: bool) -> None:
    """Сдвинуть регистрацию на следующее касание (и залогировать отправку)."""
    next_stage, next_at = next_stage_after(now, after_stage=stage_done)
    async with SessionLocal() as session:
        reg = await session.get(WebinarRegistration, reg_id)
        if reg is None:
            return
        reg.next_reminder_stage = next_stage
        reg.next_reminder_at = next_at
        if sent_ok:
            reg.last_reminder_at = now
            session.add(
                Event(
                    telegram_id=reg.telegram_id,
                    event_type="webinar_reminder_sent",
                    meta={"stage": stage_done, "webinar": webinar_key()},
                )
            )
        await session.commit()
