import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.models import Event, Lead
from db.session import get_session
from handlers.audit import begin_with_idea
from keyboards.inline import audit_offer_kb
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


# Столько символов уже похоже на описание идеи, а не на «привет».
IDEA_LIKE_LEN = 40


@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    """Свободный текст вне FSM.

    Развёрнутое сообщение трактуем как идею и сразу заводим аудит — по ТЗ
    человек может «написать свою идею первым сообщением». Короткое — обычный
    мягкий фоллбек с предложением разобрать идею.
    """
    if message.from_user is not None and message.text and len(message.text.strip()) >= IDEA_LIKE_LEN:
        await begin_with_idea(message, message.from_user.id, state, message.text.strip())
        return

    await message.answer(messages.FALLBACK, reply_markup=audit_offer_kb())


@router.callback_query()
async def stale_callback(call: CallbackQuery) -> None:
    """Устаревший callback (после рестарта или из старого сообщения) —
    отвечаем тостом, чтобы не висел спиннер на клиенте."""
    await call.answer("Эта кнопка устарела. Жми /start.", show_alert=False)
