"""Add styling axes, i18n, and accessory columns.

Revision ID: h8i9j0k1l2m3
Revises: g7b8c9d0e1f2
Create Date: 2026-03-23 12:00:00.000000

New columns:
- users: language, contrast_level, kibbe_family, style_essence,
         color_flow_to, color_flow_strength, tonal_depth, chroma
- wardrobe_items: formality_level, metal_tone
"""
from alembic import op
import sqlalchemy as sa

revision = "h8i9j0k1l2m3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Users: i18n
    op.add_column("users", sa.Column("language", sa.String(5), server_default="ru"))

    # Users: professional styling axes
    op.add_column("users", sa.Column("contrast_level", sa.String(10), nullable=True))
    op.add_column("users", sa.Column("kibbe_family", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("style_essence", sa.String(20), nullable=True))

    # Users: color depth (16 seasons)
    op.add_column("users", sa.Column("color_flow_to", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("color_flow_strength", sa.Float, nullable=True))
    op.add_column("users", sa.Column("tonal_depth", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("chroma", sa.String(20), nullable=True))

    # Wardrobe items: formality + metal tone
    op.add_column("wardrobe_items", sa.Column("formality_level", sa.SmallInteger, nullable=True))
    op.add_column("wardrobe_items", sa.Column("metal_tone", sa.String(10), nullable=True))

    # Add 'bag' to category_group_enum (idempotent)
    op.execute("ALTER TYPE category_group_enum ADD VALUE IF NOT EXISTS 'bag'")


def downgrade() -> None:
    op.drop_column("wardrobe_items", "metal_tone")
    op.drop_column("wardrobe_items", "formality_level")
    op.drop_column("users", "chroma")
    op.drop_column("users", "tonal_depth")
    op.drop_column("users", "color_flow_strength")
    op.drop_column("users", "color_flow_to")
    op.drop_column("users", "style_essence")
    op.drop_column("users", "kibbe_family")
    op.drop_column("users", "contrast_level")
    op.drop_column("users", "language")
