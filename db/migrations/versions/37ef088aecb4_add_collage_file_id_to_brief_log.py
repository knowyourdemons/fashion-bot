"""add_collage_file_id_to_brief_log

Revision ID: 37ef088aecb4
Revises: b2c3d4e5f6a7
Create Date: 2026-03-19 15:11:16.999372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '37ef088aecb4'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('brief_log', sa.Column('collage_file_id', sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column('brief_log', 'collage_file_id')
