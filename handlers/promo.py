import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import get_settings
from services import promo

logger = logging.getLogger(__name__)
router = Router(name="promo")


def promo_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Подписаться на AI Stack", url=promo.CHANNEL_URL))
    builder.row(InlineKeyboardButton(text="Проверить подписку", callback_data="promo_check"))
    return builder.as_markup()


def course_kb(url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Открыть курс на Stepik", url=url))
    return builder.as_markup()


async def show_promo(message: Message) -> None:
    if not promo.is_active():
        await message.answer(
            "Акция для подписчиков завершена или ещё не началась. "
            "Обычная стоимость курса — 12 900 ₽.",
            reply_markup=course_kb(promo.COURSE_URL),
        )
        return
    await message.answer(
        "Подпишись на канал AI Stack и получи скидку 5 000 ₽ на курс "
        "«AI вместо штата» — цена для подписчиков 7 900 ₽ вместо 12 900 ₽.\n\n"
        "После подписки нажми «Проверить подписку». "
        "Акция действует с 16 по 22 ноября 2026 года включительно, по московскому времени.",
        reply_markup=promo_kb(),
    )


@router.callback_query(F.data == "promo_open")
async def open_promo(call: CallbackQuery) -> None:
    if call.message is None or call.message.chat.type != "private":
        await call.answer("Открой бота в личных сообщениях.", show_alert=True)
        return
    await show_promo(call.message)
    await call.answer()


@router.callback_query(F.data == "promo_check")
async def check_promo(call: CallbackQuery) -> None:
    if call.message is None or call.message.chat.type != "private":
        await call.answer("Открой бота в личных сообщениях.", show_alert=True)
        return
    if not promo.is_active():
        await show_promo(call.message)
        await call.answer()
        return
    try:
        member = await call.bot.get_chat_member(chat_id=promo.CHANNEL, user_id=call.from_user.id)
    except TelegramAPIError:
        logger.exception("Could not check promo channel membership")
        await call.answer(
            "Не удалось проверить подписку. Попробуй позже или напиши @vatyutov.",
            show_alert=True,
        )
        return

    if not promo.is_active():
        await show_promo(call.message)
    elif member.status in ("creator", "administrator", "member") or (
        member.status == "restricted" and member.is_member
    ):
        settings = get_settings()
        if not settings.subscriber_promo_code or not settings.subscriber_promo_url:
            logger.error("Subscriber promo code or URL is not configured")
            await call.answer(
                "Не удалось выдать промокод. Попробуй позже или напиши @vatyutov.",
                show_alert=True,
            )
            return
        await call.message.answer(
            f"Подписка подтверждена! Промокод: <b>{escape(settings.subscriber_promo_code)}</b>.\n\n"
            "Цена курса — 7 900 ₽ вместо 12 900 ₽. "
            "Введи промокод на Stepik и проверь итоговую цену до оплаты. "
            "Акция действует до 22 ноября 2026 года включительно, по МСК.\n\n"
            "Если курс тебе полезен, можешь поделиться им с друзьями — это необязательно.",
            reply_markup=course_kb(settings.subscriber_promo_url),
        )
    else:
        await call.message.answer(
            "Пока не вижу подписку. Подпишись на канал и нажми «Проверить подписку» ещё раз.",
            reply_markup=promo_kb(),
        )
    await call.answer()
