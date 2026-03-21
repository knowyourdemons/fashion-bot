"""add milestones_reached to users

Revision ID: e5f6a7b8c9d0
Revises: 27b53b86727f
Create Date: 2026-03-21 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = '27b53b86727f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('milestones_reached', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'milestones_reached')
