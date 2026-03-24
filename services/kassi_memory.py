"""Kassi Memory — personal facts for natural comments."""
import json
from datetime import date, timedelta

import structlog
from core.redis import get_redis

logger = structlog.get_logger()

MEMORY_TTL = 90 * 86400  # 90 days
MEMORY_COOLDOWN = 3 * 86400  # Use memory in comments max every 3 days


async def build_memory(user_id: str, prefs: dict, user=None) -> list[str]:
    """Build list of personal facts about user."""
    facts = []

    # From preferences (auto-learned)
    liked = prefs.get("liked_colors", {})
    if liked:
        top_color = list(liked.keys())[0]
        facts.append(f"любимый цвет — {top_color}")

    liked_types = prefs.get("liked_types", {})
    if liked_types:
        top_type = list(liked_types.keys())[0]
        facts.append(f"часто носит {top_type}")

    wr = prefs.get("wore_rate", 0.5)
    if wr > 0.7:
        facts.append("обычно соглашается с предложениями Касси")

    # From user profile
    if user:
        sp = getattr(user, "style_preferences", None) or {}
        if sp.get("style_type"):
            from bot.handlers.style_quiz import STYLE_TYPES
            st = STYLE_TYPES.get(sp["style_type"], {})
            if st:
                facts.append(f"стиль — {st.get('label', sp['style_type'])}")

        if sp.get("avoid"):
            facts.append(f"не любит {', '.join(sp['avoid'][:2])}")

        ct = getattr(user, "colortype", None)
        if ct:
            facts.append(f"цветотип — {ct}")

    # Store in Redis
    try:
        redis = get_redis()
        await redis.set(f"memory:{user_id}", json.dumps(facts, ensure_ascii=False), ex=MEMORY_TTL)
    except Exception:
        pass

    return facts


async def get_memory_for_prompt(user_id: str) -> str:
    """Get memory facts for AI prompt. Rate-limited to every 3 days."""
    redis = get_redis()

    # Rate limit check
    cooldown_key = f"memory_used:{user_id}"
    if await redis.get(cooldown_key):
        return ""  # Used recently

    # Get facts
    raw = await redis.get(f"memory:{user_id}")
    if not raw:
        return ""

    facts = json.loads(raw if isinstance(raw, str) else raw.decode())
    if not facts:
        return ""

    # Mark as used
    await redis.set(cooldown_key, "1", ex=MEMORY_COOLDOWN)

    facts_text = "; ".join(facts[:4])
    return (
        f"Ты ПОМНИШЬ о юзере: {facts_text}.\n"
        "Используй 1 факт естественно в комментарии (не каждый раз):\n"
        '«Знаю что любишь синий — сегодня бирюзовый, похожий но свежее!»\n'
        '«Зелёная кофта вернулась — давно не виделись! 🌿»'
    )


async def save_explicit_memory(user_id: str, fact: str):
    """Save an explicit fact from user chat (e.g., 'не люблю жёлтый')."""
    # Sanitize: strip control chars, limit length
    fact = fact.replace("\n", " ").replace("\r", " ").replace("\x00", "").strip()
    if not fact or len(fact) > 200:
        return
    fact = fact[:200]
    redis = get_redis()
    key = f"memory:{user_id}"
    raw = await redis.get(key)
    facts = json.loads(raw) if raw else []
    if fact not in facts:
        facts.append(fact)
        facts = facts[-10:]  # Keep last 10
        await redis.set(key, json.dumps(facts, ensure_ascii=False), ex=MEMORY_TTL)
