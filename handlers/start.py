import logging

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy import select

from db.models import Event, Lead
from db.session import get_session
from keyboards.inline import welcome_kb
from texts import messages

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    """Upsert лида, лог start, welcome + кнопка диагностики."""
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

    await message.answer(messages.WELCOME, reply_markup=welcome_kb())
