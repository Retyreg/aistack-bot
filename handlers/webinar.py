"""Регистрация на вебинар: кнопка → имя → подтверждение + постановка цепочки.

Само расписание и рассылка — в services/webinar.py. Здесь только интейк.
"""

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.models import Event, Lead, WebinarRegistration
from db.session import get_session
from keyboards.inline import audit_offer_kb
from services import webinar as svc
from texts import webinar as texts

logger = logging.getLogger(__name__)
router = Router(name="webinar")


class WebinarFlow(StatesGroup):
    waiting_for_name = State()


async def _lead_source(telegram_id: int) -> str | None:
    async with get_session() as session:
        result = await session.execute(select(Lead.source).where(Lead.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def _start_registration(message: Message, telegram_id: int, state: FSMContext) -> None:
    """Общий вход: из кнопки и из /webinar."""
    if svc.is_over():
        await message.answer(texts.WEBINAR_PASSED)
        return

    async with get_session() as session:
        result = await session.execute(
            select(WebinarRegistration).where(
                WebinarRegistration.telegram_id == telegram_id,
                WebinarRegistration.webinar_key == svc.webinar_key(),
            )
        )
        existing = result.scalar_one_or_none()

    if existing is not None:
        await message.answer(svc.fmt(texts.WEBINAR_ALREADY_REGISTERED))
        return

    await state.set_state(WebinarFlow.waiting_for_name)
    await message.answer(svc.fmt(texts.WEBINAR_PITCH))


@router.callback_query(F.data == "webinar_reg")
async def cb_webinar_reg(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user is None or call.message is None:
        await call.answer()
        return
    await _start_registration(call.message, call.from_user.id, state)
    await call.answer()


@router.message(Command("webinar"))
async def cmd_webinar(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await _start_registration(message, message.from_user.id, state)


@router.message(WebinarFlow.waiting_for_name)
async def on_name(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None or not message.text:
        return

    name = message.text.strip()
    if len(name) < 2:
        await message.answer(texts.WEBINAR_NAME_TOO_SHORT)
        return
    name = name[:100]

    now = datetime.now(timezone.utc)
    # Регистрация за день до эфира не должна получить «за 3 дня» задним
    # числом — next_stage_after перешагивает всё, что уже в прошлом.
    stage, next_at = svc.next_stage_after(now)
    source = await _lead_source(user.id)

    async with get_session() as session:
        result = await session.execute(
            select(WebinarRegistration).where(
                WebinarRegistration.telegram_id == user.id,
                WebinarRegistration.webinar_key == svc.webinar_key(),
            )
        )
        reg = result.scalar_one_or_none()
        if reg is None:
            reg = WebinarRegistration(
                telegram_id=user.id,
                webinar_key=svc.webinar_key(),
                source=source,
            )
            session.add(reg)
        reg.username = user.username
        reg.name = name
        reg.next_reminder_stage = stage
        reg.next_reminder_at = next_at
        reg.is_active = True

        session.add(
            Event(
                telegram_id=user.id,
                event_type="webinar_registered",
                meta={"webinar": svc.webinar_key(), "source": source, "name": name},
            )
        )

    await state.clear()
    # Касание 0 цепочки — подтверждение, уходит сразу и в sweep не участвует.
    await message.answer(svc.fmt(texts.WEBINAR_CONFIRMED, name=name))
    logger.info(
        "Webinar registration: tg=%s stage=%s next_at=%s source=%s",
        user.id,
        stage,
        next_at,
        source,
    )

    # Мостик в аудит: у зарегистрировавшихся идея обычно уже есть.
    await message.answer(texts.WEBINAR_TO_AUDIT, reply_markup=audit_offer_kb())
