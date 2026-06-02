"""Уведомления автору в личку. Используется на шагах 4–5."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from config import get_settings

logger = logging.getLogger(__name__)


async def send_admin(bot: Bot, text: str) -> None:
    """Шлёт сообщение каждому ADMIN_ID. Глотает блокировки/ошибки."""
    settings = get_settings()
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except TelegramForbiddenError:
            logger.warning("Admin %s blocked the bot", admin_id)
        except Exception as exc:
            logger.exception("Failed to notify admin %s: %s", admin_id, exc)
