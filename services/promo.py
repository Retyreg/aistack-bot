from datetime import datetime, timezone

from config import MSK

PROMO_START = datetime(2026, 11, 16, tzinfo=MSK)
PROMO_END = datetime(2026, 11, 23, tzinfo=MSK)
CHANNEL = "@aistackca"
CHANNEL_URL = "https://t.me/aistackca"
COURSE_URL = "https://stepik.org/a/299181"


def is_active(now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Promo time must have a timezone")
    return PROMO_START <= now < PROMO_END
