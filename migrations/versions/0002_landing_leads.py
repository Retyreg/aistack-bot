"""landing lead support: nullable telegram_id, source_type, email, country

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-05

"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("leads", "telegram_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("events", "telegram_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column(
        "leads",
        sa.Column("source_type", sa.String(), nullable=False, server_default="bot"),
    )
    op.add_column("leads", sa.Column("email", sa.String(), nullable=True))
    op.add_column("leads", sa.Column("country", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "country")
    op.drop_column("leads", "email")
    op.drop_column("leads", "source_type")
    op.alter_column("events", "telegram_id", existing_type=sa.BigInteger(), nullable=False)
    op.alter_column("leads", "telegram_id", existing_type=sa.BigInteger(), nullable=False)
