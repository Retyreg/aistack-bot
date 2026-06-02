"""initial: leads, events

Revision ID: 0001
Revises:
Create Date: 2026-06-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("segment", sa.String(), nullable=True),
        sa.Column("diagnostic_answers", postgresql.JSONB(), nullable=True),
        sa.Column("diagnostic_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funnel_stage", sa.String(), nullable=False, server_default="new"),
        sa.Column("next_touch", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_touch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tariff", sa.String(), nullable=True),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("contact_phone", sa.String(), nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_subscribed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_leads_telegram_id", "leads", ["telegram_id"], unique=True)
    op.create_index("ix_leads_funnel_subscribed", "leads", ["funnel_stage", "is_subscribed"])
    op.create_index("ix_leads_next_action_at", "leads", ["next_action_at"])

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_events_telegram_id", "events", ["telegram_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_telegram_id", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_leads_next_action_at", table_name="leads")
    op.drop_index("ix_leads_funnel_subscribed", table_name="leads")
    op.drop_index("ix_leads_telegram_id", table_name="leads")
    op.drop_table("leads")
