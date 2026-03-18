"""add role to wardrobe_items

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wardrobe_items",
        sa.Column("role", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wardrobe_items", "role")
