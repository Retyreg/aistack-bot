"""Одобрение вердикта аудита админом: отправить / отредактировать / позже.

Отдельный роутер, но с тем же AdminOnly-фильтром, что и handlers/admin.py, и
включается сразу после него — до FSM-хендлеров пользовательских флоу. Иначе
сообщение админа «вот текст вердикта» перехватил бы чужой FSM.

Источник правды — строка в audit_requests. FSM держит только audit_id на
время набора текста; если он потеряется (рестарт), кнопка «✏️» под тем же
сообщением просто нажимается заново.
"""

import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import get_settings
from db.models import AuditRequest, Event
from db.session import get_session
from handlers.admin import AdminOnly
from keyboards.inline import AuditAction, audit_verdict_kb
from services import webinar as webinar_svc
from texts import audit as texts

logger = logging.getLogger(__name__)
router = Router(name="audit_admin")
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())

OPEN_STATUSES = ("pending_approval", "failed")


class VerdictEdit(StatesGroup):
    waiting_for_text = State()


def _who(request: AuditRequest) -> str:
    handle = f"@{html.escape(request.username)}" if request.username else f"id{request.telegram_id}"
    name = html.escape(request.first_name) if request.first_name else "—"
    return f"{name} ({handle})"


async def _deliver(call_or_message, request_id: int, text: str) -> None:
    """Отправить вердикт пользователю и закрыть заявку.

    CTA на вебинар дописывается здесь, а не в промпте: модель не должна
    самовольно менять дату эфира или формулировку оффера.
    """
    bot = call_or_message.bot
    async with get_session() as session:
        request = await session.get(AuditRequest, request_id)
        if request is None:
            await call_or_message.answer(texts.ADMIN_NOT_FOUND.format(audit_id=request_id))
            return
        telegram_id = request.telegram_id
        who = _who(request)

    webinar_open = not webinar_svc.is_over()
    body = texts.AUDIT_VERDICT_HEADER + text
    if webinar_open:
        body += texts.AUDIT_VERDICT_CTA.format(
            webinar_date=webinar_svc.human_date(),
            webinar_title=get_settings().webinar_title,
        )

    try:
        await bot.send_message(
            telegram_id,
            body,
            reply_markup=audit_verdict_kb() if webinar_open else None,
        )
    except TelegramForbiddenError:
        async with get_session() as session:
            request = await session.get(AuditRequest, request_id)
            if request is not None:
                request.status = "manual"
            session.add(
                Event(
                    telegram_id=telegram_id,
                    event_type="unsubscribed",
                    meta={"reason": "blocked", "during": "audit_verdict"},
                )
            )
        await call_or_message.answer(texts.ADMIN_SENT_BLOCKED.format(audit_id=request_id))
        return

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        request = await session.get(AuditRequest, request_id)
        edited = True
        if request is not None:
            edited = text != (request.draft_text or "")
            request.final_text = text
            request.status = "sent"
            request.sent_at = now
        session.add(
            Event(
                telegram_id=telegram_id,
                event_type="audit_verdict_sent",
                meta={"audit_id": request_id, "edited": edited},
            )
        )

    await call_or_message.answer(texts.ADMIN_SENT_OK.format(audit_id=request_id, who=who))


@router.callback_query(AuditAction.filter(F.action == "send"))
async def cb_send(call: CallbackQuery, callback_data: AuditAction) -> None:
    if call.message is None or call.bot is None:
        await call.answer()
        return

    audit_id = callback_data.audit_id
    async with get_session() as session:
        request = await session.get(AuditRequest, audit_id)
        if request is None:
            await call.message.answer(texts.ADMIN_NOT_FOUND.format(audit_id=audit_id))
            await call.answer()
            return
        if request.status not in OPEN_STATUSES:
            await call.message.answer(texts.ADMIN_ALREADY_HANDLED.format(status=request.status))
            await call.answer()
            return
        draft = request.draft_text

    if not draft:
        # «Отправить как есть» без черновика отправлять нечего.
        await call.message.answer(texts.ADMIN_DRAFT_MISSING.format(audit_id=audit_id))
        await call.answer()
        return

    await _deliver(call.message, audit_id, draft)
    await call.answer()


@router.callback_query(AuditAction.filter(F.action == "edit"))
async def cb_edit(call: CallbackQuery, callback_data: AuditAction, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    audit_id = callback_data.audit_id
    async with get_session() as session:
        request = await session.get(AuditRequest, audit_id)
        if request is None:
            await call.message.answer(texts.ADMIN_NOT_FOUND.format(audit_id=audit_id))
            await call.answer()
            return
        if request.status not in OPEN_STATUSES:
            await call.message.answer(texts.ADMIN_ALREADY_HANDLED.format(status=request.status))
            await call.answer()
            return

    await state.set_state(VerdictEdit.waiting_for_text)
    await state.update_data(audit_id=audit_id)
    await call.message.answer(texts.ADMIN_EDIT_PROMPT.format(audit_id=audit_id))
    await call.answer()


@router.callback_query(AuditAction.filter(F.action == "later"))
async def cb_later(call: CallbackQuery, callback_data: AuditAction) -> None:
    if call.message is None:
        await call.answer()
        return

    audit_id = callback_data.audit_id
    async with get_session() as session:
        request = await session.get(AuditRequest, audit_id)
        if request is None:
            await call.message.answer(texts.ADMIN_NOT_FOUND.format(audit_id=audit_id))
            await call.answer()
            return
        if request.status not in OPEN_STATUSES:
            await call.message.answer(texts.ADMIN_ALREADY_HANDLED.format(status=request.status))
            await call.answer()
            return
        request.status = "manual"
        session.add(
            Event(
                telegram_id=request.telegram_id,
                event_type="audit_manual",
                meta={"audit_id": audit_id},
            )
        )

    await call.message.answer(texts.ADMIN_MARKED_MANUAL.format(audit_id=audit_id))
    await call.answer()


@router.message(VerdictEdit.waiting_for_text, Command("cancel"))
async def cmd_cancel_edit(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await message.answer(texts.ADMIN_EDIT_CANCELLED.format(audit_id=data.get("audit_id", "?")))


@router.message(VerdictEdit.waiting_for_text)
async def on_verdict_text(message: Message, state: FSMContext) -> None:
    if not message.text and not message.html_text:
        return

    data = await state.get_data()
    audit_id = data.get("audit_id")
    await state.clear()
    if audit_id is None:
        await message.answer("Потерял, к какому аудиту это относится. Нажми «✏️» ещё раз.")
        return

    # html_text сохраняет разметку, которую админ набрал в клиенте.
    await _deliver(message, int(audit_id), message.html_text)


# ─── /auditcard — полный текст заявки без обрезки ──────────────────────────

@router.message(Command("auditcard"))
async def cmd_auditcard(message: Message, command: CommandObject) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: <code>/auditcard &lt;id&gt;</code>")
        return

    audit_id = int(command.args.strip())
    async with get_session() as session:
        request = await session.get(AuditRequest, audit_id)
        if request is None:
            await message.answer(texts.ADMIN_NOT_FOUND.format(audit_id=audit_id))
            return
        answers = request.answers or {}
        parts = [
            f"🔍 <b>Аудит #{audit_id}</b>  ·  статус: <b>{request.status}</b>",
            f"От: {_who(request)}  ·  source: {html.escape(request.source or '—')}",
            f"Создан: {request.created_at}",
            "",
            f"<b>Идея:</b>\n{html.escape(request.idea or '—')}",
        ]

    for idx, (key, _text) in enumerate(texts.QUESTIONS, start=1):
        parts.append(f"\n<b>{idx}.</b> {html.escape(answers.get(key) or '(не ответил)')}")

    # Режем по лимиту Telegram, а не молча теряем хвост.
    out = "\n".join(parts)
    for chunk in (out[i : i + 3900] for i in range(0, len(out), 3900)):
        await message.answer(chunk)
