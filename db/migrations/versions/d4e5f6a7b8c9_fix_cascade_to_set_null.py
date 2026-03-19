"""fix cascade to set null on log tables

Soft-deleted users should not hard-delete their logs.
Change CASCADE → SET NULL on brief_log, outfit_log, events.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-19 23:30:00.000000

"""
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

_TABLES = ["brief_log", "outfit_log", "events"]


def upgrade() -> None:
    for table in _TABLES:
        # Drop old FK with CASCADE
        op.drop_constraint(f"{table}_user_id_fkey", table, type_="foreignkey")
        # Recreate with SET NULL
        op.create_foreign_key(
            f"{table}_user_id_fkey",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_constraint(f"{table}_user_id_fkey", table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_user_id_fkey",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
