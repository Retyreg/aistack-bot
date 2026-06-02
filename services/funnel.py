"""Логика воронки: сегмент, расписание дрипа, рендер оффера.

- calc_segment — большинство из 3 ответов, тай-брейк product > marketer > ops.
- drip_mode — full/compressed/ultra/post по дельте до EB-дедлайна.
- compute_first_touch_at / next_interval — расписание дрипа.
- is_early_bird_active / render_offer — рендер оффера с динамической ценой.
"""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardMarkup

from config import get_settings
from texts import messages

Segment = Literal["marketer", "ops", "product"]
DripMode = Literal["full", "compressed", "ultra", "post"]

_TIEBREAKER: tuple[Segment, ...] = ("product", "marketer", "ops")


def calc_segment(answers: list[Segment]) -> Segment:
    """Большинство; тай-брейк product > marketer > ops."""
    counts = Counter(answers)
    max_count = max(counts.values())
    winners = {k for k, v in counts.items() if v == max_count}
    for segment in _TIEBREAKER:
        if segment in winners:
            return segment
    raise ValueError(f"Unexpected segment state: {counts!r}")


def _local_date(now: datetime) -> date:
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return aware.astimezone(tz).date()


def days_to_deadline(now: datetime) -> int:
    """Дней до EB-дедлайна (по локальной дате аудитории)."""
    settings = get_settings()
    return (settings.earlybird_deadline - _local_date(now)).days


def drip_mode(now: datetime) -> DripMode:
    """Режим дрипа в зависимости от дельты до EB-дедлайна."""
    d = days_to_deadline(now)
    if d < 0:
        return "post"
    if d < 2:
        return "ultra"
    if d < 5:
        return "compressed"
    return "full"


def next_interval(mode: DripMode) -> timedelta:
    """Интервал между касаниями дрипа."""
    return {
        "full": timedelta(hours=24),
        "compressed": timedelta(hours=12),
        "ultra": timedelta(hours=6),
        "post": timedelta(minutes=30),
    }[mode]


def compute_first_touch_at(diagnostic_done_at: datetime) -> datetime:
    """Когда послать касание 1 дрипа — first touch берёт next_interval(mode)."""
    return diagnostic_done_at + next_interval(drip_mode(diagnostic_done_at))


def is_early_bird_active(now: datetime | None = None) -> bool:
    """EB ещё открыт?"""
    return days_to_deadline(now or datetime.now(timezone.utc)) >= 0


def render_offer(now: datetime | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """Текст оффера + клавиатура тарифов. Цена self переключается по EB."""
    from keyboards.inline import offer_kb  # локальный импорт от циклов

    eb = is_early_bird_active(now)
    self_price = "$200" if eb else "$300"
    eb_warning = messages.OFFER_EB_WARNING if eb else ""
    text = messages.OFFER_TEMPLATE.format(self_price=self_price, eb_warning=eb_warning)
    return text, offer_kb(early_bird_active=eb)
