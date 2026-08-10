"""Агрегаты для /stats, /lead и /sources."""

import html
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from db.models import AuditRequest, Event, Lead, WebinarRegistration
from db.session import SessionLocal

_STAGES = ("new", "diagnostic_done", "warming", "offered", "booked", "paid", "lost")
_EVENT_FUNNEL = (
    ("start", "start"),
    ("diagnostic_complete", "diagnostic"),
    ("offer_shown", "offer shown"),
    ("booked", "booked"),
    ("paid", "paid"),
)


async def funnel_snapshot() -> dict:
    """Срез воронки: total, по стадиям, по событиям (уникальные telegram_id),
    разбивка по segment и source.
    """
    out: dict = {}
    async with SessionLocal() as session:
        out["total"] = await session.scalar(select(func.count(Lead.id))) or 0

        stage_rows = (
            await session.execute(
                select(Lead.funnel_stage, func.count(Lead.id)).group_by(Lead.funnel_stage)
            )
        ).all()
        by_stage = {s: 0 for s in _STAGES}
        for stage, cnt in stage_rows:
            by_stage[stage or "?"] = cnt
        out["by_stage"] = by_stage

        events_out: list[tuple[str, str, int]] = []
        for et, label in _EVENT_FUNNEL:
            cnt = await session.scalar(
                select(func.count(func.distinct(Event.telegram_id))).where(Event.event_type == et)
            )
            events_out.append((et, label, cnt or 0))
        out["events"] = events_out

        seg_rows = (
            await session.execute(
                select(Lead.segment, func.count(Lead.id))
                .where(Lead.segment.is_not(None))
                .group_by(Lead.segment)
            )
        ).all()
        out["by_segment"] = {seg: cnt for seg, cnt in seg_rows}

        src_rows = (
            await session.execute(
                select(Lead.source, func.count(Lead.id))
                .group_by(Lead.source)
                .order_by(func.count(Lead.id).desc())
                .limit(10)
            )
        ).all()
        out["by_source"] = [((src or "—"), cnt) for src, cnt in src_rows]

        out["subscribed"] = await session.scalar(
            select(func.count(Lead.id)).where(Lead.is_subscribed.is_(True))
        ) or 0

    return out


def format_stats(snap: dict) -> str:
    """HTML-форматированный /stats для админа."""
    lines: list[str] = []
    lines.append("📊 <b>Воронка AIstack-bot</b>")
    lines.append(f"\nВсего лидов: <b>{snap['total']}</b>  ·  подписаны: {snap['subscribed']}")

    lines.append("\n<b>По стадиям</b>")
    for stage in _STAGES:
        cnt = snap["by_stage"].get(stage, 0)
        if cnt:
            lines.append(f"  {stage}: {cnt}")

    lines.append("\n<b>Воронка событий</b>")
    base = next((c for _, _, c in snap["events"] if _ == "start"), 0)
    prev = None
    for et, label, cnt in snap["events"]:
        pct_total = f"{cnt * 100 // base}%" if base else "—"
        pct_prev = ""
        if prev is not None and prev > 0:
            pct_prev = f"  ({cnt * 100 // prev}% от пред.)"
        lines.append(f"  {label}: {cnt}  ({pct_total} от старта){pct_prev}")
        prev = cnt

    if snap["by_segment"]:
        lines.append("\n<b>По сегментам</b>")
        for seg, cnt in sorted(snap["by_segment"].items(), key=lambda x: -x[1]):
            lines.append(f"  {seg}: {cnt}")

    if snap["by_source"]:
        lines.append("\n<b>По источникам</b>")
        for src, cnt in snap["by_source"]:
            lines.append(f"  {src}: {cnt}")

    return "\n".join(lines)


# ─── /sources: стартов бота по источникам за период ────────────────────────
#
# Считаем по events, а НЕ по leads.source. Разница принципиальная:
# leads.source — first-touch и навсегда (handlers/start.py пишет его только
# если он ещё пустой), так что по нему нельзя ответить «сколько стартов с
# li за прошлую неделю». А events пишет каждый /start вместе с тем
# start-параметром, с которым человек пришёл именно в этот раз.
#
# «Стартов» — это события. «Людей» — уникальные telegram_id: один человек
# может нажать /start пять раз, и для оценки посева важны обе цифры.

NO_SOURCE_LABEL = "(без метки · direct)"


async def sources_report(days: int) -> dict:
    """Разбивка стартов бота по start-параметру за последние ``days`` суток."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    source_expr = Event.meta["source"].astext

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    source_expr.label("source"),
                    func.count(Event.id).label("starts"),
                    func.count(func.distinct(Event.telegram_id)).label("people"),
                )
                .where(Event.event_type == "start", Event.created_at >= since)
                .group_by(source_expr)
                .order_by(func.count(Event.id).desc())
            )
        ).all()

        # Что источники дали дальше по воронке — по тем же меткам.
        audits = dict(
            (
                await session.execute(
                    select(AuditRequest.source, func.count(AuditRequest.id))
                    .where(AuditRequest.created_at >= since)
                    .group_by(AuditRequest.source)
                )
            ).all()
        )
        regs = dict(
            (
                await session.execute(
                    select(WebinarRegistration.source, func.count(WebinarRegistration.id))
                    .where(WebinarRegistration.created_at >= since)
                    .group_by(WebinarRegistration.source)
                )
            ).all()
        )

    return {
        "days": days,
        "since": since,
        "rows": [
            {
                "source": src,
                "starts": starts,
                "people": people,
                "audits": audits.get(src, 0),
                "regs": regs.get(src, 0),
            }
            for src, starts, people in rows
        ],
    }


def format_sources(report: dict) -> str:
    """HTML-таблица для /sources. Ничего не отбрасываем — все метки видны."""
    rows = report["rows"]
    lines = [
        f"📈 <b>Старты бота по источникам</b> · за {report['days']} дн.",
        f"<i>с {report['since']:%d.%m.%Y %H:%M} UTC</i>",
    ]
    if not rows:
        lines.append("\nЗа период ни одного /start.")
        return "\n".join(lines)

    total_starts = sum(r["starts"] for r in rows)
    total_people = sum(r["people"] for r in rows)

    lines.append("\n<code>источник · стартов · людей · аудитов · вебинар</code>")
    for row in rows:
        label = html.escape(row["source"]) if row["source"] else NO_SOURCE_LABEL
        lines.append(
            f"  <b>{label}</b> · {row['starts']} · {row['people']} · "
            f"{row['audits']} · {row['regs']}"
        )

    lines.append(f"\n<b>Итого:</b> {total_starts} стартов, {total_people} человек")
    lines.append(
        "\n<i>«Стартов» — нажатий /start (один человек может несколько раз). "
        "«Людей» — уникальных. Аудиты и вебинар — по метке того же лида.</i>"
    )
    return "\n".join(lines)
