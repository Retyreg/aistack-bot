"""«Аудит идеи»: идея → 5 вопросов → AI-черновик → админу на одобрение.

Пользователю здесь ничего не уходит: вердикт отправляет handlers/audit_admin.py
после решения админа. Это осознанно — вердикт подписан именем Дмитрия, поэтому
он его и визирует.

Состояние заявки живёт в audit_requests, FSM — только для «на каком мы
вопросе». Рестарт бота в середине опроса теряет незавершённый интейк (у нас
MemoryStorage), но не теряет ни одной заявки, дошедшей до черновика.
"""

import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.models import AuditRequest, Event, Lead
from db.session import get_session
from keyboards.inline import audit_admin_kb
from services.llm import LLMError, complete
from services.notify import send_admin
from texts import audit as texts

logger = logging.getLogger(__name__)
router = Router(name="audit")

MAX_ANSWER_LEN = 2000
MIN_IDEA_LEN = 20
# Обрезка только для карточки админа; в БД и в промпт уходит полный текст.
CARD_ANSWER_LEN = 450
# Заявки в этих статусах ждут действий — второй аудит параллельно не начинаем.
BUSY_STATUSES = ("collecting", "pending_approval")


class AuditFlow(StatesGroup):
    idea = State()
    answers = State()


def _who(username: str | None, first_name: str | None, telegram_id: int) -> str:
    handle = f"@{html.escape(username)}" if username else f"id{telegram_id}"
    name = html.escape(first_name) if first_name else "—"
    return f"{name} ({handle})"


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _format_answers(answers: dict) -> str:
    """Ответы для карточки админа. Режем — карточка должна влезть в 4096;
    полный текст всегда доступен через /auditcard."""
    lines = []
    for idx, (key, _text) in enumerate(texts.QUESTIONS, start=1):
        value = (answers or {}).get(key) or "(не ответил)"
        lines.append(f"<b>{idx}.</b> {html.escape(_clip(value, CARD_ANSWER_LEN))}")
    return "\n\n".join(lines)


async def _has_pending(telegram_id: int) -> bool:
    """Есть незакрытая заявка на одобрении — второй аудит не начинаем."""
    async with get_session() as session:
        result = await session.execute(
            select(AuditRequest.id)
            .where(
                AuditRequest.telegram_id == telegram_id,
                AuditRequest.status.in_(("pending_approval", "failed")),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


async def _start_audit(message: Message, telegram_id: int, state: FSMContext) -> None:
    if await _has_pending(telegram_id):
        await message.answer(texts.AUDIT_ALREADY_PENDING)
        return

    async with get_session() as session:
        session.add(Event(telegram_id=telegram_id, event_type="audit_start"))

    await state.set_state(AuditFlow.idea)
    await state.update_data(answers={}, step=0)
    await message.answer(texts.AUDIT_INTRO)


async def begin_with_idea(message: Message, telegram_id: int, state: FSMContext, idea: str) -> None:
    """Вход в аудит из свободного текста: человек уже описал идею — не
    заставляем его печатать её второй раз, сразу переходим к вопросу 1."""
    if await _has_pending(telegram_id):
        await message.answer(texts.AUDIT_ALREADY_PENDING)
        return

    async with get_session() as session:
        session.add(
            Event(telegram_id=telegram_id, event_type="audit_start", meta={"via": "free_text"})
        )

    await state.set_state(AuditFlow.answers)
    await state.update_data(idea=idea[:MAX_ANSWER_LEN], answers={}, step=0)
    await message.answer(texts.AUDIT_FROM_FREE_TEXT)
    await message.answer(texts.QUESTIONS[0][1])


@router.callback_query(F.data == "audit_start")
async def cb_audit_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user is None or call.message is None:
        await call.answer()
        return
    await _start_audit(call.message, call.from_user.id, state)
    await call.answer()


@router.message(Command("audit"))
async def cmd_audit(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await _start_audit(message, message.from_user.id, state)


@router.message(AuditFlow.idea)
async def on_idea(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not message.text:
        return

    idea = message.text.strip()
    if len(idea) < MIN_IDEA_LEN:
        await message.answer(texts.AUDIT_IDEA_TOO_SHORT)
        return

    await state.update_data(idea=idea[:MAX_ANSWER_LEN], answers={}, step=0)
    await state.set_state(AuditFlow.answers)
    await message.answer(texts.QUESTIONS[0][1])


@router.message(AuditFlow.answers)
async def on_answer(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None or not message.text:
        return

    data = await state.get_data()
    step = int(data.get("step", 0))
    answers = dict(data.get("answers") or {})
    idea = data.get("idea")

    key = texts.QUESTION_KEYS[step]
    answers[key] = message.text.strip()[:MAX_ANSWER_LEN]
    step += 1

    if step < len(texts.QUESTIONS):
        await state.update_data(answers=answers, step=step)
        await message.answer(texts.QUESTIONS[step][1])
        return

    # Все пять собраны.
    await state.clear()
    await message.answer(texts.AUDIT_COLLECTED)
    await _draft_and_notify(message, user.id, user.username, user.first_name, idea, answers)


async def _draft_and_notify(
    message: Message,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    idea: str | None,
    answers: dict,
) -> None:
    """Сохранить заявку, сгенерить черновик, отдать админу на одобрение.

    Порядок важен: строка в БД пишется ДО вызова LLM. Если OpenRouter лежит,
    пятиминутный опрос не уходит в никуда — админ всё равно получает ответы
    и может написать вердикт руками.
    """
    async with get_session() as session:
        source = await session.scalar(select(Lead.source).where(Lead.telegram_id == telegram_id))
        request = AuditRequest(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            source=source,
            idea=idea,
            answers=answers,
            status="collecting",
        )
        session.add(request)
        await session.flush()
        audit_id = request.id
        session.add(
            Event(
                telegram_id=telegram_id,
                event_type="audit_submitted",
                meta={"audit_id": audit_id, "source": source},
            )
        )

    draft: str | None = None
    error: str | None = None
    try:
        draft = await complete(
            texts.VERDICT_SYSTEM_PROMPT,
            texts.build_user_prompt(idea, answers),
        )
    except LLMError as exc:
        error = str(exc)
        logger.warning("Audit #%s: draft failed — %s", audit_id, error)
    except Exception as exc:  # неожиданное — тоже не роняем интейк
        error = repr(exc)
        logger.exception("Audit #%s: unexpected draft failure", audit_id)

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        request = await session.get(AuditRequest, audit_id)
        if request is not None:
            request.draft_text = draft
            request.drafted_at = now
            # failed тоже ждёт админа — просто без черновика.
            request.status = "pending_approval" if draft else "failed"
        session.add(
            Event(
                telegram_id=telegram_id,
                event_type="audit_drafted",
                meta={"audit_id": audit_id, "ok": bool(draft), "error": error},
            )
        )

    if message.bot is None:
        return

    # Контекст и черновик — двумя сообщениями: вместе они пробивают лимит
    # Telegram в 4096 символов. Кнопки висят на втором.
    await send_admin(
        message.bot,
        texts.ADMIN_CONTEXT.format(
            audit_id=audit_id,
            who=_who(username, first_name, telegram_id),
            source=html.escape(source or "—"),
            idea=html.escape(_clip(idea or "—", 700)),
            answers=_format_answers(answers),
        ),
    )
    if draft:
        body = texts.ADMIN_DRAFT.format(audit_id=audit_id, draft=draft)
    else:
        body = texts.ADMIN_DRAFT_FAILED.format(
            audit_id=audit_id, error=html.escape((error or "unknown")[:200])
        )
    await send_admin(message.bot, body, reply_markup=audit_admin_kb(audit_id))
