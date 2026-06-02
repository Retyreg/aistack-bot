from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from texts import messages


def welcome_kb() -> InlineKeyboardMarkup:
    """Кнопка после welcome — старт диагностики."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=messages.WELCOME_BUTTON, callback_data="diag_start"))
    return builder.as_markup()
