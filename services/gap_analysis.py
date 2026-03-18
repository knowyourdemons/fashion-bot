"""Gap analysis — шоппинг-лист по гардеробу."""
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()

_SEASON_MAP = {
    12: "зима", 1: "зима", 2: "зима",
    3: "весна", 4: "весна", 5: "весна",
    6: "лето", 7: "лето", 8: "лето",
    9: "осень", 10: "осень", 11: "осень",
}


def _get_current_season(tz_str: str) -> str:
    try:
        import pytz
        tz = pytz.timezone(tz_str)
        month = datetime.now(tz).month
    except Exception:
        month = datetime.now(timezone.utc).month
    return _SEASON_MAP.get(month, "весна")


async def build_shopping_list(
    user, items: list, redis, *, child=None
) -> Optional[str]:
    """
    Анализирует гардероб и возвращает шоппинг-лист.

    Returns:
        "lock"  — другой запрос уже выполняется
        ""      — гардероб ок, ничего докупать не нужно
        None    — ошибка или мало вещей (< 5)
        str     — текст шоппинг-листа
    """
    items = items or []

    if len(items) < 5:
        return None

    lock_key = f"gap_lock:{user.id}"
    cache_key = f"gap_analysis:{user.id}"

    # Проверить lock
    if await redis.get(lock_key):
        return "lock"

    # Проверить кэш
    cached = await redis.get(cache_key)
    if cached:
        return cached.decode() if isinstance(cached, bytes) else cached

    # Определить сезон
    season = _get_current_season(user.timezone or "Europe/Vilnius")

    # Owner context
    segment = getattr(user, "segment", "") or ""
    is_child_wardrobe = segment in ("mom_girl", "mom_boy")

    if is_child_wardrobe:
        if child is not None and getattr(child, "birthdate", None):
            from datetime import date
            age_years = (date.today() - child.birthdate).days // 365
            owner_context = f"Детский гардероб, возраст ребёнка {age_years} лет."
        else:
            owner_context = "Детский гардероб."
    else:
        owner_context = "Взрослая женщина."

    # Топ-50 по score_item DESC (None → в конец)
    sorted_items = sorted(
        items,
        key=lambda x: (
            getattr(x, "score_item", None) is None,
            -(getattr(x, "score_item", None) or 0),
        ),
    )[:50]

    # Только нужные поля для промпта
    items_lines = "\n".join(
        f"- {getattr(i, 'category_group', '')} | {getattr(i, 'type', '')} | "
        f"{getattr(i, 'color', '')} | сезон: {getattr(i, 'season', [])}"
        for i in sorted_items
    )

    colortype = user.colortype or ""
    colortype_str = f"\nЦветотип: {colortype}." if colortype else ""

    user_prompt = (
        f"{owner_context}{colortype_str}\n"
        f"Сезон: {season}.\n\n"
        f"Гардероб ({len(sorted_items)} вещей):\n{items_lines}\n\n"
        f"Определи 5–7 конкретных вещей которых не хватает для этого сезона. "
        f"Указывай цвет с учётом цветотипа. "
        f"Если гардероб полный — ответь пустой строкой. "
        f"Формат: нумерованный список, одна вещь на строку, без пояснений."
    )

    system_prompt = "Ты стилист-аналитик. Отвечай только на русском. Кратко и по делу."

    # Установить lock перед вызовом Claude
    await redis.set(lock_key, "1", ex=60)

    try:
        from core.anthropic_client import get_anthropic_pool
        pool = get_anthropic_pool()

        response = await pool.create_message(
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=800,
            model="claude-haiku-4-5-20251001",
            system=system_prompt,
        )

        result = response.content[0].text.strip() if response.content else ""

        # Сохранить в кэш на 24 часа
        await redis.set(cache_key, result, ex=86400)

        logger.info(
            "gap_analysis.done",
            user_id=str(user.id),
            items_count=len(sorted_items),
            season=season,
        )
        return result

    except Exception as e:
        logger.error("gap_analysis.error", user_id=str(user.id), error=str(e))
        return None

    finally:
        await redis.delete(lock_key)
