"""add critical indexes for scaling

Revision ID: c3d4e5f6a7b8
Revises: 37ef088aecb4
Create Date: 2026-03-19 22:30:00.000000

"""
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "37ef088aecb4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # wardrobe_items: queried on every outfit generation + wardrobe listing
    op.create_index(
        "ix_wardrobe_items_owner",
        "wardrobe_items",
        ["owner_id", "owner_type"],
        postgresql_where="deleted_at IS NULL",
    )

    # children: loaded for every brief + wardrobe handler
    op.create_index(
        "ix_children_user_id",
        "children",
        ["user_id"],
        postgresql_where="deleted_at IS NULL",
    )

    # brief_log: queried per user for history, feedback, engagement checks
    op.create_index(
        "ix_brief_log_user_date",
        "brief_log",
        ["user_id", "date"],
    )

    # outfit_log: queried per user for outfit history
    op.create_index(
        "ix_outfit_log_user_date",
        "outfit_log",
        ["user_id", "date"],
    )

    # events: queried per user for analytics
    op.create_index(
        "ix_events_user_id",
        "events",
        ["user_id"],
    )

    # users: schedule_all() filters active+onboarded users
    op.create_index(
        "ix_users_active_onboarded",
        "users",
        ["is_active", "onboarding_completed"],
        postgresql_where="deleted_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index("ix_users_active_onboarded", "users")
    op.drop_index("ix_events_user_id", "events")
    op.drop_index("ix_outfit_log_user_date", "outfit_log")
    op.drop_index("ix_brief_log_user_date", "brief_log")
    op.drop_index("ix_children_user_id", "children")
    op.drop_index("ix_wardrobe_items_owner", "wardrobe_items")
