"""Progressive preference learning from outfit feedback."""
import json
from collections import Counter
from datetime import date, timedelta

import structlog
from core.redis import get_redis

logger = structlog.get_logger()

CACHE_TTL = 86400  # 24h


async def build_user_preferences(user_id: str) -> dict:
    """Build preference profile from 60 days of feedback history."""
    # Check Redis cache first
    redis = get_redis()
    cache_key = f"preferences:{user_id}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached if isinstance(cached, str) else cached.decode())

    from db.base import AsyncReadSession
    from db.models.brief_log import BriefLog
    from db.models.wardrobe import WardrobeItem
    from sqlalchemy import select
    import uuid as _uuid

    cutoff = date.today() - timedelta(days=60)

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(BriefLog).where(
                BriefLog.user_id == _uuid.UUID(user_id) if isinstance(user_id, str) else BriefLog.user_id == user_id,
                BriefLog.date >= cutoff,
                BriefLog.outfit_items.isnot(None),
            ).order_by(BriefLog.date.desc())
        )
        logs = list(result.scalars().all())

    prefs = {
        "liked_colors": {},
        "disliked_colors": {},
        "liked_types": {},
        "liked_formality": {},
        "avoid_items": [],
        "total_feedback": len(logs),
        "wore_rate": 0.0,
        "top_combo": None,
    }

    liked_colors = Counter()
    disliked_colors = Counter()
    liked_types = Counter()
    liked_formality = Counter()
    item_reroll = Counter()
    wore = 0

    # Batch-fetch ALL referenced items to avoid N+1 queries
    all_item_ids = set()
    for log in logs:
        for iid in (log.outfit_items or []):
            all_item_ids.add(_uuid.UUID(iid) if isinstance(iid, str) else iid)

    items_by_id = {}
    if all_item_ids:
        try:
            async with AsyncReadSession() as s:
                items_result = await s.execute(
                    select(WardrobeItem).where(
                        WardrobeItem.id.in_(list(all_item_ids))
                    )
                )
                for item in items_result.scalars().all():
                    items_by_id[str(item.id)] = item
        except Exception:
            pass

    for log in logs:
        item_ids = log.outfit_items or []
        if not item_ids:
            continue

        items = [items_by_id[str(_uuid.UUID(i) if isinstance(i, str) else i)]
                 for i in item_ids
                 if str(_uuid.UUID(i) if isinstance(i, str) else i) in items_by_id]

        is_wore = log.feedback in ("up", "wore", "надели", "надела")
        is_reroll = log.feedback in ("down", "reroll", "другой")

        if is_wore:
            wore += 1
            for item in items:
                liked_colors[item.color or ""] += 1
                liked_types[item.type or ""] += 1
                fl = getattr(item, "formality_level", None)
                if fl:
                    liked_formality[fl] += 1
        elif is_reroll:
            for item in items:
                disliked_colors[item.color or ""] += 1
            for iid in item_ids:
                item_reroll[str(iid)] += 1

    prefs["liked_colors"] = dict(liked_colors.most_common(5))
    prefs["disliked_colors"] = dict(disliked_colors.most_common(3))
    prefs["liked_types"] = dict(liked_types.most_common(5))
    prefs["liked_formality"] = dict(liked_formality.most_common(3))
    prefs["avoid_items"] = [iid for iid, cnt in item_reroll.items() if cnt >= 3]
    prefs["total_feedback"] = len(logs)
    prefs["wore_rate"] = round(wore / max(len(logs), 1), 2)

    # Cache
    try:
        await redis.set(cache_key, json.dumps(prefs), ex=CACHE_TTL)
    except Exception:
        pass

    return prefs


async def invalidate_preferences(user_id: str):
    """Invalidate cache after new feedback."""
    try:
        redis = get_redis()
        await redis.delete(f"preferences:{user_id}")
    except Exception:
        pass


def get_preference_context(prefs: dict) -> str:
    """Format preferences for AI prompt injection."""
    if prefs.get("total_feedback", 0) < 3:
        return ""

    lines = []

    lc = prefs.get("liked_colors", {})
    if lc:
        top = list(lc.keys())[:3]
        lines.append(f"Чаще надевает: {', '.join(top)}")

    dc = prefs.get("disliked_colors", {})
    if dc:
        top = list(dc.keys())[:2]
        lines.append(f"Часто отклоняет: {', '.join(top)}")

    avoid = prefs.get("avoid_items", [])
    if avoid:
        lines.append(f"НЕ использовать items: {', '.join(avoid[:5])}")

    lf = prefs.get("liked_formality", {})
    if lf:
        top_f = list(lf.keys())[0]
        lines.append(f"Предпочитает формальность: {top_f}")

    wr = prefs.get("wore_rate", 0.5)
    if wr > 0.7:
        lines.append("Принимает большинство образов — продолжай в том же стиле")
    elif wr < 0.3:
        lines.append("Часто отклоняет — больше разнообразия, пробуй новое")

    return "\n".join(lines)


def calc_kassi_knows_pct(
    prefs: dict,
    wardrobe_size: int,
    has_style_type: bool = False,
    has_colortype: bool = False,
    has_body_type: bool = False,
) -> int:
    """Calculate how well Kassi 'knows' the user (0-100%)."""
    score = 0
    score += min(prefs.get("total_feedback", 0), 30)  # max 30
    score += min(wardrobe_size, 30)                     # max 30
    if has_style_type:
        score += 15
    if has_colortype:
        score += 15
    if has_body_type:
        score += 10
    return min(score, 100)
