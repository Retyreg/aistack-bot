"""Ручной запуск броадкаста (для теста до плановой даты).

Использование (бот polling может работать параллельно — Telegram не запрещает
второй send_message клиент при одном polling):

    python -m tools.force_broadcast earlybird_closing
    python -m tools.force_broadcast post_earlybird
    python -m tools.force_broadcast last_call

Чтобы запустить повторно в течение 24h (дедуп per-lead per-kind):
    DELETE FROM events WHERE event_type='broadcast_sent';
"""

import asyncio
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import get_settings
from services.broadcasts import (
    push_earlybird_closing,
    push_last_call,
    push_post_earlybird,
)

KINDS = {
    "earlybird_closing": push_earlybird_closing,
    "post_earlybird": push_post_earlybird,
    "last_call": push_last_call,
}


async def _main(kind: str) -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await KINDS[kind](bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in KINDS:
        print(f"Usage: python -m tools.force_broadcast <{' | '.join(KINDS)}>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
