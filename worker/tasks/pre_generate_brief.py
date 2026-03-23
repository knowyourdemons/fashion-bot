"""Pre-generate morning briefs overnight for fast delivery at 7 AM."""
import asyncio
import json
from datetime import date, datetime, timedelta

import pytz
import structlog

logger = structlog.get_logger()


async def run() -> None:
    """Pre-generate outfit + collage for each eligible user at 02:00 local time."""
    from sqlalchemy import select, or_
    from datetime import timezone as _tz

    from db.base import AsyncReadSession
    from db.models.user import User
    from core.redis import get_redis
    from core.permissions import get_effective_plan, is_brief_day

    redis = get_redis()
    count = 0
    today = date.today()
    tomorrow = today + timedelta(days=1)

    try:
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(
                    User.onboarding_completed.is_(True),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    or_(
                        User.plan != "free",
                        User.trial_ends_at > datetime.now(_tz.utc),
                    ),
                )
            )
            users = list(result.scalars().all())

        for user in users:
            try:
                tz = pytz.timezone(user.timezone or "Europe/Vilnius")
                local_hour = datetime.now(tz).hour

                # Only pre-generate for users where it's ~02:00 local time
                if local_hour != 2:
                    continue

                plan = get_effective_plan(user)
                if not is_brief_day(plan, user.timezone or "Europe/Vilnius"):
                    continue

                # Check if already pre-generated
                cache_key = f"prebrief:{user.id}:{tomorrow.isoformat()}"
                if await redis.get(cache_key):
                    continue

                # Get forecast weather for tomorrow morning
                from services.brief_weather import _geocode_city, _get_weather
                weather = {}
                if user.city:
                    coords = await _geocode_city(user.city)
                    if coords:
                        weather = await _get_weather(
                            coords[0], coords[1],
                            user.timezone or "Europe/Vilnius",
                        )

                # Generate outfit (same logic as morning brief but save to cache)
                from db.crud.wardrobe import get_owner_items
                from db.crud.children import get_children
                from services.outfit_builder import has_minimum_wardrobe
                from services.brief_weather import _SEASONS

                async with AsyncReadSession() as s:
                    children = await get_children(s, user.id)

                # Determine owner
                child = children[0] if children else None
                owner_id = child.id if child else user.id
                owner_type = "child" if child else "user"

                async with AsyncReadSession() as s:
                    items = await get_owner_items(s, owner_id, owner_type)

                if not has_minimum_wardrobe(items):
                    continue

                season = _SEASONS.get(tomorrow.month, "spring")
                temp_m = weather.get("temp_morning") or 10.0

                # Store pre-generated data (outfit will be built at send time from this)
                pre_data = {
                    "weather": weather,
                    "season": season,
                    "owner_id": str(owner_id),
                    "owner_type": owner_type,
                    "item_count": len(items),
                    "temp": temp_m,
                    "generated_at": datetime.utcnow().isoformat(),
                }
                await redis.set(cache_key, json.dumps(pre_data), ex=43200)  # 12h TTL
                count += 1

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning("pre_generate.user_error", user_id=str(user.id), error=str(e))

    except Exception as e:
        logger.error("pre_generate.error", error=str(e))

    logger.info("pre_generate.done", count=count)
