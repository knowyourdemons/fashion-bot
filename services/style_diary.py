"""Style Diary — wear data aggregation and weekly insights.

Provides 4 rotating insight types for Monday morning briefs:
  Week 1: Color dominance ("ты носишь синий 60%")
  Week 2: Favorites ("твои фавориты месяца")
  Week 3: Orphans ("N вещей ждут своего часа")
  Week 4: Progress ("X образов из Y вещей")
"""
import structlog
from collections import Counter
from datetime import date, timedelta

logger = structlog.get_logger()

_CONTRAST_COLORS = {
    "синий": "горчичный", "чёрный": "белый", "серый": "бордовый",
    "белый": "тёмно-синий", "бежевый": "бирюзовый", "коричневый": "голубой",
    "розовый": "оливковый", "зелёный": "коралловый", "красный": "серый",
}


async def get_wear_insights(user_id, items: list, days: int = 30) -> dict:
    """Aggregate wear data from wardrobe items (not BriefLog — simpler)."""
    today = date.today()

    color_counts: Counter = Counter()
    category_counts: Counter = Counter()
    favorites: list = []
    orphans: list = []

    for item in items:
        if getattr(item, "category_group", "") in ("underwear", "base_layer"):
            continue
        color = getattr(item, "color", "") or "unknown"
        wc = getattr(item, "wear_count", 0) or 0
        last = getattr(item, "last_worn", None)

        color_counts[color] += wc
        category_counts[getattr(item, "category_group", "top")] += wc

        if wc >= 3:
            favorites.append(item)

        if last is None or (today - last).days > 30:
            if wc == 0:
                orphans.append(item)

    total_wears = sum(color_counts.values())
    top_color = color_counts.most_common(1)[0] if color_counts else None
    top_color_pct = int(top_color[1] / total_wears * 100) if top_color and total_wears > 0 else 0

    visual_items = [i for i in items if getattr(i, "category_group", "") not in ("underwear", "base_layer")]
    unique_worn = sum(1 for i in visual_items if (getattr(i, "wear_count", 0) or 0) > 0)
    usage_pct = int(unique_worn / len(visual_items) * 100) if visual_items else 0

    return {
        "top_color": top_color[0] if top_color else None,
        "top_color_pct": top_color_pct,
        "total_wears": total_wears,
        "unique_worn": unique_worn,
        "total_visual": len(visual_items),
        "usage_pct": usage_pct,
        "favorites": favorites[:5],
        "orphans": orphans[:5],
    }


def format_weekly_insight(insights: dict, week_num: int) -> str | None:
    """Format insight based on week rotation (0-3)."""
    insight_type = week_num % 4

    if insights["total_wears"] < 5:
        return None  # not enough data

    if insight_type == 0 and insights["top_color"]:
        contrast = _CONTRAST_COLORS.get(insights["top_color"], "яркий акцент")
        return (
            f"📊 Кстати: за месяц ты носишь {insights['top_color']} "
            f"{insights['top_color_pct']}% времени. "
            f"Попробуй {contrast} для свежести!"
        )
    elif insight_type == 1 and insights["favorites"]:
        names = ", ".join(f"{i.type} {i.color}" for i in insights["favorites"][:3])
        return f"📊 Твои фавориты месяца: {names}. Надёжная база!"
    elif insight_type == 2 and insights["orphans"]:
        orphan = insights["orphans"][0]
        days = 30
        if getattr(orphan, "last_worn", None):
            days = (date.today() - orphan.last_worn).days
        return (
            f"📊 {len(insights['orphans'])} вещей ждут своего часа! "
            f"{orphan.type} {orphan.color} — {days} дней без дела. Сегодня? 💎"
        )
    elif insight_type == 3:
        return (
            f"📊 За месяц: {insights['total_wears']} раз надевала из "
            f"{insights['unique_worn']} вещей. "
            f"Ты используешь {insights['usage_pct']}% гардероба!"
        )

    return None
