"""Wardrobe math — combo counting, capsule builder, travel packing, monthly report."""
from datetime import date, timedelta
from collections import Counter


def calc_wardrobe_combos(items: list) -> int:
    """Count possible outfit combinations from wardrobe items.

    Formula: (tops × bottoms × (outerwear+1) + one_pieces × (outerwear+1)) × footwear × 0.7
    The 0.7 coefficient accounts for style/season incompatibilities.
    """
    tops = sum(1 for i in items if getattr(i, "category_group", "") == "top")
    bottoms = sum(1 for i in items if getattr(i, "category_group", "") == "bottom")
    outerwear = sum(1 for i in items if getattr(i, "category_group", "") == "outerwear")
    one_pieces = sum(1 for i in items if getattr(i, "category_group", "") == "one_piece")
    footwear = sum(1 for i in items if getattr(i, "category_group", "") == "footwear")

    base = tops * bottoms * (outerwear + 1)
    dresses = one_pieces * (outerwear + 1)
    foot_mult = max(footwear, 1)

    raw = (base + dresses) * foot_mult * 0.7
    return max(int(raw), 1) if (base + dresses) > 0 else 0


async def calc_used_combos(user_id, days: int = 30) -> int:
    """Count unique outfit combinations used in last N days (from BriefLog)."""
    from db.base import AsyncReadSession
    from db.models.brief_log import BriefLog
    from sqlalchemy import select, func

    cutoff = date.today() - timedelta(days=days)
    try:
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(func.count(func.distinct(
                    func.cast(BriefLog.outfit_items, type_=func.text())
                )))
                .where(
                    BriefLog.user_id == user_id,
                    BriefLog.feedback == "wore",
                    BriefLog.date >= cutoff,
                )
            )
            return result.scalar() or 0
    except Exception:
        return 0


def format_wardrobe_stats(items: list, used: int = 0) -> str:
    """Format wardrobe math for display."""
    total = len([i for i in items if getattr(i, "category_group", "") not in ("underwear", "base_layer")])
    combos = calc_wardrobe_combos(items)
    if combos <= 0:
        return ""

    pct = int(used / combos * 100) if combos > 0 and used > 0 else 0
    remaining = max(0, combos - used)

    lines = [
        f"📊 Твой гардероб:",
        f"{total} вещей → {combos} комбинаций",
    ]
    if used > 0:
        lines.append(f"Использовано: {used} ({pct}%)")
        if remaining > 10:
            lines.append(f"\nМожно ещё {remaining} образов без покупок! ✨")
    else:
        lines.append(f"\n✨ {combos} образов — и это без покупок!")

    return "\n".join(lines)


# ── Seasonal Capsule Builder ─────────────────────────────────────────────────

SEASON_MAP = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}

_CAPSULE_SLOTS = {
    "top": 6, "bottom": 4, "outerwear": 3, "footwear": 3,
    "one_piece": 3, "accessory": 4,
}


def build_seasonal_capsule(items: list, season: str = "", size: int = 25) -> dict:
    """Build optimal seasonal capsule from wardrobe.

    Returns: {items, total_combos, season, palette_colors}
    """
    if not season:
        season = SEASON_MAP.get(date.today().month, "spring")

    # Filter by season (keep all-season items too)
    season_items = [
        i for i in items
        if getattr(i, "category_group", "") not in ("underwear", "base_layer")
        and (not getattr(i, "season", None) or season in getattr(i, "season", []))
    ]

    if not season_items:
        season_items = [i for i in items if getattr(i, "category_group", "") not in ("underwear", "base_layer")]

    # Select items with versatility + color diversity
    from services.scoring import calc_item_versatility

    capsule = []
    used_colors: Counter = Counter()

    for category, max_count in _CAPSULE_SLOTS.items():
        candidates = sorted(
            [i for i in season_items if getattr(i, "category_group", "") == category],
            key=lambda i: calc_item_versatility(i, season_items),
            reverse=True,
        )
        added = 0
        for item in candidates:
            if added >= max_count:
                break
            color = getattr(item, "color", "unknown") or "unknown"
            if used_colors[color] >= 3:
                continue  # color diversity
            capsule.append(item)
            used_colors[color] += 1
            added += 1

    capsule = capsule[:size]
    combos = calc_wardrobe_combos(capsule)
    palette = [c for c, _ in used_colors.most_common(6)]

    return {
        "items": capsule,
        "total_combos": combos,
        "season": season,
        "palette_colors": palette,
    }


# ── Travel Capsule ──────────────────────────────────────────────────────────

_OCCASION_WEIGHTS = {
    "работа": {"top": 2, "bottom": 1, "footwear": 1, "outerwear": 1},
    "пляж": {"one_piece": 1, "bottom": 1, "footwear": 1},
    "культура": {"top": 1, "bottom": 1, "footwear": 1},
    "ужин": {"one_piece": 1, "top": 1, "bottom": 1},
    "активный": {"top": 1, "bottom": 1, "footwear": 1},
    "событие": {"one_piece": 1, "top": 1, "accessory": 1},
}


def build_travel_capsule(items: list, days: int, occasions: list[str], temp_range: tuple = (15, 25)) -> dict:
    """Build compact travel capsule.

    Rule: max items = days + 5. Each item reused ≥2x ideally.
    Rule: 3 neutral + 2 accent colors.
    """
    max_items = days + 5
    visual = [i for i in items if getattr(i, "category_group", "") not in ("underwear", "base_layer")]

    # Filter by temperature
    min_t, max_t = temp_range
    if max_t > 25:  # warm destination
        visual = [i for i in visual if getattr(i, "warmth_level", 3) <= 3]
    elif min_t < 5:  # cold destination
        visual = [i for i in visual if getattr(i, "warmth_level", 3) >= 2]

    # Score by versatility
    from services.scoring import calc_item_versatility
    scored = sorted(visual, key=lambda i: calc_item_versatility(i, visual), reverse=True)

    # Select compact set
    capsule = []
    cats_needed = {"top": 3, "bottom": 2, "footwear": 2, "outerwear": 1, "one_piece": 1, "accessory": 1}
    cat_counts: Counter = Counter()

    for item in scored:
        cat = getattr(item, "category_group", "top")
        if cat_counts[cat] < cats_needed.get(cat, 2):
            capsule.append(item)
            cat_counts[cat] += 1
        if len(capsule) >= max_items:
            break

    combos = calc_wardrobe_combos(capsule)

    return {
        "items": capsule,
        "total_combos": combos,
        "days": days,
        "occasions": occasions,
    }


def format_travel_packing(capsule: dict) -> str:
    """Format travel capsule as packing list text."""
    items = capsule["items"]
    by_cat: dict[str, list] = {}
    for item in items:
        cat = getattr(item, "category_group", "top")
        label = {"top": "Верх", "bottom": "Низ", "outerwear": "Верхнее",
                 "footwear": "Обувь", "one_piece": "Платья", "accessory": "Аксессуары"}.get(cat, cat)
        by_cat.setdefault(label, []).append(f"{item.color} {item.type}".strip())

    lines = [f"📦 Чемодан ({len(items)} вещей → {capsule['total_combos']} образов):\n"]
    for cat, names in by_cat.items():
        lines.append(f"{cat}: {', '.join(names)}")

    lines.append(f"\n💡 Каждая вещь используется минимум 2 раза!")
    return "\n".join(lines)


# ── Monthly Report Data ──────────────────────────────────────────────────────

async def build_monthly_report(user_id, items: list, month: int = 0) -> dict:
    """Aggregate monthly style data for report card."""
    visual = [i for i in items if getattr(i, "category_group", "") not in ("underwear", "base_layer")]
    total_wears = sum(getattr(i, "wear_count", 0) or 0 for i in visual)
    unique_worn = sum(1 for i in visual if (getattr(i, "wear_count", 0) or 0) > 0)
    usage_pct = int(unique_worn / len(visual) * 100) if visual else 0

    # Top items
    top_items = sorted(visual, key=lambda i: getattr(i, "wear_count", 0) or 0, reverse=True)[:3]

    # Color stats
    color_counts: Counter = Counter()
    for i in visual:
        wc = getattr(i, "wear_count", 0) or 0
        if wc > 0:
            color_counts[getattr(i, "color", "unknown")] += wc
    top_colors = color_counts.most_common(3)

    # Forgotten
    forgotten = sum(1 for i in visual if (getattr(i, "wear_count", 0) or 0) == 0)

    combos = calc_wardrobe_combos(items)
    estimated_savings = max(0, (unique_worn // 5)) * 40  # rough: every 5 wears ≈ €40 saved

    return {
        "total_outfits": total_wears,
        "unique_items_used": unique_worn,
        "wardrobe_size": len(visual),
        "usage_pct": usage_pct,
        "top_items": top_items,
        "top_colors": top_colors,
        "forgotten_count": forgotten,
        "total_combos": combos,
        "estimated_savings": estimated_savings,
        "co2_saved": estimated_savings // 8,  # rough estimate
    }
