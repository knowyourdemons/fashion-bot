"""add collage_file_id to brief_log

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-19 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "brief_log",
        sa.Column("collage_file_id", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brief_log", "collage_file_id")
