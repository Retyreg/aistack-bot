import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import FSInputFile, Message
from sqlalchemy import select

from config import is_webinar_source
from db.models import Event, Lead
from db.session import get_session
from keyboards.inline import replay_kb, welcome_kb
from services.events import event_exists, log_event
from texts import messages

logger = logging.getLogger(__name__)
router = Router(name="start")

# Лид-магнит с вебинара: PDF лежит в репо (попадает на сервер через git).
# Путь от корня репо — не зависит от CWD процесса.
WEBINAR_LEADMAGNET_PDF = (
    Path(__file__).resolve().parent.parent / "assets" / "AIstack-competitor-analysis-prompt.pdf"
)


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    """Upsert лида, лог start. С вебинар-источников — промт+реплей, затем мостик
    в диагностику; иначе — обычный welcome с кнопкой диагностики.
    """
    user = message.from_user
    if user is None:
        return

    source = command.args or None

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.telegram_id == user.id))
        lead = result.scalar_one_or_none()

        if lead is None:
            lead = Lead(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                source=source,
            )
            session.add(lead)
        else:
            lead.username = user.username
            lead.first_name = user.first_name
            if not lead.source and source:
                lead.source = source
            lead.is_subscribed = True

        session.add(Event(telegram_id=user.id, event_type="start", meta={"source": source}))

        webinar = is_webinar_source(lead.source)
        # Идемпотентность: на повторный /start промт не дублируем (мостик — да).
        magnet_already_sent = (
            await event_exists(session, user.id, "leadmagnet_sent", meta_kind="webinar")
            if webinar
            else False
        )

    if webinar:
        if not magnet_already_sent:
            await message.answer(messages.WEBINAR_LEADMAGNET_INTRO)
            await message.answer_document(
                FSInputFile(WEBINAR_LEADMAGNET_PDF),
                caption=messages.WEBINAR_LEADMAGNET_CAPTION,
                reply_markup=replay_kb(),
            )
            async with get_session() as session:
                await log_event(session, user.id, "leadmagnet_sent", meta={"kind": "webinar"})
        await message.answer(messages.WEBINAR_AFTER_MAGNET, reply_markup=welcome_kb())
        return

    await message.answer(messages.WELCOME, reply_markup=welcome_kb())
