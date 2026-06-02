"""Бронь и сбор вопроса.

После клика тарифа (offer.py):
- self/supported → FSM waiting_for_contact, на ответ парсим имя+телефон,
  funnel_stage='booked', booked_at=now(), уведомление автору, deep-link.
- ask  → FSM waiting_for_question, на ответ — пересылка автору + ack.
"""

import html
import logging
import re
from datetime import datetime, timezone

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from config import get_settings
from db.models import Event, Lead
from db.session import get_session
from services.notify import send_admin
from texts import messages

logger = logging.getLogger(__name__)
router = Router(name="booking")


class BookingFlow(StatesGroup):
    waiting_for_contact = State()


class QuestionFlow(StatesGroup):
    waiting_for_question = State()


# Простой захват номера: 7+ значащих цифр с допустимыми разделителями.
PHONE_RE = re.compile(r"\+?\d(?:[\s\-\(\)\d]{6,})\d")


def parse_contact(text: str) -> tuple[str | None, str | None]:
    """Возвращает (имя, телефон). Если телефон не нашли — текст уходит в имя."""
    text = text.strip()
    m = PHONE_RE.search(text)
    if m:
        phone = m.group(0).strip()
        name = (text[: m.start()] + text[m.end() :]).strip(" ,;\n\t-")
        return (name or None, phone)
    return (text or None, None)


def _safe(value: str | None) -> str:
    return html.escape(value) if value else "—"


@router.message(BookingFlow.waiting_for_contact)
async def on_contact(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None or message.text is None:
        return

    name, phone = parse_contact(message.text)
    settings = get_settings()
    tariff_code: str | None = None
    source: str | None = None

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.telegram_id == user.id))
        lead = result.scalar_one_or_none()
        if lead is None:
            await message.answer(messages.BOOKING_NO_LEAD)
            await state.clear()
            return

        lead.contact_name = name
        lead.contact_phone = phone
        lead.funnel_stage = "booked"
        lead.booked_at = datetime.now(timezone.utc)
        tariff_code = lead.tariff
        source = lead.source

        session.add(
            Event(
                telegram_id=user.id,
                event_type="contact_captured",
                meta={"raw": message.text[:500], "name": name, "phone": phone},
            )
        )
        session.add(
            Event(telegram_id=user.id, event_type="booked", meta={"tariff": tariff_code})
        )

    landing_url = {
        "self": settings.landing_self,
        "supported": settings.landing_supported,
        "personal": settings.landing_personal,
    }.get(tariff_code or "", settings.landing_url)

    await message.answer(messages.BOOKING_CONFIRMED.format(landing_url=landing_url))

    admin_text = messages.ADMIN_NEW_BOOKING.format(
        tariff=messages.TARIFF_NAMES.get(tariff_code or "", tariff_code or "?"),
        name=_safe(name),
        phone=_safe(phone),
        username=f"@{html.escape(user.username)}" if user.username else "(нет username)",
        first_name=_safe(user.first_name),
        source=_safe(source),
    )
    if message.bot is not None:
        await send_admin(message.bot, admin_text)

    await state.clear()


@router.message(QuestionFlow.waiting_for_question)
async def on_question(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None or message.text is None:
        return

    async with get_session() as session:
        session.add(
            Event(
                telegram_id=user.id,
                event_type="question_asked",
                meta={"text": message.text[:1000]},
            )
        )

    admin_text = messages.ADMIN_QUESTION.format(
        username=f"@{html.escape(user.username)}" if user.username else "(нет username)",
        first_name=_safe(user.first_name),
        question=html.escape(message.text)[:3500],
    )
    if message.bot is not None:
        await send_admin(message.bot, admin_text)

    await message.answer(messages.QUESTION_RECEIVED)
    await state.clear()
