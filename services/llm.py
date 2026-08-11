"""Один вызов LLM через OpenRouter — черновик вердикта для «Аудита идеи».

Почему не роутер моделей (дешёвая на простое / сильная на сложное, как в
консультационном кейсе): роутить тут нечего. На аудит приходится ровно один
LLM-вызов, и он же — единственный, от которого зависит качество продукта.
Модель вынесена в ``OPENROUTER_MODEL``, так что переключение — правка одной
строки в .env, без кода.

Транспорт — aiohttp: он уже в зависимостях (aiogram тянет его, services/web.py
импортирует напрямую). Отдельный httpx ради одного POST не заводим — билд-гейт
в CI это ``compileall``, недостающая зависимость всплыла бы только в проде.
"""

import logging

import aiohttp

from config import get_settings

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    """Черновик не получен. Вызывающий обязан деградировать, а не падать."""


async def complete(system_prompt: str, user_prompt: str, *, max_tokens: int = 1200) -> str:
    """Вернуть текст ответа модели или бросить LLMError.

    Один повтор — и только на пустой content. Это не гипотетика: на проде
    10.08 из трёх пробных вызовов один вернул HTTP 200 с ``content: null``
    (finish_reason=stop, никакой ошибки), два следующих отработали штатно.
    Без повтора такой аудит уходил бы админу писать руками на ровном месте.

    На сетевых ошибках и не-200 повторов нет: там либо лежит провайдер, либо
    кончились кредиты, и второй заход только задержит уведомление админу.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY не задан")

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # OpenRouter просит их для атрибуции трафика в дашборде.
        "HTTP-Referer": settings.landing_url,
        "X-Title": "AIstack idea audit",
    }
    timeout = aiohttp.ClientTimeout(total=settings.openrouter_timeout_seconds)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in (1, 2):
            text = await _one_call(session, payload, headers)
            if text:
                return text
            logger.warning(
                "OpenRouter вернул пустой content (попытка %s/2, модель %s)",
                attempt,
                settings.openrouter_model,
            )

    raise LLMError("OpenRouter дважды вернул пустой content")


async def _one_call(session: aiohttp.ClientSession, payload: dict, headers: dict) -> str:
    """Один POST. Возвращает текст или пустую строку; на ошибках — LLMError."""
    try:
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise LLMError(f"OpenRouter HTTP {resp.status}: {body[:400]}")
            data = await resp.json()
    except LLMError:
        raise
    except Exception as exc:  # сеть, таймаут, кривой JSON
        raise LLMError(f"OpenRouter недоступен: {exc}") from exc

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Неожиданный ответ OpenRouter: {str(data)[:400]}") from exc

    return (text or "").strip()
