"""HTTP-эндпоинт /api/lead — приём заявок с aistackca.com.

aiohttp Application запускается в том же asyncio loop, что и polling.
Биндится на 0.0.0.0:WEBHOOK_PORT, авторизация — X-Webhook-Secret header.
TLS не предусмотрен — рассчитан на server-to-server в доверенной сети
(landing-сервер 78.140.246.150 → bot-сервер 185.115.33.211).

Payload (JSON):
    {
      "name": str,
      "phone": str,
      "email": str,
      "country": str,
      "tariff": "self" | "supported" | "personal",
      "source": str | null,       # обычно "landing_form" или UTM source
      "utm": dict | null,         # UTM-параметры landing-запроса
    }

Поведение:
- Любая успешная заявка → insert в leads (telegram_id=NULL, source_type='landing',
  funnel_stage='booked', is_subscribed=False — без telegram_id писать всё равно
  не сможем), event 'landing_form_submitted', уведомление автору в Telegram.
- Дедуп НЕТ — каждый submit = новая запись (админ дедуплицирует руками).
"""

import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiohttp import web

from config import get_settings
from db.models import Event, Lead
from db.session import get_session
from services.notify import send_admin
from texts import messages

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("name", "phone", "email", "country", "tariff")


async def handle_lead(request: web.Request) -> web.Response:
    settings = get_settings()
    secret_header = request.headers.get("X-Webhook-Secret", "")
    if not settings.webhook_secret or secret_header != settings.webhook_secret:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)

    missing = [f for f in REQUIRED_FIELDS if not payload.get(f)]
    if missing:
        return web.json_response(
            {"error": "missing_fields", "fields": missing}, status=422
        )

    name = str(payload["name"]).strip()[:200]
    phone = str(payload["phone"]).strip()[:50]
    email = str(payload["email"]).strip()[:200]
    country = str(payload["country"]).strip()[:20]
    tariff = str(payload["tariff"]).strip()[:20]
    source = (payload.get("source") or "landing_form")[:200]
    utm = payload.get("utm") or {}

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        lead = Lead(
            telegram_id=None,
            source_type="landing",
            source=source,
            contact_name=name,
            contact_phone=phone,
            email=email,
            country=country,
            tariff=tariff,
            funnel_stage="booked",
            booked_at=now,
            is_subscribed=False,
        )
        session.add(lead)
        await session.flush()
        session.add(
            Event(
                telegram_id=None,
                event_type="landing_form_submitted",
                meta={
                    "lead_id": lead.id,
                    "tariff": tariff,
                    "source": source,
                    "utm": utm,
                },
            )
        )
        # Дублирующий 'booked' для event-based funnel в /stats.
        # services/analytics.funnel_snapshot считает distinct по telegram_id,
        # поэтому landing-лиды (telegram_id=NULL) приземляются как одна группа.
        # Достаточно, чтобы у landing-лида был такой же тип event'а, как у бот-лидов.
        session.add(
            Event(
                telegram_id=None,
                event_type="booked",
                meta={"lead_id": lead.id, "tariff": tariff, "via": "landing"},
            )
        )
        lead_id = lead.id

    bot: Bot = request.app["bot"]
    admin_text = messages.ADMIN_NEW_LANDING_LEAD.format(
        tariff=messages.TARIFF_NAMES.get(tariff, tariff),
        name=name,
        phone=phone,
        email=email,
        country=country,
        source=source,
    )
    try:
        await send_admin(bot, admin_text)
    except Exception:
        logger.exception("failed to send admin notification for landing lead %s", lead_id)

    logger.info("landing lead %s saved (tariff=%s, source=%s)", lead_id, tariff, source)
    return web.json_response({"ok": True, "lead_id": lead_id})


async def healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def create_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/api/lead", handle_lead)
    app.router.add_get("/health", healthcheck)
    return app
