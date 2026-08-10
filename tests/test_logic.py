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
os.environ["EARLYBIRD_DEADLINE"] = "2026-09-01"
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
for mod in (wt, audit_texts):
    for nm in dir(mod):
        if nm.startswith("_"):
            continue
        val = getattr(mod, nm)
        if isinstance(val, str) and HARDCODED.search(val):
            check(f"{mod.__name__}.{nm} без вбитой даты", False, HARDCODED.search(val).group(0))
check("тексты вебинара/аудита без вбитых дат", True)

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

print("\n" + ("ВСЁ ЗЕЛЁНОЕ" if not failures else f"ПРОВАЛЫ: {failures}"))
sys.exit(1 if failures else 0)
