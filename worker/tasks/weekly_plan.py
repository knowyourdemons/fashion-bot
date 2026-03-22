"""Weekly Plan — 5 outfits for Mon-Fri, generated Sunday evening.

Premium only. Текстовый формат, без коллажей.
Коллаж генерируется утром для конкретного дня (morning brief).
"""
import json
import structlog
from datetime import date, datetime, timedelta

import pytz

logger = structlog.get_logger()

_TARGET_HOUR = 19  # 19:00 local time, Sunday
_WEEKDAY_NAMES = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт"}

# Occasion по дню и сегменту
_WEEKLY_OCCASIONS = {
    "no_kids": ["офис", "офис", "кэжуал", "офис", "casual friday"],
    "pregnant": ["прогулка", "прогулка", "кэжуал", "прогулка", "отдых"],
    "mom_girl": ["садик", "садик", "садик", "садик", "прогулка"],
    "mom_boy": ["садик", "садик", "садик", "садик", "прогулка"],
}

# Basic items that can repeat across days
_BASIC_TYPES = frozenset(["джинсы", "кроссовки", "ботинки", "сапоги"])
_BASIC_COLORS = frozenset(["белый", "чёрный", "серый", "бежевый"])


def _is_basic_item(item) -> bool:
    """Basic items can repeat across days (jeans, basic sneakers)."""
    t = (getattr(item, "type", "") or "").lower()
    c = (getattr(item, "color", "") or "").lower()
    return t in _BASIC_TYPES or (t in ("футболка",) and c in _BASIC_COLORS)


def _item_emoji(category: str) -> str:
    return {
        "top": "👚", "bottom": "👖", "one_piece": "👗",
        "outerwear": "🧥", "footwear": "👟", "accessory": "🎒",
    }.get(category, "👔")


def _format_outfit_line(outfit: dict) -> str:
    """Format outfit as one-line text with emoji."""
    parts = []
    for slot in ["outerwear", "top", "bottom", "one_piece", "footwear", "hat", "scarf"]:
        item = outfit.get(slot)
        if item:
            color = getattr(item, "color", "") or ""
            type_name = getattr(item, "type", "") or ""
            parts.append(f"{color} {type_name}".strip())
    return " + ".join(parts) if parts else "образ подобран"


async def generate_weekly_plan(user, items: list, child=None, redis=None) -> list[dict]:
    """Generate 5 outfits for Mon-Fri using rule-based selector.

    Returns list of 5 dicts: {day_name, occasion, outfit_line, item_ids}
    """
    from services.outfit_selector import _select_outfit
    from services.outfit_builder import has_minimum_wardrobe

    if not has_minimum_wardrobe(items):
        return []

    segment = getattr(user, "segment", "no_kids") or "no_kids"
    occasions = _WEEKLY_OCCASIONS.get(segment, _WEEKLY_OCCASIONS["no_kids"])

    # Get current season
    month = date.today().month
    SEASONS = {12: "winter", 1: "winter", 2: "winter",
               3: "spring", 4: "spring", 5: "spring",
               6: "summer", 7: "summer", 8: "summer",
               9: "autumn", 10: "autumn", 11: "autumn"}
    season = SEASONS[month]

    # Get weather estimate
    temp_morning = 10.0  # default
    if user.city:
        try:
            from services.brief_weather import _geocode_city, _get_weather
            coords = await _geocode_city(user.city)
            if coords:
                weather = await _get_weather(coords[0], coords[1], user.timezone or "Europe/Vilnius")
                temp_morning = weather.get("temp_morning", 10.0)
        except Exception:
            pass

    used_ids: set = set()
    plan = []
    today = date.today()

    for day_idx in range(5):
        day_date = today + timedelta(days=day_idx + 1)  # Monday = tomorrow+0 if Sunday
        occasion = occasions[day_idx]

        # Filter out already used non-basic items
        available = [i for i in items if _is_basic_item(i) or i.id not in used_ids]

        outfit = _select_outfit(
            items=available,
            season=season,
            today=day_date,
            temp_morning=temp_morning,
            temp_evening=temp_morning - 3,  # estimate
        )

        # Track used items (skip basics)
        all_items = outfit.get("all_items", [])
        for item in all_items:
            if not _is_basic_item(item):
                used_ids.add(item.id)

        outfit_line = _format_outfit_line(outfit)
        item_ids = [str(i.id) for i in all_items]

        plan.append({
            "day_name": _WEEKDAY_NAMES[day_idx],
            "occasion": occasion,
            "outfit_line": outfit_line,
            "item_ids": item_ids,
        })

    return plan


def format_weekly_message(plan: list[dict], new_combos: int = 0) -> str:
    """Format weekly plan as readable Telegram message."""
    lines = ["📅 План на неделю от Касси\n"]
    for day in plan:
        emoji = "👔" if day["occasion"] in ("офис", "casual friday") else "👚"
        lines.append(f"{day['day_name']} · {day['occasion']}")
        lines.append(f"{emoji} {day['outfit_line']}")
        lines.append("")
    if new_combos > 0:
        lines.append(f"💡 {new_combos} комбинаций, которые ты ещё не пробовала!")
    return "\n".join(lines).strip()


async def schedule_weekly() -> None:
    """Каждый час — проверить юзеров у которых вс 19:00 по timezone."""
    from db.base import AsyncReadSession
    from db.models.user import User
    from sqlalchemy import select, orm
    from core.permissions import get_effective_plan
    from core.redis import get_redis
    from config import settings
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

    redis = get_redis()
    bot = Bot(token=settings.telegram_bot_token)
    count = 0

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User)
            .options(orm.selectinload(User.children))
            .where(
                User.onboarding_completed.is_(True),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        users = list(result.scalars().all())

    for user in users:
        try:
            # Timezone check: must be Sunday 19:xx local
            tz_name = user.timezone or "Europe/Vilnius"
            try:
                tz = pytz.timezone(tz_name)
                now_local = datetime.now(tz)
            except Exception:
                continue
            if now_local.weekday() != 6 or now_local.hour != _TARGET_HOUR:
                continue

            plan = get_effective_plan(user)
            is_premium = plan in ("premium", "ultra", "admin")

            if not is_premium:
                # Free тизер
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✨ Попробовать Premium", callback_data="show_upgrade"),
                ]])
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text="📅 План на неделю уже готов!\n\nВ Premium — 5 образов на каждый день, без повторов, по погоде.",
                    reply_markup=keyboard,
                )
                logger.info("weekly.teaser_sent", user_id=str(user.id))
                continue

            # Generate plan
            from db.crud.wardrobe import get_owner_items
            async with AsyncReadSession() as s:
                items = await get_owner_items(s, user.id, "user")

            if len(items) < 5:
                continue

            weekly = await generate_weekly_plan(user, items, redis=redis)
            if not weekly:
                continue

            # Cache in Redis
            await redis.set(
                f"weekly:{user.id}",
                json.dumps(weekly, ensure_ascii=False),
                ex=7 * 86400,
            )

            text = format_weekly_message(weekly, new_combos=len(weekly))
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("👍 Отлично!", callback_data="weekly_ok"),
                InlineKeyboardButton("🔄 Перемешать", callback_data="weekly_reshuffle"),
            ]])
            await bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=keyboard,
            )
            logger.info("weekly.sent", user_id=str(user.id), days=len(weekly))
            count += 1
        except Exception as e:
            logger.warning("weekly.failed", user_id=str(user.id), error=str(e))

    logger.info("weekly.schedule", sent=count)
