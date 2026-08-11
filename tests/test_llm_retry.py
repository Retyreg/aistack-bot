"""Повтор на пустой content — вручную, без сети: подменяем session.post."""
import asyncio
import os
import pathlib
import sys

os.environ["BOT_TOKEN"] = "123:T"
os.environ["ADMIN_IDS"] = "1"
os.environ["EARLYBIRD_DEADLINE"] = "2026-09-03"
os.environ["COURSE_START"] = "2026-09-10"
os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-test"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://x@127.0.0.1:1/x"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import services.llm as llm

failures = []


def check(label, cond, detail=""):
    print(f"{'OK  ' if cond else 'FAIL'}  {label}{('  — ' + str(detail)) if detail else ''}")
    if not cond:
        failures.append(label)


async def main():
    real_one_call = llm._one_call  # предыдущие сценарии его подменяют
    calls = {"n": 0}

    # 1. Пусто → повтор → текст
    async def flaky(session, payload, headers):
        calls["n"] += 1
        return "" if calls["n"] == 1 else "вердикт"

    llm._one_call = flaky
    out = await llm.complete("sys", "user")
    check("пустой content → повтор вернул текст", out == "вердикт", out)
    check("ровно две попытки", calls["n"] == 2, calls["n"])

    # 2. Пусто дважды → LLMError, а не бесконечный цикл
    calls["n"] = 0

    async def always_empty(session, payload, headers):
        calls["n"] += 1
        return ""

    llm._one_call = always_empty
    try:
        await llm.complete("sys", "user")
        check("два пустых → LLMError", False, "исключения не было")
    except llm.LLMError as exc:
        check("два пустых → LLMError", "дважды" in str(exc), exc)
    check("больше двух попыток не делаем", calls["n"] == 2, calls["n"])

    # 3. Первая же попытка успешна → второго вызова нет
    calls["n"] = 0

    async def ok(session, payload, headers):
        calls["n"] += 1
        return "сразу"

    llm._one_call = ok
    out = await llm.complete("sys", "user")
    check("успех с первой → одна попытка", out == "сразу" and calls["n"] == 1, calls["n"])

    # 4. HTTP-ошибка не ретраится
    calls["n"] = 0

    async def boom(session, payload, headers):
        calls["n"] += 1
        raise llm.LLMError("OpenRouter HTTP 402: no credits")

    llm._one_call = boom
    try:
        await llm.complete("sys", "user")
        check("HTTP-ошибка пробрасывается", False, "исключения не было")
    except llm.LLMError as exc:
        check("HTTP-ошибка пробрасывается", "402" in str(exc), exc)
    check("на HTTP-ошибке повтора нет", calls["n"] == 1, calls["n"])

    # 5. Без ключа — сразу ошибка, сети не касаемся
    os.environ["OPENROUTER_API_KEY"] = ""
    from config import get_settings

    get_settings.cache_clear()
    try:
        await llm.complete("sys", "user")
        check("без ключа → LLMError", False, "исключения не было")
    except llm.LLMError as exc:
        check("без ключа → LLMError", "OPENROUTER_API_KEY" in str(exc), exc)


    # 6. Обрезка по max_tokens логируется, но черновик не теряется
    import logging

    records = []

    class Catcher(logging.Handler):
        def emit(self, record):
            records.append(record)

    llm._one_call = real_one_call
    llm.logger.addHandler(Catcher())
    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-test"
    get_settings.cache_clear()

    class FakeResp:
        status = 200

        async def text(self):
            return ""

        async def json(self):
            return {
                "choices": [{"finish_reason": "length",
                             "message": {"content": "вердикт обрезан на полусл"}}],
                "usage": {"completion_tokens": 2400,
                          "completion_tokens_details": {"reasoning_tokens": 300}},
            }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def post(self, *a, **kw):
            return FakeResp()

    out = await llm._one_call(FakeSession(), {}, {})
    check("обрезанный черновик всё равно возвращается", out.startswith("вердикт обрезан"), out)
    errs = [r for r in records if r.levelno >= logging.ERROR and "max_tokens" in r.getMessage()]
    check("обрезка попадает в лог как ERROR", len(errs) == 1, [r.getMessage()[:60] for r in records])

    check("дефолтный лимит поднят до 2400", llm.DEFAULT_MAX_TOKENS == 2400, llm.DEFAULT_MAX_TOKENS)

    print("\n" + ("ВСЁ ЗЕЛЁНОЕ" if not failures else f"ПРОВАЛЫ: {failures}"))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
