import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from sqlalchemy import select

from db.models import Event, Lead
from db.session import get_session
from keyboards.inline import DiagAnswer, q1_kb, q2_kb, q3_kb
from services.funnel import Segment, calc_segment, compute_first_touch_at
from texts import messages, prompts

logger = logging.getLogger(__name__)
router = Router(name="diagnostic")


class DiagnosticFlow(StatesGroup):
    q1 = State()
    q2 = State()
    q3 = State()


@router.callback_query(F.data == "diag_start")
async def diag_start(call: CallbackQuery, state: FSMContext) -> None:
    """Стартует диагностику: лог diagnostic_start, FSM=q1, Q1."""
    if call.from_user is None or call.message is None:
        await call.answer()
        return

    async with get_session() as session:
        session.add(Event(telegram_id=call.from_user.id, event_type="diagnostic_start"))

    await state.set_state(DiagnosticFlow.q1)
    await state.update_data(answers={})
    await call.message.answer(messages.Q1_TEXT, reply_markup=q1_kb())
    await call.answer()


@router.callback_query(DiagnosticFlow.q1, DiagAnswer.filter(F.q == 1))
async def on_q1(call: CallbackQuery, callback_data: DiagAnswer, state: FSMContext) -> None:
    data = await state.get_data()
    answers = dict(data.get("answers") or {})
    answers["q1"] = callback_data.seg
    await state.update_data(answers=answers)
    await state.set_state(DiagnosticFlow.q2)

    if call.message is not None:
        await call.message.answer(messages.Q2_TEXT, reply_markup=q2_kb())
    await call.answer()


@router.callback_query(DiagnosticFlow.q2, DiagAnswer.filter(F.q == 2))
async def on_q2(call: CallbackQuery, callback_data: DiagAnswer, state: FSMContext) -> None:
    data = await state.get_data()
    answers = dict(data.get("answers") or {})
    answers["q2"] = callback_data.seg
    await state.update_data(answers=answers)
    await state.set_state(DiagnosticFlow.q3)

    if call.message is not None:
        await call.message.answer(messages.Q3_TEXT, reply_markup=q3_kb())
    await call.answer()


@router.callback_query(DiagnosticFlow.q3, DiagAnswer.filter(F.q == 3))
async def on_q3(call: CallbackQuery, callback_data: DiagAnswer, state: FSMContext) -> None:
    if call.from_user is None or call.message is None:
        await call.answer()
        return

    data = await state.get_data()
    answers = dict(data.get("answers") or {})
    answers["q3"] = callback_data.seg

    seg_list: list[Segment] = [answers["q1"], answers["q2"], answers["q3"]]
    segment = calc_segment(seg_list)
    completed_at = datetime.now(timezone.utc)
    next_action_at = compute_first_touch_at(completed_at)

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.telegram_id == call.from_user.id))
        lead = result.scalar_one_or_none()
        if lead is None:
            # защитный путь: лид удалили вручную, /start не нажал — пересоздать
            lead = Lead(
                telegram_id=call.from_user.id,
                username=call.from_user.username,
                first_name=call.from_user.first_name,
            )
            session.add(lead)

        lead.segment = segment
        lead.diagnostic_answers = answers
        lead.diagnostic_completed_at = completed_at
        lead.funnel_stage = "warming"
        lead.next_touch = 1
        lead.next_action_at = next_action_at

        session.add(
            Event(
                telegram_id=call.from_user.id,
                event_type="diagnostic_complete",
                meta={"segment": segment, "answers": answers},
            )
        )

    # 1) шапка результата + плашка про подарок
    await call.message.answer(messages.RESULT_HEADER[segment])

    # 2) 4 промпта по сегменту, каждый отдельным сообщением (title + <pre>body</pre>)
    for prompt in prompts.by_segment(segment):
        text = f"<b>{prompt.title}</b>\n<pre>{prompt.body}</pre>"
        await call.message.answer(text)

    # 3) P.S. с затравкой на следующий шаг прогрева
    await call.message.answer(messages.RESULT_PS[segment])

    async with get_session() as session:
        session.add(Event(telegram_id=call.from_user.id, event_type="leadmagnet_sent"))

    await state.clear()
    await call.answer()
