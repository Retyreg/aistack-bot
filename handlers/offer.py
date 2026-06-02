"""Хендлеры кликов по кнопкам оффера.

- self / supported  → лог tariff_clicked, lead.tariff = code,
                      FSM → BookingFlow.waiting_for_contact, запрос контакта.
- personal          → лог tariff_clicked, приглашение на 10-мин созвон,
                      уведомление автора о горячем лиде ($900).
- ask               → лог tariff_clicked(meta=ask), FSM → QuestionFlow,
                      ждём текст вопроса; пересылка → шаг booking.on_question.
"""

import html
import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import select

from config import get_settings
from db.models import Event, Lead
from db.session import get_session
from handlers.booking import BookingFlow, QuestionFlow
from keyboards.inline import TariffChoice
from services.notify import send_admin
from texts import messages

logger = logging.getLogger(__name__)
router = Router(name="offer")


def _safe(value: str | None) -> str:
    return html.escape(value) if value else "—"


@router.callback_query(TariffChoice.filter())
async def on_tariff(
    call: CallbackQuery, callback_data: TariffChoice, state: FSMContext
) -> None:
    user = call.from_user
    if user is None or call.message is None:
        await call.answer()
        return

    code = callback_data.code
    settings = get_settings()
    source: str | None = None

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.telegram_id == user.id))
        lead = result.scalar_one_or_none()

        if lead is not None:
            # уже забронил/оплатил → не пересоздаём поток, мягко возвращаем
            if lead.funnel_stage in ("booked", "paid"):
                await call.message.answer(messages.ALREADY_BOOKED)
                await call.answer()
                return
            source = lead.source
            if code in ("self", "supported", "personal"):
                lead.tariff = code

        session.add(
            Event(
                telegram_id=user.id,
                event_type="tariff_clicked",
                meta={"tariff": code},
            )
        )

    if code in ("self", "supported"):
        await state.set_state(BookingFlow.waiting_for_contact)
        await call.message.answer(messages.CONTACT_REQUEST)

    elif code == "personal":
        await call.message.answer(
            messages.PERSONAL_CALL_INVITE.format(author_contact=settings.author_contact)
        )
        admin_text = messages.ADMIN_PERSONAL_HOT_LEAD.format(
            username=f"@{html.escape(user.username)}" if user.username else "(нет username)",
            first_name=_safe(user.first_name),
            source=_safe(source),
        )
        if call.bot is not None:
            await send_admin(call.bot, admin_text)

    elif code == "ask":
        await state.set_state(QuestionFlow.waiting_for_question)
        await call.message.answer(messages.QUESTION_PROMPT)

    await call.answer()
