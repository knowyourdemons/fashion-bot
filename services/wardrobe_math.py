"""Wardrobe math — combo counting and usage stats."""
from datetime import date, timedelta


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
