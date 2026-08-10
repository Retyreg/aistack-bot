from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import get_settings
from texts import audit as audit_texts
from texts import messages
from texts import webinar as webinar_texts


class DiagAnswer(CallbackData, prefix="diag"):
    """callback ответа на вопрос диагностики: q ∈ {1,2,3}, seg ∈ {marketer,ops,product}."""

    q: int
    seg: str


class TariffChoice(CallbackData, prefix="tariff"):
    """callback выбора тарифа в оффере. code ∈ {self, supported, personal, ask}."""

    code: str


class AuditAction(CallbackData, prefix="aud"):
    """Решение админа по черновику вердикта. action ∈ {send, edit, later}.

    audit_id носим прямо в callback: FSM живёт в MemoryStorage и умирает при
    рестарте, а заявка может ждать одобрения часами. Кнопка остаётся рабочей.
    """

    action: str
    audit_id: int


def welcome_kb(*, webinar_open: bool = True) -> InlineKeyboardMarkup:
    """Главное меню: аудит идеи (основной магнит), вебинар, диагностика.

    Прошедший эфир из меню убираем — кнопка на него всё равно ответила бы
    «этот эфир уже прошёл».
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=audit_texts.AUDIT_BUTTON, callback_data="audit_start"))
    if webinar_open:
        builder.row(
            InlineKeyboardButton(text=webinar_texts.WEBINAR_BUTTON, callback_data="webinar_reg")
        )
    builder.row(InlineKeyboardButton(text=messages.WELCOME_BUTTON, callback_data="diag_start"))
    return builder.as_markup()


def audit_offer_kb() -> InlineKeyboardMarkup:
    """«Да, разбери мою идею» — после свободного текста в холодную."""
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text=audit_texts.AUDIT_OFFER_BUTTON, callback_data="audit_start")
    )
    return builder.as_markup()


def audit_verdict_kb() -> InlineKeyboardMarkup:
    """CTA под вердиктом: запись на вебинар + тарифы курса."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=webinar_texts.WEBINAR_BUTTON, callback_data="webinar_reg")
    )
    builder.row(
        InlineKeyboardButton(text=messages.PRICING_BUTTON, url=get_settings().landing_url)
    )
    return builder.as_markup()


def audit_admin_kb(audit_id: int) -> InlineKeyboardMarkup:
    """Три решения по черновику: отправить / отредактировать / позже."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=audit_texts.ADMIN_BTN_SEND,
            callback_data=AuditAction(action="send", audit_id=audit_id).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=audit_texts.ADMIN_BTN_EDIT,
            callback_data=AuditAction(action="edit", audit_id=audit_id).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=audit_texts.ADMIN_BTN_LATER,
            callback_data=AuditAction(action="later", audit_id=audit_id).pack(),
        )
    )
    return builder.as_markup()


def webinar_reminder_kb(*, with_join: bool) -> InlineKeyboardMarkup | None:
    """Под напоминанием: «Подключиться» (если задан WEBINAR_JOIN_URL) для
    касания «за час», иначе — аудит идеи как следующий шаг."""
    join_url = get_settings().webinar_join_url
    builder = InlineKeyboardBuilder()
    if with_join and join_url:
        builder.row(
            InlineKeyboardButton(text=webinar_texts.WEBINAR_JOIN_BUTTON, url=join_url)
        )
    elif not with_join:
        builder.row(
            InlineKeyboardButton(text=audit_texts.AUDIT_BUTTON, callback_data="audit_start")
        )
    else:
        return None
    return builder.as_markup()


def replay_kb() -> InlineKeyboardMarkup:
    """Кнопка-ссылка на запись эфира (прикрепляется к PDF лид-магнита)."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=messages.REPLAY_BUTTON, url=get_settings().replay_url))
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


def book_now_self_eb_kb() -> InlineKeyboardMarkup:
    """Одна кнопка 'Забронировать за $200' → TariffChoice(self), для пуша 09.06."""
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text=messages.PUSH_EARLYBIRD_BUTTON,
            callback_data=TariffChoice(code="self").pack(),
        )
    )
    return builder.as_markup()


def offer_kb(early_bird_active: bool) -> InlineKeyboardMarkup:
    """4 кнопки: 3 тарифа + 'Остался вопрос'."""
    builder = InlineKeyboardBuilder()
    self_label = (
        messages.TARIFF_LABELS["self_eb"] if early_bird_active else messages.TARIFF_LABELS["self_regular"]
    )
    builder.row(InlineKeyboardButton(text=self_label, callback_data=TariffChoice(code="self").pack()))
    builder.row(
        InlineKeyboardButton(
            text=messages.TARIFF_LABELS["supported"], callback_data=TariffChoice(code="supported").pack()
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=messages.TARIFF_LABELS["personal"], callback_data=TariffChoice(code="personal").pack()
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=messages.TARIFF_LABELS["ask"], callback_data=TariffChoice(code="ask").pack()
        )
    )
    return builder.as_markup()
