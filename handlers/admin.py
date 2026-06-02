"""Админ-команды (gated по ADMIN_IDS).

- /stats              — срез воронки + конверсии + разбивка source/segment.
- /paid <id|phone>    — пометить лида оплаченным, остановить пуши.
- /lead <id|phone>    — карточка лида.
- /broadcast <текст>  — ручная рассылка по подписанным; подтверждение
                        инлайн-кнопкой.
"""

import asyncio
import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandObject, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, or_, select

from config import get_settings
from db.models import Event, Lead
from db.session import SessionLocal
from services.analytics import format_stats, funnel_snapshot

logger = logging.getLogger(__name__)
router = Router(name="admin")


class AdminOnly(Filter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        return user.id in get_settings().admin_ids


router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())


class BroadcastFlow(StatesGroup):
    confirm = State()


def _safe(value) -> str:
    if value is None:
        return "—"
    return html.escape(str(value))


async def _lookup_lead(arg: str) -> Lead | None:
    arg = arg.strip()
    async with SessionLocal() as session:
        if arg.lstrip("-").isdigit():
            result = await session.execute(select(Lead).where(Lead.telegram_id == int(arg)))
            return result.scalar_one_or_none()
        result = await session.execute(
            select(Lead).where(
                or_(
                    Lead.contact_phone.ilike(f"%{arg}%"),
                    Lead.username.ilike(f"%{arg.lstrip('@')}%"),
                )
            )
        )
        return result.scalar_one_or_none()


# ─── /stats ────────────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    snap = await funnel_snapshot()
    await message.answer(format_stats(snap))


# ─── /lead ─────────────────────────────────────────────────────────────────

@router.message(Command("lead"))
async def cmd_lead(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /lead &lt;telegram_id | phone | @username&gt;")
        return

    lead = await _lookup_lead(command.args)
    if lead is None:
        await message.answer("Не нашёл лида.")
        return

    parts = [
        "👤 <b>Lead</b>",
        f"telegram_id: <code>{lead.telegram_id}</code>",
        f"username: @{_safe(lead.username)}" if lead.username else "username: —",
        f"first_name: {_safe(lead.first_name)}",
        f"source: {_safe(lead.source)}",
        "",
        f"segment: <b>{_safe(lead.segment)}</b>",
        f"funnel_stage: <b>{_safe(lead.funnel_stage)}</b>",
        f"tariff: {_safe(lead.tariff)}",
        f"is_subscribed: {lead.is_subscribed}",
        "",
        f"contact_name: {_safe(lead.contact_name)}",
        f"contact_phone: {_safe(lead.contact_phone)}",
        f"booked_at: {_safe(lead.booked_at)}",
        f"paid_at: {_safe(lead.paid_at)}",
        "",
        f"diagnostic_completed_at: {_safe(lead.diagnostic_completed_at)}",
        f"next_touch: {lead.next_touch}",
        f"next_action_at: {_safe(lead.next_action_at)}",
        f"last_touch_at: {_safe(lead.last_touch_at)}",
        f"created_at: {_safe(lead.created_at)}",
    ]
    await message.answer("\n".join(parts))


# ─── /paid ─────────────────────────────────────────────────────────────────

@router.message(Command("paid"))
async def cmd_paid(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /paid &lt;telegram_id | phone | @username&gt;")
        return

    async with SessionLocal() as session:
        arg = command.args.strip()
        if arg.lstrip("-").isdigit():
            result = await session.execute(select(Lead).where(Lead.telegram_id == int(arg)))
        else:
            result = await session.execute(
                select(Lead).where(
                    or_(
                        Lead.contact_phone.ilike(f"%{arg}%"),
                        Lead.username.ilike(f"%{arg.lstrip('@')}%"),
                    )
                )
            )
        lead = result.scalar_one_or_none()
        if lead is None:
            await message.answer("Не нашёл лида.")
            return

        lead.funnel_stage = "paid"
        lead.paid_at = datetime.now(timezone.utc)
        lead.next_action_at = None
        session.add(Event(telegram_id=lead.telegram_id, event_type="paid", meta={"by_admin": True}))

    await message.answer(
        f"✅ Лид <code>{lead.telegram_id}</code> ({_safe(lead.contact_name)}) "
        f"помечен <b>paid</b>. Пуши остановлены."
    )


# ─── /broadcast ────────────────────────────────────────────────────────────

def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="bcast_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="bcast_cancel"),
            ]
        ]
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, state: FSMContext) -> None:
    if not command.args:
        await message.answer(
            "Использование: <code>/broadcast &lt;текст&gt;</code>\n"
            "Поддерживается HTML (&lt;b&gt;, &lt;i&gt;, &lt;a&gt;)."
        )
        return

    text = command.args
    async with SessionLocal() as session:
        recipients = (
            await session.scalar(
                select(func.count(Lead.id)).where(Lead.is_subscribed.is_(True))
            )
        ) or 0

    await state.set_state(BroadcastFlow.confirm)
    await state.update_data(text=text)
    await message.answer(
        f"📣 <b>Подтвердить рассылку?</b>\n\n"
        f"Получателей: <b>{recipients}</b> (is_subscribed=true)\n\n"
        f"<b>Превью:</b>\n{text}",
        reply_markup=_confirm_kb(),
    )


@router.callback_query(BroadcastFlow.confirm, F.data == "bcast_confirm")
async def cb_broadcast_confirm(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.bot is None:
        await call.answer()
        return

    data = await state.get_data()
    text = data.get("text", "")
    await state.clear()

    await call.message.edit_text(call.message.html_text + "\n\n⏳ Отправляю…")

    sent = blocked = errored = 0
    async with SessionLocal() as session:
        result = await session.execute(select(Lead).where(Lead.is_subscribed.is_(True)))
        leads = list(result.scalars().all())

    for lead in leads:
        try:
            await call.bot.send_message(lead.telegram_id, text)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            async with SessionLocal() as session:
                res = await session.execute(
                    select(Lead).where(Lead.telegram_id == lead.telegram_id)
                )
                l = res.scalar_one()
                l.is_subscribed = False
                session.add(
                    Event(
                        telegram_id=lead.telegram_id,
                        event_type="unsubscribed",
                        meta={"reason": "blocked", "during": "manual_broadcast"},
                    )
                )
                await session.commit()
        except Exception:
            errored += 1
            logger.exception("Manual broadcast failed for lead %s", lead.telegram_id)
        await asyncio.sleep(0.05)

    await call.message.answer(
        f"✅ Готово.\nДоставлено: <b>{sent}</b>  ·  заблокировано: {blocked}  ·  ошибок: {errored}"
    )
    await call.answer()


@router.callback_query(BroadcastFlow.confirm, F.data == "bcast_cancel")
async def cb_broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if call.message is not None:
        await call.message.edit_text(call.message.html_text + "\n\n❌ Отменено.")
    await call.answer()
