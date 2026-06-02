"""Логика воронки: подсчёт сегмента, расписание дрипа.

Сегмент: большинство из 3 ответов; тай-брейк product > marketer > ops.
Дрип: расписание сжимается под EARLYBIRD_DEADLINE — см. compute_first_touch_at.
"""

from collections import Counter
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from config import get_settings

Segment = Literal["marketer", "ops", "product"]

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


def compute_first_touch_at(diagnostic_done_at: datetime) -> datetime:
    """Когда отправить касание 1 дрипа. Зависит от того, сколько дней до EB-дедлайна.

    Логика по SPEC §7.5 / §8.1:
    - ≥ 5 дней до дедлайна → полный дрип, касания раз в ~24ч.
    - 2–4 дня → ~12ч между касаниями.
    - < 2 дней → одно объединённое касание через ~6ч, потом оффер.
    - после дедлайна → оффер сразу (через 30 минут), пост-EB цена.

    Возвращает timezone-aware datetime в TZ из конфига.
    """
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    local_now = diagnostic_done_at.astimezone(tz) if diagnostic_done_at.tzinfo else diagnostic_done_at
    days_left = (settings.earlybird_deadline - local_now.date()).days

    if days_left < 0:
        return diagnostic_done_at + timedelta(minutes=30)
    if days_left < 2:
        return diagnostic_done_at + timedelta(hours=6)
    if days_left < 5:
        return diagnostic_done_at + timedelta(hours=12)
    return diagnostic_done_at + timedelta(hours=24)
