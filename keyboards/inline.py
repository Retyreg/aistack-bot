from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from texts import messages


class DiagAnswer(CallbackData, prefix="diag"):
    """callback для ответа на вопрос диагностики: q ∈ {1,2,3}, seg ∈ {marketer,ops,product}."""

    q: int
    seg: str


def welcome_kb() -> InlineKeyboardMarkup:
    """Кнопка после welcome — старт диагностики."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=messages.WELCOME_BUTTON, callback_data="diag_start"))
    return builder.as_markup()


def _question_kb(q: int, options: dict[str, str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seg, label in options.items():
        builder.row(
            InlineKeyboardButton(text=label, callback_data=DiagAnswer(q=q, seg=seg).pack())
        )
    return builder.as_markup()


def q1_kb() -> InlineKeyboardMarkup:
    return _question_kb(1, messages.Q1_OPTIONS)


def q2_kb() -> InlineKeyboardMarkup:
    return _question_kb(2, messages.Q2_OPTIONS)


def q3_kb() -> InlineKeyboardMarkup:
    return _question_kb(3, messages.Q3_OPTIONS)
