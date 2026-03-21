"""Add warmth_level, style_tag, rain_ok to wardrobe_items.

Backfill existing items by type keyword matching.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns
    op.add_column("wardrobe_items", sa.Column("warmth_level", sa.SmallInteger(), nullable=True))
    op.add_column("wardrobe_items", sa.Column("style_tag", sa.String(32), nullable=True))
    op.add_column("wardrobe_items", sa.Column("rain_ok", sa.Boolean(), nullable=True, server_default="false"))

    # Backfill warmth_level by type keyword
    # warmth 1: very light
    op.execute("""
        UPDATE wardrobe_items SET warmth_level = 1
        WHERE warmth_level IS NULL AND (
            type ILIKE '%футболк%' OR type ILIKE '%майк%' OR type ILIKE '%топ%'
            OR type ILIKE '%шорт%' OR type ILIKE '%сандал%' OR type ILIKE '%босонож%'
            OR type ILIKE '%панам%' OR type ILIKE '%сарафан%' OR type ILIKE '%ромпер%'
        )
    """)
    # warmth 2: light
    op.execute("""
        UPDATE wardrobe_items SET warmth_level = 2
        WHERE warmth_level IS NULL AND (
            type ILIKE '%лонгслив%' OR type ILIKE '%рубаш%' OR type ILIKE '%блузк%'
            OR type ILIKE '%юбк%' OR type ILIKE '%кроссовк%' OR type ILIKE '%туфл%'
            OR type ILIKE '%кепк%' OR type ILIKE '%ветровк%' OR type ILIKE '%кед%'
            OR type ILIKE '%балетк%'
        )
    """)
    # warmth 4: warm
    op.execute("""
        UPDATE wardrobe_items SET warmth_level = 4
        WHERE warmth_level IS NULL AND (
            type ILIKE '%свитер%' OR type ILIKE '%водолазк%' OR type ILIKE '%толстовк%'
            OR type ILIKE '%куртк%' OR type ILIKE '%пальто%' OR type ILIKE '%сапог%'
            OR type ILIKE '%шапк%' OR type ILIKE '%шарф%' OR type ILIKE '%перчатк%'
            OR type ILIKE '%варежк%' OR type ILIKE '%плащ%'
        )
    """)
    # warmth 5: very warm
    op.execute("""
        UPDATE wardrobe_items SET warmth_level = 5
        WHERE warmth_level IS NULL AND (
            type ILIKE '%пуховик%' OR type ILIKE '%зимн%' OR type ILIKE '%угги%'
            OR type ILIKE '%термо%' OR type ILIKE '%балаклав%' OR type ILIKE '%дублёнк%'
        )
    """)
    # warmth 3: medium (everything else)
    op.execute("""
        UPDATE wardrobe_items SET warmth_level = 3
        WHERE warmth_level IS NULL
    """)

    # Backfill style_tag from existing style column
    op.execute("UPDATE wardrobe_items SET style_tag = 'casual' WHERE style = 'повседневный'")
    op.execute("UPDATE wardrobe_items SET style_tag = 'sport' WHERE style = 'спортивный'")
    op.execute("UPDATE wardrobe_items SET style_tag = 'formal' WHERE style = 'нарядный'")
    op.execute("UPDATE wardrobe_items SET style_tag = 'home' WHERE style = 'домашний'")
    op.execute("UPDATE wardrobe_items SET style_tag = 'casual' WHERE style_tag IS NULL")

    # Backfill rain_ok
    op.execute("""
        UPDATE wardrobe_items SET rain_ok = true
        WHERE type ILIKE '%дождевик%' OR type ILIKE '%резинов%'
            OR type ILIKE '%непромокаем%' OR type ILIKE '%мембран%'
    """)


def downgrade() -> None:
    op.drop_column("wardrobe_items", "rain_ok")
    op.drop_column("wardrobe_items", "style_tag")
    op.drop_column("wardrobe_items", "warmth_level")
