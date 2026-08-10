"""Проверки против настоящего Postgres: /sources, цепочка напоминаний, аудит."""
import asyncio
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

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

from db.models import AuditRequest, Event, Lead, WebinarRegistration
from db.session import SessionLocal
from services import webinar as svc
from services.analytics import format_sources, funnel_snapshot, format_stats, sources_report

failures = []


def check(label, cond, detail=""):
    print(f"{'OK  ' if cond else 'FAIL'}  {label}{('  — ' + str(detail)) if detail else ''}")
    if not cond:
        failures.append(label)


class FakeBot:
    """Ловит send_message вместо похода в Telegram."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))


async def main():
    now = datetime.now(timezone.utc)

    # ─── данные для /sources ───────────────────────────────────────────
    async with SessionLocal() as s:
        # li: 3 старта от 2 человек, из них один — 40 дней назад (вне окна 7д)
        s.add_all([
            Event(telegram_id=1, event_type="start", meta={"source": "li"}, created_at=now - timedelta(days=1)),
            Event(telegram_id=1, event_type="start", meta={"source": "li"}, created_at=now - timedelta(days=2)),
            Event(telegram_id=2, event_type="start", meta={"source": "li"}, created_at=now - timedelta(days=3)),
            Event(telegram_id=3, event_type="start", meta={"source": "li"}, created_at=now - timedelta(days=40)),
            Event(telegram_id=4, event_type="start", meta={"source": "ah"}, created_at=now - timedelta(days=1)),
            Event(telegram_id=5, event_type="start", meta={"source": "tg"}, created_at=now - timedelta(hours=2)),
            # без метки (прямой заход) — meta['source'] = null
            Event(telegram_id=6, event_type="start", meta={"source": None}, created_at=now - timedelta(hours=5)),
            # чужое событие того же периода не должно попасть в отчёт
            Event(telegram_id=7, event_type="diagnostic_complete", meta={"source": "li"}, created_at=now),
        ])
        s.add(Lead(telegram_id=1, source="li"))
        s.add(AuditRequest(telegram_id=1, source="li", status="sent", answers={"q1": "x"}))
        s.add(WebinarRegistration(telegram_id=1, webinar_key=svc.webinar_key(), source="li",
                                  next_reminder_stage=1, next_reminder_at=now + timedelta(days=1)))
        await s.commit()

    rep = await sources_report(7)
    by = {r["source"]: r for r in rep["rows"]}
    check("/sources: li = 3 старта / 2 человека", by["li"]["starts"] == 3 and by["li"]["people"] == 2, by.get("li"))
    check("/sources: старт 40-дневной давности отфильтрован", by["li"]["starts"] == 3)
    check("/sources: ah и tg на месте", by.get("ah", {}).get("starts") == 1 and by.get("tg", {}).get("starts") == 1)
    check("/sources: null-метка отдельной строкой", None in by, list(by))
    check("/sources: чужие event_type не попали", sum(r["starts"] for r in rep["rows"]) == 6,
          sum(r["starts"] for r in rep["rows"]))
    check("/sources: аудиты подтянулись по метке", by["li"]["audits"] == 1)
    check("/sources: регистрации подтянулись по метке", by["li"]["regs"] == 1)

    rep30 = await sources_report(30)
    check("/sources 30д не включает 40-дневный старт",
          {r["source"]: r for r in rep30["rows"]}["li"]["starts"] == 3)
    rep60 = await sources_report(60)
    check("/sources 60д включает его", {r["source"]: r for r in rep60["rows"]}["li"]["starts"] == 4)

    print("\n--- рендер /sources 7д ---")
    print(format_sources(rep))
    print("---\n")

    # ─── цепочка напоминаний ──────────────────────────────────────────
    bot = FakeBot()
    # 1) ещё не время — sweep молчит
    await svc.reminder_sweep(bot)
    check("sweep не шлёт раньше времени", len(bot.sent) == 0, bot.sent)

    # 2) просрочено — шлёт и двигает стадию
    async with SessionLocal() as s:
        reg = (await s.execute(select(WebinarRegistration).where(WebinarRegistration.telegram_id == 1))).scalar_one()
        reg.next_reminder_at = now - timedelta(minutes=1)
        reg.next_reminder_stage = 1
        await s.commit()

    await svc.reminder_sweep(bot)
    check("sweep отправил напоминание стадии 1", len(bot.sent) == 1, bot.sent)
    check("в тексте есть дата эфира", "27 августа" in bot.sent[0][1] if bot.sent else False)

    async with SessionLocal() as s:
        reg = (await s.execute(select(WebinarRegistration).where(WebinarRegistration.telegram_id == 1))).scalar_one()
        moved = reg.next_reminder_stage
        nxt = reg.next_reminder_at
    check("стадия сдвинулась вперёд", moved != 1, f"stage={moved} next_at={nxt}")

    # 3) повторный проход не дублирует
    await svc.reminder_sweep(bot)
    check("повторный sweep не дублирует", len(bot.sent) == 1, len(bot.sent))

    # 4) событие записалось
    async with SessionLocal() as s:
        cnt = await s.scalar(select(Event.id).where(Event.event_type == "webinar_reminder_sent").limit(1))
    check("webinar_reminder_sent залогирован", cnt is not None)

    # ─── сценарии со сдвинутой датой эфира ────────────────────────────
    from config import get_settings

    async def with_webinar_at(iso, fn):
        os.environ["WEBINAR_AT"] = iso
        get_settings.cache_clear()
        try:
            await fn()
        finally:
            os.environ["WEBINAR_AT"] = "2026-08-27T18:00:00+03:00"
            get_settings.cache_clear()

    # A. Эфир через 1ч05м: актуально только касание «за час» → потом цепочка закрыта.
    async def scenario_last_hour():
        bot2 = FakeBot()
        stage, at = svc.next_stage_after(datetime.now(timezone.utc))
        check("A: регистрация за час до эфира → сразу стадия 3", stage == 3, f"stage={stage}")
        async with SessionLocal() as s:
            s.add(WebinarRegistration(telegram_id=901, webinar_key=svc.webinar_key(),
                                      next_reminder_stage=3,
                                      next_reminder_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await s.commit()
        await svc.reminder_sweep(bot2)
        check("A: касание «за час» отправлено", len(bot2.sent) == 1, bot2.sent)
        check("A: текст именно про час", "Через час" in bot2.sent[0][1] if bot2.sent else False)
        async with SessionLocal() as s:
            reg = (await s.execute(select(WebinarRegistration).where(
                WebinarRegistration.telegram_id == 901))).scalar_one()
            check("A: цепочка закрыта (STAGE_DONE)", reg.next_reminder_stage == svc.STAGE_DONE,
                  reg.next_reminder_stage)
            check("A: next_reminder_at обнулён", reg.next_reminder_at is None)
        await svc.reminder_sweep(bot2)
        check("A: закрытая цепочка больше не шлёт", len(bot2.sent) == 1)

    nowu = datetime.now(timezone.utc)
    await with_webinar_at((nowu + timedelta(hours=1, minutes=5)).isoformat(), scenario_last_hour)

    # B. Бот лежал сутки: протухшее «за 3 дня» не досылаем, а перешагиваем.
    async def scenario_stale():
        bot3 = FakeBot()
        async with SessionLocal() as s:
            s.add(WebinarRegistration(telegram_id=902, webinar_key=svc.webinar_key(),
                                      next_reminder_stage=1,
                                      next_reminder_at=datetime.now(timezone.utc) - timedelta(days=1)))
            await s.commit()
        await svc.reminder_sweep(bot3)
        check("B: протухшее касание не отправлено", len(bot3.sent) == 0, bot3.sent)
        async with SessionLocal() as s:
            reg = (await s.execute(select(WebinarRegistration).where(
                WebinarRegistration.telegram_id == 902))).scalar_one()
            check("B: но цепочка сдвинулась на стадию 2", reg.next_reminder_stage == 2,
                  reg.next_reminder_stage)
            check("B: и не застряла", reg.next_reminder_at is not None and
                  reg.next_reminder_at > datetime.now(timezone.utc))

    await with_webinar_at((nowu + timedelta(days=2)).isoformat(), scenario_stale)

    # C. /stop должен глушить напоминания (их шлёт не drip_sweep)
    async def scenario_unsubscribed():
        bot4 = FakeBot()
        async with SessionLocal() as s:
            s.add(Lead(telegram_id=903, is_subscribed=False))  # отписался через /stop
            s.add(Lead(telegram_id=904, is_subscribed=True))
            s.add(WebinarRegistration(telegram_id=903, webinar_key=svc.webinar_key(),
                                      next_reminder_stage=3,
                                      next_reminder_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            s.add(WebinarRegistration(telegram_id=904, webinar_key=svc.webinar_key(),
                                      next_reminder_stage=3,
                                      next_reminder_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            # 905 — регистрация без строки в leads: терять её нельзя
            s.add(WebinarRegistration(telegram_id=905, webinar_key=svc.webinar_key(),
                                      next_reminder_stage=3,
                                      next_reminder_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await s.commit()
        await svc.reminder_sweep(bot4)
        got = sorted(m[0] for m in bot4.sent)
        check("C: отписавшийся (903) напоминание НЕ получил", 903 not in got, got)
        check("C: подписанный (904) получил", 904 in got, got)
        check("C: регистрация без лида (905) получила", 905 in got, got)

    await with_webinar_at((nowu + timedelta(hours=1, minutes=5)).isoformat(), scenario_unsubscribed)

    # D. /webinars показывает взведённую цепочку
    from services.analytics import format_webinar, webinar_snapshot

    snap = await webinar_snapshot()
    txt = format_webinar(snap)
    check("/webinars: считает записанных", snap["total"] >= 1, snap["total"])
    check("/webinars: показывает расписание касаний", "стадия 1:" in txt, txt[:200])
    check("/webinars: пишет статус регистрации", "регистрация открыта" in txt)
    print("\n--- рендер /webinars ---")
    print(txt)
    print("---\n")

    # ─── /stats не сломался ───────────────────────────────────────────
    snap = await funnel_snapshot()
    text = format_stats(snap)
    check("/stats по-прежнему рендерится", "Воронка AIstack-bot" in text)

    print("\n" + ("ВСЁ ЗЕЛЁНОЕ" if not failures else f"ПРОВАЛЫ: {failures}"))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
