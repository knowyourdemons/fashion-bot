"""Add bbox column to wardrobe_items.

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wardrobe_items", sa.Column("bbox", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("wardrobe_items", "bbox")
