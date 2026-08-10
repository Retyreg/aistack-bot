"""Аудит идеи целиком, без Telegram: черновик → карточка админу → одобрение."""
import asyncio
import os
import pathlib
import sys

os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "111,222"
os.environ["EARLYBIRD_DEADLINE"] = "2026-09-01"
os.environ["COURSE_START"] = "2026-09-10"
os.environ["WEBINAR_AT"] = "2026-08-27T18:00:00+03:00"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://aistack:aistack@localhost:5433/aistack"
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import select

import handlers.audit as audit
import handlers.audit_admin as audit_admin
from db.models import AuditRequest, Event
from db.session import SessionLocal
from services.llm import LLMError

failures = []


def check(label, cond, detail=""):
    print(f"{'OK  ' if cond else 'FAIL'}  {label}{('  — ' + str(detail)) if detail else ''}")
    if not cond:
        failures.append(label)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append({"chat": chat_id, "text": text, "kb": reply_markup})


class FakeMessage:
    """Достаточно для _draft_and_notify и _deliver: .bot и .answer()."""

    def __init__(self, bot):
        self.bot = bot
        self.replies = []

    async def answer(self, text, reply_markup=None):
        self.replies.append(text)


IDEA = "Сервис подписки на домашнюю еду от соседских поваров в Алматы"
ANSWERS = {
    "q1": "Айгуль, 34, маркетолог в банке, двое детей, готовить некогда",
    "q2": "Ужин. Сейчас заказывает доставку из ресторанов — дорого и жирно",
    "q3": "Платит сама. Сейчас — потому что вышла из декрета и времени нет совсем",
    "q4": "Опросил 12 знакомых, 4 сказали что купили бы. Ничего не продавал",
    "q5": "Домашняя еда, а не ресторанная. Повар — сосед, знаешь его в лицо",
}


async def main():
    bot = FakeBot()
    msg = FakeMessage(bot)

    # ─── 1. LLM недоступен: заявка всё равно сохраняется, админ уведомлён ──
    async def boom(*a, **kw):
        raise LLMError("OPENROUTER_API_KEY не задан")

    audit.complete = boom
    await audit._draft_and_notify(msg, 555, "testuser", "Тест", IDEA, ANSWERS)

    async with SessionLocal() as s:
        req = (await s.execute(select(AuditRequest).where(AuditRequest.telegram_id == 555))).scalar_one()
    check("LLM упал → заявка сохранена", req.idea == IDEA)
    check("LLM упал → ответы сохранены целиком", req.answers == ANSWERS)
    check("LLM упал → статус failed", req.status == "failed", req.status)
    check("LLM упал → админам ушло 2 сообщения × 2 админа", len(bot.sent) == 4, len(bot.sent))
    card = bot.sent[0]["text"]
    check("карточка: есть идея", IDEA in card)
    check("карточка: есть ответы", "Айгуль" in card)
    check("карточка: влезает в лимит Telegram", len(card) < 4096, len(card))
    fail_card = bot.sent[2]["text"]
    check("карточка: сказано, что черновика нет", "не сгенерился" in fail_card)
    check("карточка: кнопки одобрения приложены", bot.sent[2]["kb"] is not None)

    # ─── 2. LLM ответил: pending_approval + черновик админу ───────────────
    DRAFT = "Идея жива, но пока это гипотеза. Первый шаг: продай пять ужинов до пятницы."

    async def ok(*a, **kw):
        return DRAFT

    audit.complete = ok
    bot.sent.clear()
    await audit._draft_and_notify(msg, 556, None, "Аноним", IDEA, ANSWERS)

    async with SessionLocal() as s:
        req2 = (await s.execute(select(AuditRequest).where(AuditRequest.telegram_id == 556))).scalar_one()
        audit_id = req2.id
    check("LLM ответил → статус pending_approval", req2.status == "pending_approval", req2.status)
    check("LLM ответил → черновик сохранён", req2.draft_text == DRAFT)
    check("черновик ушёл админу", any(DRAFT in m["text"] for m in bot.sent))

    # ─── 3. Одобрение «отправить как есть» ────────────────────────────────
    bot.sent.clear()
    admin_msg = FakeMessage(bot)
    await audit_admin._deliver(admin_msg, audit_id, DRAFT)

    check("вердикт ушёл пользователю", len(bot.sent) == 1, bot.sent)
    to_user = bot.sent[0]
    check("вердикт адресован автору идеи", to_user["chat"] == 556, to_user["chat"])
    check("вердикт содержит текст", DRAFT in to_user["text"])
    check("вердикт содержит CTA на вебинар 27.08", "27 августа" in to_user["text"], to_user["text"][-300:])
    check("под вердиктом кнопки (вебинар + тарифы)", to_user["kb"] is not None)
    check("админ получил подтверждение", any("отправлен" in r for r in admin_msg.replies), admin_msg.replies)

    async with SessionLocal() as s:
        req3 = await s.get(AuditRequest, audit_id)
        ev = (await s.execute(select(Event).where(Event.event_type == "audit_verdict_sent"))).scalars().all()
    check("статус → sent", req3.status == "sent", req3.status)
    check("final_text записан", req3.final_text == DRAFT)
    check("sent_at проставлен", req3.sent_at is not None)
    check("событие audit_verdict_sent записано", len(ev) == 1)
    check("пометка edited=False для «как есть»", ev[0].meta.get("edited") is False, ev[0].meta)

    # ─── 4. Отправка отредактированного текста ────────────────────────────
    bot.sent.clear()
    EDITED = "Мертва. Ты описал доставку еды, а не новый рынок."
    await audit_admin._deliver(FakeMessage(bot), audit_id, EDITED)
    async with SessionLocal() as s:
        ev2 = (await s.execute(
            select(Event).where(Event.event_type == "audit_verdict_sent").order_by(Event.id.desc())
        )).scalars().first()
    check("правка помечается edited=True", ev2.meta.get("edited") is True, ev2.meta)
    check("пользователю ушёл именно правленый текст", EDITED in bot.sent[0]["text"])

    print("\n" + ("ВСЁ ЗЕЛЁНОЕ" if not failures else f"ПРОВАЛЫ: {failures}"))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
