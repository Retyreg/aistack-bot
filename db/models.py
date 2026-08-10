from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    # 'bot' (пришёл через /start) | 'landing' (отправил форму с aistackca.com)
    source_type: Mapped[str] = mapped_column(
        String, nullable=False, default="bot", server_default="bot"
    )
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)

    segment: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnostic_answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    diagnostic_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    funnel_stage: Mapped[str] = mapped_column(String, nullable=False, default="new", server_default="new")
    next_touch: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tariff: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_subscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_leads_funnel_subscribed", "funnel_stage", "is_subscribed"),
        Index("ix_leads_next_action_at", "next_action_at"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # /sources: group by meta->>'source' за период (см. analytics.sources_report)
        Index("ix_events_type_created", "event_type", "created_at"),
    )


class AuditRequest(Base):
    """Одна заявка на «Аудит идеи»: ответы юзера → AI-черновик → вердикт.

    Статусы:
      collecting        — идёт опрос, ответы копятся
      pending_approval  — черновик готов и улетел админу, ждём решения
      sent              — вердикт доставлен юзеру (as-is или отредактированный)
      manual            — админ забрал в ручной ответ («отвечу позже»)
      failed            — LLM не ответил; ответы у админа, черновика нет
    """

    __tablename__ = "audit_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)

    idea: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"q1": "...", ..., "q5": "..."} — ключи совпадают с texts.audit.QUESTIONS
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="collecting", server_default="collecting"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_audit_status", "status"),)


class WebinarRegistration(Base):
    """Регистрация на вебинар + позиция в цепочке напоминаний.

    Расписание живёт в БД (next_reminder_stage/next_reminder_at), а не в памяти
    процесса — тот же приём, что у Lead.next_touch/next_action_at. Рестарт бота
    не теряет цепочку; сдвиг стадии коммитится сразу после отправки.
    Стадии — services.webinar.ReminderStage.
    """

    __tablename__ = "webinar_registrations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    # ключ вебинара ('2026-08-27') — чтобы следующий эфир не смешался с этим
    webinar_key: Mapped[str] = mapped_column(String, nullable=False, index=True)

    next_reminder_stage: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )
    next_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_webinar_reg_unique", "telegram_id", "webinar_key", unique=True),
        Index("ix_webinar_reg_due", "next_reminder_at"),
    )
