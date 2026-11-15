import os
import pathlib
import sys
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ["BOT_TOKEN"] = "123456:TEST-TOKEN-NOT-REAL"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:5999/x"
os.environ["ADMIN_IDS"] = "111"
os.environ["EARLYBIRD_DEADLINE"] = "2026-09-03"
os.environ["COURSE_START"] = "2026-09-10"
os.environ["SUBSCRIBER_PROMO_CODE"] = "TESTCODE"
os.environ["SUBSCRIBER_PROMO_URL"] = "https://example.com/promo"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChatMember

from handlers import promo as handler
from handlers import start
from keyboards.inline import welcome_kb
from services import promo


def callback(status="member", *, is_member=False, chat_type="private"):
    message = SimpleNamespace(
        chat=SimpleNamespace(type=chat_type),
        answer=AsyncMock(),
    )
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(
            return_value=SimpleNamespace(status=status, is_member=is_member)
        )
    )
    return SimpleNamespace(
        message=message, bot=bot, from_user=SimpleNamespace(id=42), answer=AsyncMock()
    )


class PromoTests(unittest.IsolatedAsyncioTestCase):
    def test_promo_window_moscow_boundaries(self):
        self.assertFalse(promo.is_active(datetime(2026, 11, 15, 20, 59, 59, tzinfo=timezone.utc)))
        self.assertTrue(promo.is_active(datetime(2026, 11, 15, 21, 0, 0, tzinfo=timezone.utc)))
        self.assertTrue(promo.is_active(datetime(2026, 11, 22, 20, 59, 59, tzinfo=timezone.utc)))
        self.assertFalse(promo.is_active(datetime(2026, 11, 22, 21, 0, 0, tzinfo=timezone.utc)))
        with self.assertRaises(ValueError):
            promo.is_active(datetime(2026, 11, 16))

    async def test_member_gets_code_and_link(self):
        for status, is_member in [
            ("creator", False), ("administrator", False), ("member", False), ("restricted", True)
        ]:
            with self.subTest(status=status), patch.object(promo, "is_active", return_value=True):
                call = callback(status, is_member=is_member)
                await handler.check_promo(call)
                call.bot.get_chat_member.assert_awaited_once_with(chat_id="@aistackca", user_id=42)
                args, kwargs = call.message.answer.await_args
                self.assertIn("TESTCODE", args[0])
                self.assertIn("7 900", args[0])
                self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].url, "https://example.com/promo")
                call.answer.assert_awaited_once()

    async def test_nonmembers_never_receive_code(self):
        for status, is_member in [("left", False), ("kicked", False), ("restricted", False)]:
            with self.subTest(status=status), patch.object(promo, "is_active", return_value=True):
                call = callback(status, is_member=is_member)
                await handler.check_promo(call)
                args, kwargs = call.message.answer.await_args
                self.assertNotIn("TESTCODE", args[0])
                self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].url, promo.CHANNEL_URL)
                call.answer.assert_awaited_once()

    async def test_telegram_error_does_not_issue_code(self):
        call = callback()
        call.bot.get_chat_member.side_effect = TelegramBadRequest(
            method=GetChatMember(chat_id="@aistackca", user_id=42), message="chat not found"
        )
        with patch.object(promo, "is_active", return_value=True), self.assertLogs(
            handler.logger, level="ERROR"
        ):
            await handler.check_promo(call)
        call.message.answer.assert_not_awaited()
        self.assertIn("Не удалось", call.answer.await_args.args[0])

    async def test_expired_or_group_callback_never_gets_code(self):
        with patch.object(promo, "is_active", return_value=False):
            call = callback()
            await handler.check_promo(call)
            call.bot.get_chat_member.assert_not_awaited()
            args, kwargs = call.message.answer.await_args
            self.assertNotIn("TESTCODE", args[0])
            self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].url, promo.COURSE_URL)
        with patch.object(promo, "is_active", return_value=True):
            call = callback(chat_type="supergroup")
            await handler.check_promo(call)
            call.bot.get_chat_member.assert_not_awaited()
            call.message.answer.assert_not_awaited()
            call.answer.assert_awaited_once()

    async def test_expiry_during_membership_check(self):
        call = callback()
        with patch.object(promo, "is_active", side_effect=[True, False, False]):
            await handler.check_promo(call)
        args, kwargs = call.message.answer.await_args
        self.assertNotIn("TESTCODE", args[0])
        self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].url, promo.COURSE_URL)

    async def test_deep_link_does_not_replace_existing_webinar_flow(self):
        lead = SimpleNamespace(source="src_yt", username=None, first_name=None, is_subscribed=False)
        result = SimpleNamespace(scalar_one_or_none=lambda: lead)
        session = SimpleNamespace(execute=AsyncMock(return_value=result), add=lambda event: None)

        @asynccontextmanager
        async def fake_session():
            yield session

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=42, username="user", first_name="User"),
            answer=AsyncMock(),
        )
        with patch.object(start, "get_session", fake_session), \
             patch.object(start, "event_exists", AsyncMock(return_value=True)), \
             patch.object(promo, "is_active", return_value=True):
            await start.cmd_start(message, SimpleNamespace(args="sub_promo"))
        self.assertIn("Проверить подписку", str(message.answer.await_args.kwargs["reply_markup"]))
        self.assertTrue(lead.is_subscribed)
        self.assertEqual(lead.source, "src_yt")

    async def test_missing_promo_configuration_is_reported(self):
        call = callback()
        with patch.object(promo, "is_active", return_value=True), \
             patch.object(handler, "get_settings", return_value=SimpleNamespace(
                 subscriber_promo_code="", subscriber_promo_url=""
             )), self.assertLogs(handler.logger, level="ERROR"):
            await handler.check_promo(call)
        call.message.answer.assert_not_awaited()
        self.assertIn("Не удалось", call.answer.await_args.args[0])

    def test_menu_preserves_diagnostic_and_audit(self):
        for active in (True, False):
            with patch("keyboards.inline.promo_is_active", return_value=active):
                callbacks = [
                    button.callback_data
                    for row in welcome_kb(webinar_open=False).inline_keyboard
                    for button in row
                ]
                self.assertIn("diag_start", callbacks)
                self.assertIn("audit_start", callbacks)
                self.assertEqual("promo_open" in callbacks, active)


if __name__ == "__main__":
    unittest.main()
