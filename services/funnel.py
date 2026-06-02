"""Логика воронки: подсчёт сегмента, расписание дрипа.

На шаге 1 — только тип сегмента. Остальное наполняется на шагах 2–3.
"""

from collections import Counter
from typing import Literal

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
