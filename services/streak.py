"""Streak system — daily engagement tracking."""
import json
from datetime import date, timedelta

import structlog
from core.redis import get_redis

logger = structlog.get_logger()

STREAK_TTL = 90 * 86400  # 90 days

MILESTONES = {
    3:  "3 дня подряд! Привычка формируется!",
    7:  "7 дней! Неделя стиля!",
    14: "14 дней! Касси знает тебя на {knows_pct}%!",
    21: "21 день! Привычка закрепилась!",
    30: "30 дней! Месяц стиля!",
    50: "50 дней! Полкалендаря!",
    100: "100 дней! Легенда стиля!",
}


async def update_streak(user_id: str) -> dict:
    """Update streak on brief interaction. Returns streak data."""
    redis = get_redis()
    key = f"streak:{user_id}"
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()

    raw = await redis.get(key)
    if raw:
        streak = json.loads(raw if isinstance(raw, str) else raw.decode())
    else:
        streak = {"current": 0, "best": 0, "last_date": "", "freezes_left": 1}

    # Clamp freezes_left to valid range [0, 1]
    streak["freezes_left"] = max(0, min(1, streak.get("freezes_left", 1)))

    if streak["last_date"] == today:
        return streak  # Already counted today

    if streak["last_date"] == yesterday:
        # Consecutive day
        streak["current"] += 1
    elif streak["last_date"] == two_days_ago and streak.get("freezes_left", 0) > 0:
        # Freeze: skip 1 day allowed
        streak["freezes_left"] -= 1
        streak["current"] += 1
    else:
        # Reset
        streak["current"] = 1
        streak["freezes_left"] = 1

    streak["best"] = max(streak["best"], streak["current"])
    streak["last_date"] = today

    # Reset freeze on Mondays
    if date.today().weekday() == 0 and streak.get("_freeze_reset") != today:
        streak["freezes_left"] = 1
        streak["_freeze_reset"] = today

    await redis.set(key, json.dumps(streak), ex=STREAK_TTL)
    return streak


async def get_streak(user_id: str) -> dict:
    """Get current streak without updating."""
    redis = get_redis()
    raw = await redis.get(f"streak:{user_id}")
    if raw:
        return json.loads(raw if isinstance(raw, str) else raw.decode())
    return {"current": 0, "best": 0, "last_date": ""}


def get_streak_text(streak: dict) -> str:
    """Get streak display text for brief."""
    current = streak.get("current", 0)
    if current <= 0:
        return ""
    if current == 1:
        return "✨ Первый день с Касси!"
    if current == 2:
        return "✨ 2 дня подряд — отличное начало!"
    return f"🔥 {current} дней с Касси!"


def check_milestone(streak: dict, knows_pct: int = 0) -> str | None:
    """Check if streak hit a milestone. Returns message or None."""
    current = streak.get("current", 0)
    msg = MILESTONES.get(current)
    if msg and "{knows_pct}" in msg:
        msg = msg.format(knows_pct=knows_pct)
    return msg
