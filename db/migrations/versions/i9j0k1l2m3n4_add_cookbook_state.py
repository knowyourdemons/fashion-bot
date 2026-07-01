"""Add cookbook_state table for multi-device sync.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-07-01 09:00:00.000000

One row per (tg_id, key); `value` is the whole per-key blob written by the
frontend Store.save, `rev` is the client Date.now() ms (last-write-wins clock).
Standalone table — no FKs to fashion-bot tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cookbook_state",
        sa.Column("tg_id", sa.String(32), nullable=False),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rev", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tg_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("cookbook_state")
