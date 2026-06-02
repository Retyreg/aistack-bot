import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

from db.models import Event, Lead
from db.session import get_session
from texts import messages

logger = logging.getLogger(__name__)
router = Router(name="common")


@router.message(Command("stop"))
async def cmd_stop(message: Message, state: FSMContext) -> None:
    """Отписка: is_subscribed=False, чистим FSM."""
    user = message.from_user
    if user is None:
        return

    await state.clear()

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.telegram_id == user.id))
        lead = result.scalar_one_or_none()
        if lead is not None:
            lead.is_subscribed = False
            session.add(Event(telegram_id=user.id, event_type="unsubscribed"))

    await message.answer(messages.STOP_OK)


@router.message()
async def fallback(message: Message) -> None:
    """Мягкий ответ на непонятный ввод вне FSM."""
    await message.answer(messages.FALLBACK)
