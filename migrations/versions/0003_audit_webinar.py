"""idea audit requests + webinar registrations + events index

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10

Аддитивная и обратимая: только CREATE TABLE / CREATE INDEX, ни одной колонки
существующих таблиц не трогаем.

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("idea", sa.Text(), nullable=True),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="collecting", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("drafted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_requests_telegram_id", "audit_requests", ["telegram_id"])
    op.create_index("ix_audit_status", "audit_requests", ["status"])

    op.create_table(
        "webinar_registrations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("webinar_key", sa.String(), nullable=False),
        sa.Column("next_reminder_stage", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("next_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webinar_registrations_telegram_id", "webinar_registrations", ["telegram_id"])
    op.create_index("ix_webinar_registrations_webinar_key", "webinar_registrations", ["webinar_key"])
    op.create_index(
        "ix_webinar_reg_unique", "webinar_registrations", ["telegram_id", "webinar_key"], unique=True
    )
    op.create_index("ix_webinar_reg_due", "webinar_registrations", ["next_reminder_at"])

    # /sources гоняет: event_type='start' AND created_at >= now() - interval
    op.create_index("ix_events_type_created", "events", ["event_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_events_type_created", table_name="events")
    op.drop_index("ix_webinar_reg_due", table_name="webinar_registrations")
    op.drop_index("ix_webinar_reg_unique", table_name="webinar_registrations")
    op.drop_index("ix_webinar_registrations_webinar_key", table_name="webinar_registrations")
    op.drop_index("ix_webinar_registrations_telegram_id", table_name="webinar_registrations")
    op.drop_table("webinar_registrations")
    op.drop_index("ix_audit_status", table_name="audit_requests")
    op.drop_index("ix_audit_requests_telegram_id", table_name="audit_requests")
    op.drop_table("audit_requests")
