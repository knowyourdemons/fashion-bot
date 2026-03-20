"""add_trimester_due_date_to_users

Revision ID: 27b53b86727f
Revises: d4e5f6a7b8c9
Create Date: 2026-03-20 08:23:25.217613
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '27b53b86727f'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('trimester', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('due_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'due_date')
    op.drop_column('users', 'trimester')
