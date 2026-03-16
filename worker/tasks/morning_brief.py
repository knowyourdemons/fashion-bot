"""
Morning Brief задача:
- schedule_all(): каждый час ищет юзеров у кого 07:00 по timezone
- generate_brief(payload): погода + гардероб → BriefLog → push send_morning_brief
- send_morning_brief(payload): отправляет сообщение через Telegram Bot API
"""
from datetime import date, datetime

import httpx
import pytz
import structlog

from config import settings
from worker.fast_worker import register

logger = structlog.get_logger()

_SEASONS = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring",  4: "spring", 5: "spring",
    6: "summer",  7: "summer", 8: "summer",
    9: "autumn",  10: "autumn", 11: "autumn",
}


# ── Геокодинг ──────────────────────────────────────────────────────────────

async def _geocode_city(city: str) -> tuple[float, float] | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": "FashionBot/1.0"},
            )
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logger.warning("brief.geocode.failed", city=city, error=str(e))
    return None


# ── Погода ─────────────────────────────────────────────────────────────────

async def _get_weather(lat: float, lon: float, tz: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "temperature_2m,precipitation_probability",
                    "timezone": tz,
                    "forecast_days": 1,
                },
            )
            hourly = resp.json().get("hourly", {})
            temps = hourly.get("temperature_2m", [])
            precip = hourly.get("precipitation_probability", [])
            return {
                "temp_morning": round(temps[7], 1) if len(temps) > 7 else None,
                "temp_evening": round(temps[18], 1) if len(temps) > 18 else None,
                "precip_evening": precip[18] if len(precip) > 18 else 0,
            }
    except Exception as e:
        logger.warning("brief.weather.failed", error=str(e))
        return {"temp_morning": None, "temp_evening": None, "precip_evening": 0}


# ── Выбор образа ───────────────────────────────────────────────────────────

def _select_outfit(items: list, season: str, today: date) -> list:
    available = [
        i for i in items
        if (not i.season or season in i.season) and i.last_worn != today
    ]
    outfit = []
    one_piece = next((i for i in available if i.category_group == "one_piece"), None)
    top = next((i for i in available if i.category_group == "top"), None)
    bottom = next((i for i in available if i.category_group == "bottom"), None)
    footwear = next((i for i in available if i.category_group == "footwear"), None)

    if one_piece:
        outfit.append(one_piece)
    elif top:
        outfit.append(top)
        if bottom:
            outfit.append(bottom)
    if footwear:
        outfit.append(footwear)
    return outfit


# ── Cron: schedule_all ─────────────────────────────────────────────────────

async def schedule_all() -> None:
    """Каждый час отбирает юзеров у кого сейчас 07:00 → пушит generate_brief."""
    import redis.asyncio as aioredis
    from sqlalchemy import select
    from db.base import AsyncReadSession
    from db.models.user import User
    from core.queue import RedisQueue, QueuePriority

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    queue = RedisQueue(redis_client)
    count = 0

    try:
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(
                    User.onboarding_completed.is_(True),
                    User.is_active.is_(True),
                    User.plan != "free",
                    User.deleted_at.is_(None),
                )
            )
            users = list(result.scalars().all())

        today_str = date.today().isoformat()

        for user in users:
            try:
                tz = pytz.timezone(user.timezone or "Europe/Vilnius")
                if datetime.now(tz).hour != 7:
                    continue
                lock_key = f"lock:brief:{user.id}:{today_str}"
                acquired = await redis_client.set(lock_key, 1, ex=86400, nx=True)
                if not acquired:
                    continue
                await queue.push(
                    "generate_brief",
                    {"user_id": str(user.id)},
                    priority=QueuePriority.HIGH,
                )
                count += 1
            except Exception as e:
                logger.warning("brief.schedule.user_error", user_id=str(user.id), error=str(e))
    finally:
        await redis_client.aclose()

    logger.info("morning_brief.schedule_all", count=count, hour=datetime.utcnow().hour)


# ── Worker tasks ───────────────────────────────────────────────────────────

@register("generate_brief")
async def generate_brief(payload: dict) -> dict:
    """Генерирует Morning Brief: погода + гардероб → BriefLog → push send."""
    import uuid as _uuid
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    import redis.asyncio as aioredis
    from db.base import AsyncWriteSession, AsyncReadSession
    from db.models.user import User
    from db.crud.wardrobe import get_owner_items
    from db.crud.brief_log import create_log
    from core.queue import RedisQueue, QueuePriority

    user_id = _uuid.UUID(payload["user_id"])

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User)
            .options(selectinload(User.children))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()

    if not user:
        logger.warning("brief.generate.user_not_found", user_id=str(user_id))
        return {}

    # TODO: бриф для взрослых (no_kids/pregnant)
    if user.segment not in ("mom_girl", "mom_boy"):
        logger.info("brief.generate.skipped_adult", user_id=str(user_id))
        return {}

    children = [c for c in (user.children or []) if c.deleted_at is None]
    if not children:
        logger.info("brief.generate.no_children", user_id=str(user_id))
        return {}

    # Погода
    coords = await _geocode_city(user.city or "")
    weather = {}
    if coords:
        weather = await _get_weather(coords[0], coords[1], user.timezone or "Europe/Vilnius")

    today = date.today()
    season = _SEASONS[today.month]
    day_type = "садик" if today.weekday() < 5 else "прогулка"

    from services.scoring import matrix_name_for_owner
    from db.models.scoring_matrix import ScoringMatrix
    from sqlalchemy import select as _sel

    child_briefs = []
    all_outfit_ids: list[str] = []
    any_wow = False

    for child in children:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child.id, "child")

        if not items:
            child_briefs.append(f"👧 {child.name}: гардероб пуст. Добавь вещи 📸")
            continue

        outfit = _select_outfit(items, season, today)
        if not outfit:
            child_briefs.append(
                f"👧 {child.name}: подходящих вещей не нашла. Добавь больше вещей 👗"
            )
            continue

        all_outfit_ids.extend(str(i.id) for i in outfit)
        scored = [float(i.score_item) for i in outfit if i.score_item]
        outfit_score = round(sum(scored) / len(scored), 1) if scored else None

        # WOW детектор
        is_wow_outfit = bool(scored and sum(scored) / len(scored) >= 8.0)
        wow_msg = ""
        if is_wow_outfit:
            matrix_name = matrix_name_for_owner(user, child)
            async with AsyncReadSession() as session:
                result = await session.execute(
                    _sel(ScoringMatrix).where(
                        ScoringMatrix.name == matrix_name,
                        ScoringMatrix.is_active.is_(True),
                    )
                )
                mx = result.scalar_one_or_none()
            if mx:
                wow_msg = mx.criteria.get("_wow_message", "")
            any_wow = True

        lines = [f"👧 {child.name} ({day_type}):"]
        for item in outfit:
            lines.append(f"→ {item.type} ({item.color})")
        if outfit_score is not None:
            lines.append(f"⭐ Скор образа: {outfit_score}/10")
        if wow_msg:
            lines.append(wow_msg)
        child_briefs.append("\n".join(lines))

    # Текст бриф
    temp_m = weather.get("temp_morning")
    temp_e = weather.get("temp_evening")
    precip_e = weather.get("precip_evening", 0)

    weather_line = ""
    if temp_m is not None:
        sm = "+" if temp_m >= 0 else ""
        se = "+" if (temp_e or 0) >= 0 else ""
        weather_line = f"🌡 {user.city}: {sm}{temp_m}°C → вечером {se}{temp_e}°C\n"
        if precip_e and precip_e > 50:
            weather_line += "⚠️ Вечером дождь — возьми зонт!\n"

    brief_text = (
        f"🌅 Доброе утро, {user.name}!\n"
        f"{weather_line}\n"
        + "\n\n".join(child_briefs)
        + "\n\nКак тебе образ?"
    )

    # Сохранить BriefLog
    async with AsyncWriteSession() as session:
        log = await create_log(
            session,
            user_id=user.id,
            date=today,
            weather_summary=weather_line.strip(),
            outfit_description="\n".join(child_briefs),
            outfit_items=all_outfit_ids,
            is_wow=any_wow,
        )
        await session.commit()
        brief_id = str(log.id)

    # Push send task
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    try:
        queue = RedisQueue(redis_client)
        await queue.push(
            "send_morning_brief",
            {"telegram_id": user.telegram_id, "text": brief_text, "brief_id": brief_id},
            priority=QueuePriority.HIGH,
        )
    finally:
        await redis_client.aclose()

    logger.info("morning_brief.generated", user_id=str(user_id), brief_id=brief_id)
    return {"brief_id": brief_id}


@register("send_morning_brief")
async def send_morning_brief(payload: dict) -> dict:
    """Отправляет Morning Brief через Telegram Bot API (httpx)."""
    telegram_id = payload["telegram_id"]
    text = payload["text"]
    brief_id = payload["brief_id"]

    reply_markup = {
        "inline_keyboard": [[
            {"text": "👍 Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
            {"text": "👎 Другое", "callback_data": f"brief_feedback:down:{brief_id}"},
        ]]
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": telegram_id, "text": text, "reply_markup": reply_markup},
            )
            resp.raise_for_status()
        logger.info("morning_brief.sent", telegram_id=telegram_id, brief_id=brief_id)
        return {"sent": True}
    except Exception as e:
        logger.error("morning_brief.send_failed", telegram_id=telegram_id, error=str(e))
        return {"sent": False, "error": str(e)}
