import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from sqlalchemy import select

from config import get_settings
from db.models import Event, Lead
from db.session import SessionLocal
from handlers import admin, booking, common, diagnostic, offer, start
from services.scheduler import start_scheduler


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    setup_logging()
    settings = get_settings()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # admin.router перед остальными — admin-команды не должны попасть в FSM-фильтры
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(diagnostic.router)
    dp.include_router(offer.router)
    dp.include_router(booking.router)
    # common.router включает fallback на любое сообщение — регистрируем последним
    dp.include_router(common.router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        """Глобальный хендлер ошибок. TelegramForbiddenError (юзер заблокировал
        бота во время отправки) → пометить лид unsubscribed; остальные —
        залогировать и пропустить, чтобы polling не падал.
        """
        exc = event.exception
        if isinstance(exc, TelegramForbiddenError):
            upd = event.update
            user = None
            if upd.message is not None:
                user = upd.message.from_user
            elif upd.callback_query is not None:
                user = upd.callback_query.from_user
            if user is not None:
                async with SessionLocal() as session:
                    res = await session.execute(
                        select(Lead).where(Lead.telegram_id == user.id)
                    )
                    lead = res.scalar_one_or_none()
                    if lead is not None and lead.is_subscribed:
                        lead.is_subscribed = False
                        session.add(
                            Event(
                                telegram_id=user.id,
                                event_type="unsubscribed",
                                meta={"reason": "blocked_during_handler"},
                            )
                        )
                        await session.commit()
            return True
        logging.getLogger(__name__).exception("Unhandled error", exc_info=exc)
        return True

    logging.getLogger(__name__).info("Bot starting")
    await bot.delete_webhook(drop_pending_updates=True)
    scheduler = start_scheduler(bot)
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
