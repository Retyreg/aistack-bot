"""Оффлайн-проверки: импорт всех модулей, сборка Dispatcher, арифметика напоминаний.

Polling НЕ запускаем: в .env лежит боевой BOT_TOKEN, второй поллер на том же
токене положил бы прод в TelegramConflictError.
"""
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

os.environ["BOT_TOKEN"] = "123456:TEST-TOKEN-NOT-REAL"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:x@127.0.0.1:5999/x"
os.environ["ADMIN_IDS"] = "111,222"
os.environ["EARLYBIRD_DEADLINE"] = "2026-09-03"
os.environ["COURSE_START"] = "2026-09-10"
os.environ["WEBINAR_AT"] = "2026-08-27T18:00:00+03:00"
os.environ["OPENROUTER_API_KEY"] = ""

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import get_settings
from handlers import admin, audit, audit_admin, booking, common, diagnostic, offer, start, webinar
from services import webinar as svc
from services.analytics import format_sources
from texts import audit as audit_texts

failures = []


def check(label, cond, detail=""):
    print(f"{'OK  ' if cond else 'FAIL'}  {label}{('  — ' + str(detail)) if detail else ''}")
    if not cond:
        failures.append(label)


# 1. Роутеры собираются без конфликта имён/фильтров
dp = Dispatcher(storage=MemoryStorage())
for r in (admin, audit_admin, start, diagnostic, audit, webinar, offer, booking, common):
    dp.include_router(r.router)
check("Dispatcher собран со всеми роутерами", True)

# 2. Время эфира и его производные
s = get_settings()
check("WEBINAR_AT tz-aware", s.webinar_at.tzinfo is not None, s.webinar_at)
check("18:00 МСК == 15:00 UTC", s.webinar_at.astimezone(timezone.utc).hour == 15,
      s.webinar_at.astimezone(timezone.utc))
check("20:00 Алматы", "20:00 Алматы" in svc.human_when(), svc.human_when())
check("чт 27 августа", svc.human_when().startswith("чт 27 августа"), svc.human_when())
check("webinar_key = 2026-08-27", svc.webinar_key() == "2026-08-27", svc.webinar_key())

# 3. Стадии напоминаний — время каждой
expected = {
    1: datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc),
    2: datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc),
    3: datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc),
}
for stage, delta, _t, _j in svc.STAGES:
    got = svc.stage_time(delta)
    check(f"стадия {stage} наступает вовремя", got == expected[stage], f"{got} vs {expected[stage]}")

# 4. Клэмпинг: регистрация в разные моменты берёт следующую БУДУЩУЮ стадию
cases = [
    ("за неделю до (20.08)", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc), 1),
    ("после -3d, до -1d (25.08)", datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc), 2),
    ("в день эфира утром (27.08 08:00 UTC)", datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc), 3),
    ("за 30 мин до начала", datetime(2026, 8, 27, 14, 30, tzinfo=timezone.utc), svc.STAGE_DONE),
]
for label, now, want in cases:
    stage, at = svc.next_stage_after(now)
    check(f"клэмпинг: {label} → стадия {want}", stage == want, f"got stage={stage} at={at}")
    if stage != svc.STAGE_DONE:
        check(f"  и время в будущем ({label})", at > now, at)

# 5. is_over
check("до эфира — регистрация открыта",
      not svc.is_over(datetime(2026, 8, 27, 14, 59, tzinfo=timezone.utc)))
check("после старта — закрыта",
      svc.is_over(datetime(2026, 8, 27, 15, 1, tzinfo=timezone.utc)))

# 6. Промпт собирается и помечает пропуски
p = audit_texts.build_user_prompt("тестовая идея", {"q1": "клиент", "q3": "платит сам"})
check("build_user_prompt: есть ответ", "клиент" in p)
check("build_user_prompt: пропуск помечен", p.count("(не ответил)") == 3, p.count("(не ответил)"))

# 7. Форматтер /sources: пустой период и null-метка
empty = format_sources({"days": 7, "since": datetime(2026, 8, 3, tzinfo=timezone.utc), "rows": []})
check("/sources: пустой период не падает", "ни одного /start" in empty)
filled = format_sources({
    "days": 30,
    "since": datetime(2026, 7, 11, tzinfo=timezone.utc),
    "rows": [
        {"source": "li", "starts": 12, "people": 9, "audits": 3, "regs": 5},
        {"source": None, "starts": 4, "people": 4, "audits": 0, "regs": 1},
    ],
})
check("/sources: null-метка подписана", "без метки" in filled)
check("/sources: итог посчитан", "Итого:</b> 16 стартов, 13 человек" in filled)

# 8. Тексты форматируются без KeyError
from texts import webinar as wt
for name in ("WEBINAR_PITCH", "WEBINAR_ALREADY_REGISTERED", "REMINDER_3D", "REMINDER_1D", "REMINDER_1H"):
    try:
        svc.fmt(getattr(wt, name))
        check(f"текст {name} форматируется", True)
    except Exception as exc:
        check(f"текст {name} форматируется", False, exc)
try:
    svc.fmt(wt.WEBINAR_CONFIRMED, name="Дима")
    check("текст WEBINAR_CONFIRMED форматируется", True)
except Exception as exc:
    check("текст WEBINAR_CONFIRMED форматируется", False, exc)

# 9. Ни одна user-facing строка не содержит вбитой руками даты эфира
import re
from texts import messages as mt

HARDCODED = re.compile(r"\d{1,2}\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)")
from texts import messages as mt


def _strings(mod):
    """Все user-facing строки модуля, включая вложенные в dict (RESULT_HEADER)."""
    for nm in dir(mod):
        if nm.startswith("__"):
            continue
        val = getattr(mod, nm)
        if isinstance(val, str):
            yield nm, val
        elif isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, str):
                    yield f"{nm}[{k}]", v


for mod in (wt, audit_texts, mt):
    for nm, val in _strings(mod):
        m = HARDCODED.search(val)
        if m:
            check(f"{mod.__name__}.{nm} без вбитой даты", False, m.group(0))
check("ни в одном тексте нет вбитой руками даты", True)

# WELCOME собирается из конфига и умеет прятать прошедший эфир
w_open = mt.welcome(webinar_date=svc.human_date(), webinar_title=s.webinar_title, webinar_open=True)
w_closed = mt.welcome(webinar_date=svc.human_date(), webinar_title=s.webinar_title, webinar_open=False)
check("human_date = «27 августа»", svc.human_date() == "27 августа", svc.human_date())
check("WELCOME: дата из конфига", "27 августа" in w_open)
check("WELCOME: название эфира из конфига", s.webinar_title in w_open)
check("WELCOME: после эфира строка про него исчезает", "эфир" not in w_closed.lower(), w_closed)
check("WELCOME: аудит остаётся всегда", "Разобрать твою идею" in w_closed)

# CTA под вердиктом тоже параметризован
cta = audit_texts.AUDIT_VERDICT_CTA.format(webinar_date=svc.human_date(), webinar_title=s.webinar_title)
check("CTA: дата подставляется", "27 августа" in cta)

# 10. Кнопка вебинара уходит из меню после эфира
from keyboards.inline import welcome_kb
open_btns = [b.text for row in welcome_kb(webinar_open=True).inline_keyboard for b in row]
closed_btns = [b.text for row in welcome_kb(webinar_open=False).inline_keyboard for b in row]
check("меню до эфира: 3 кнопки", len(open_btns) == 3, open_btns)
check("меню после эфира: без вебинара", len(closed_btns) == 2 and not any("вебинар" in b for b in closed_btns), closed_btns)

# 11. Даты сентябрьского потока приезжают из конфига во все тексты
from services import funnel

check("демо-день = старт + 8 недель", funnel.demo_day().isoformat() == "2026-11-05", funnel.demo_day())
cd = funnel.course_dates()
check("course_start = «10 сентября»", cd["course_start"] == "10 сентября", cd)
check("eb_deadline = «3 сентября»", cd["eb_deadline"] == "3 сентября", cd)
check("demo_day = «5 ноября»", cd["demo_day"] == "5 ноября", cd)

for nm in ("WARMING_3", "WARMING_COMBINED", "PUSH_EARLYBIRD_CLOSING",
           "PUSH_POST_EARLYBIRD", "PUSH_LAST_CALL", "OFFER_EB_WARNING"):
    try:
        out = funnel.render(getattr(mt, nm))
        check(f"{nm} рендерится без KeyError", "{" not in out, out[:80])
    except Exception as exc:
        check(f"{nm} рендерится без KeyError", False, exc)

for seg in ("marketer", "ops", "product"):
    try:
        funnel.render(mt.RESULT_HEADER[seg])
        check(f"RESULT_HEADER[{seg}] рендерится", True)
    except Exception as exc:
        check(f"RESULT_HEADER[{seg}] рендерится", False, exc)

check("июньские даты выветрились из прогрева",
      "13 августа" not in funnel.render(mt.WARMING_3)
      and "5 ноября" in funnel.render(mt.WARMING_3))
check("оффер больше не «первый поток»", "первого потока" not in mt.OFFER_TEMPLATE)
check("last-call не обещает подорожание", "дороже" not in mt.PUSH_LAST_CALL, mt.PUSH_LAST_CALL)

# Оффер целиком: до дедлайна $200 + плашка, после — $300 без плашки
from datetime import date as _date
text_eb, _ = funnel.render_offer(datetime(2026, 9, 1, tzinfo=timezone.utc))
text_post, _ = funnel.render_offer(datetime(2026, 9, 5, tzinfo=timezone.utc))
check("оффер до дедлайна: $200 + дата дедлайна", "$200" in text_eb and "3 сентября" in text_eb)
check("оффер до дедлайна: старт 10 сентября", "10 сентября" in text_eb)
check("оффер после дедлайна: $300 без плашки", "$300" in text_post and "3 сентября" not in text_post)

# 12. Прогрев и броадкасты ожили: с июньскими датами drip_sweep выходил на
#     каждом тике, а все три броадкаста пропускались как прошедшие.
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.broadcasts import register_broadcasts

check("EB-дедлайн ещё впереди → дрип в режиме full",
      funnel.drip_mode(datetime.now(timezone.utc)) == "full",
      funnel.drip_mode(datetime.now(timezone.utc)))
check("EB активен", funnel.is_early_bird_active())
check("старт курса в будущем → guard drip_sweep пропускает",
      datetime.now(timezone.utc).date() < s.course_start, s.course_start)

sched = AsyncIOScheduler(timezone=s.timezone)
register_broadcasts(sched, bot=None)
jobs = {j.id: j.trigger.run_date for j in sched.get_jobs()}
check("все три броадкаста зарегистрированы", len(jobs) == 3, list(jobs))
expected_dates = {
    "push_earlybird_closing": "2026-09-02",   # EB−1
    "push_post_earlybird": "2026-09-04",      # EB+1
    "push_last_call": "2026-09-08",           # старт−2
}
for jid, want in expected_dates.items():
    got = jobs.get(jid)
    check(f"{jid} на {want}", got is not None and got.date().isoformat() == want, got)

print("\n" + ("ВСЁ ЗЕЛЁНОЕ" if not failures else f"ПРОВАЛЫ: {failures}"))
sys.exit(1 if failures else 0)
