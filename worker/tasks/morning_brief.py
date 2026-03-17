"""
Morning Brief задача:
- schedule_all(): каждый час ищет юзеров у кого 07:00 по timezone
- generate_brief(payload): погода + гардероб → BriefLog → push send_morning_brief
- send_morning_brief(payload): отправляет сообщение через Telegram Bot API
"""
from datetime import date, datetime

import json
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


# ── Температурный режим ─────────────────────────────────────────────────────

def _get_temp_regime(temp: float) -> str:
    if temp > 25:
        return "жара"
    elif temp > 15:
        return "тепло"
    elif temp > 10:
        return "прохладно"
    elif temp > 5:
        return "холодно"
    elif temp > 0:
        return "мороз"
    else:
        return "сильный_мороз"


# ── Выбор образа по температуре ─────────────────────────────────────────────

def _select_outfit(
    items: list,
    season: str,
    today: date,
    temp_morning: float | None = None,
    temp_evening: float | None = None,
    precip_evening: float = 0,
) -> dict:
    """Выбирает образ послойно с учётом температуры.

    Returns dict с ключами:
        thermal_top, thermal_bottom, underwear_items, underwear_text,
        one_piece, top, bottom, removable_layer, tights, socks,
        footwear, outerwear, hat, scarf, gloves, warnings, all_items
    """
    temp = temp_morning if temp_morning is not None else 15.0
    temp_eve = temp_evening if temp_evening is not None else temp
    regime = _get_temp_regime(temp)
    warnings: list[str] = []

    # Переходный период
    if abs(temp_eve - temp) > 8:
        sm = "+" if temp >= 0 else ""
        se = "+" if temp_eve >= 0 else ""
        warnings.append(f"🌡 Утром {sm}{temp}°C → вечером {se}{temp_eve}°C — одень слоями!")

    # Дождь вечером
    if precip_evening and precip_evening > 50:
        warnings.append("☂️ Вечером дождь — возьми зонт!")

    available = [
        i for i in items
        if (not i.season or season in i.season) and i.last_worn != today
    ]

    def _first(cg=None, type_contains=None, type_not_contains=None,
               prefer_contains=None, exclude_ids=None):
        pool = available
        if cg:
            if isinstance(cg, (list, tuple)):
                pool = [i for i in pool if i.category_group in cg]
            else:
                pool = [i for i in pool if i.category_group == cg]
        if type_contains:
            pool = [i for i in pool if type_contains.lower() in (i.type or "").lower()]
        if type_not_contains:
            pool = [i for i in pool if type_not_contains.lower() not in (i.type or "").lower()]
        if exclude_ids:
            pool = [i for i in pool if i.id not in exclude_ids]
        if prefer_contains and pool:
            preferred = [i for i in pool if prefer_contains.lower() in (i.type or "").lower()]
            return preferred[0] if preferred else pool[0]
        return pool[0] if pool else None

    def _first_any(cg, contains_list):
        pool = [i for i in available if i.category_group == cg]
        pool = [i for i in pool if any(c.lower() in (i.type or "").lower() for c in contains_list)]
        return pool[0] if pool else None

    result: dict = {
        "thermal_top": None,
        "thermal_bottom": None,
        "underwear_items": [],
        "underwear_text": None,
        "one_piece": None,
        "top": None,
        "bottom": None,
        "removable_layer": None,
        "tights": None,
        "socks": None,
        "footwear": None,
        "outerwear": None,
        "hat": None,
        "scarf": None,
        "gloves": None,
        "warnings": warnings,
        "all_items": [],
    }

    # ── СЛОЙ 0: Термобельё (temp <= 5°C) ─────────────────────────────────
    if temp <= 5:
        result["thermal_top"] = _first(cg="underwear", type_contains="термо")
        t_top_id = {result["thermal_top"].id} if result["thermal_top"] else set()
        result["thermal_bottom"] = _first(cg="underwear", type_contains="термо", exclude_ids=t_top_id)

    # ── СЛОЙ 1: Бельё (non-thermal underwear) ────────────────────────────
    underwear_pool = [
        i for i in available
        if i.category_group == "underwear" and "термо" not in (i.type or "").lower()
    ]
    trusiki = next(
        (i for i in underwear_pool if any(w in (i.type or "").lower() for w in ["трусик", "underwear"])),
        underwear_pool[0] if underwear_pool else None,
    )
    if trusiki:
        result["underwear_items"].append(trusiki)
        maika = next(
            (i for i in underwear_pool
             if i.id != trusiki.id
             and any(w in (i.type or "").lower() for w in ["майк", "undershirt", "боди"])),
            None,
        )
        if maika:
            result["underwear_items"].append(maika)
    else:
        result["underwear_text"] = "трусики"

    # ── СЛОЙ 2: Основной образ ────────────────────────────────────────────
    if regime in ("жара", "тепло"):
        result["one_piece"] = _first(cg="one_piece")
        if not result["one_piece"]:
            result["top"] = _first(cg="top")
            result["bottom"] = (
                _first(cg="bottom", prefer_contains="шорт")
                or _first(cg="bottom", prefer_contains="юбк")
                or _first(cg="bottom")
            )
    elif regime in ("прохладно", "холодно"):
        result["top"] = (
            _first(cg="top", prefer_contains="кофт")
            or _first(cg="top", prefer_contains="свитер")
            or _first(cg="top")
        )
        result["bottom"] = (
            _first(cg="bottom", prefer_contains="джинс")
            or _first(cg="bottom", prefer_contains="брюк")
            or _first(cg="bottom")
        )
    else:  # мороз / сильный_мороз
        result["top"] = (
            _first(cg="top", prefer_contains="свитер")
            or _first(cg="top", prefer_contains="кофт")
            or _first(cg="top")
        )
        result["bottom"] = (
            _first(cg="bottom", prefer_contains="брюк")
            or _first(cg="bottom")
        )

    # Переходный период — съёмный слой
    if abs(temp_eve - temp) > 8:
        top_id = {result["top"].id} if result["top"] else set()
        removable = next(
            (i for i in available
             if i.category_group == "top"
             and any(w in (i.type or "").lower() for w in ["кофт", "толстовк", "худи"])
             and i.id not in top_id),
            None,
        )
        result["removable_layer"] = removable

    # ── СЛОЙ 3: Колготки/носки ─────────────────────────────────────────────
    if temp <= 15:
        tights = (
            _first_any("base_layer", ["колготк", "tights"])
            or _first_any("footwear", ["колготк", "tights"])
        )
        if tights and temp <= 5:
            warm = next(
                (i for i in available
                 if i.category_group in ("base_layer", "footwear")
                 and any(w in (i.type or "").lower() for w in ["колготк", "tights"])
                 and any(w in (i.type or "").lower() for w in ["плотн", "тёплые", "warm", "thick"])),
                tights,
            )
            tights = warm
        result["tights"] = tights
    else:
        result["socks"] = (
            _first_any("base_layer", ["носк", "socks", "гольф"])
            or _first_any("footwear", ["носк", "socks", "гольф"])
        )

    # ── СЛОЙ 4: Обувь ─────────────────────────────────────────────────────
    sock_types = {"носки", "гольфы", "socks", "колготки", "tights"}
    footwear_pool = [
        i for i in available
        if i.category_group == "footwear"
        and (i.type or "").lower() not in sock_types
    ]
    if footwear_pool:
        if regime == "жара":
            preferred = [i for i in footwear_pool if any(w in (i.type or "").lower() for w in ["сандал", "босоножк", "sandal"])]
        elif regime == "прохладно":
            preferred = [i for i in footwear_pool if any(w in (i.type or "").lower() for w in ["кроссовк", "туфл", "sneaker"])]
        elif regime in ("холодно", "мороз", "сильный_мороз"):
            preferred = [i for i in footwear_pool if any(w in (i.type or "").lower() for w in ["ботинк", "сапог", "boot"])]
        else:
            preferred = []
        result["footwear"] = preferred[0] if preferred else footwear_pool[0]

    # ── СЛОЙ 5: Верхняя одежда ────────────────────────────────────────────
    if temp <= 15:
        outerwear_pool = [i for i in available if i.category_group == "outerwear"]
        if outerwear_pool:
            if temp <= 5:
                warm = [i for i in outerwear_pool if any(w in (i.type or "").lower() for w in ["пуховик", "тёплая", "зимняя", "down"])]
                result["outerwear"] = warm[0] if warm else outerwear_pool[0]
            else:
                result["outerwear"] = outerwear_pool[0]

    # ── СЛОЙ 6: Аксессуары ────────────────────────────────────────────────
    if temp < 10:
        result["hat"] = _first_any("accessory", ["шапк", "hat", "balaclava", "балаклав"])
    if temp < 5:
        result["scarf"] = _first_any("accessory", ["шарф", "scarf"])
    if temp < 0:
        result["gloves"] = _first_any("accessory", ["перчатк", "варежк", "gloves"])

    # Все вещи для скоринга
    all_items = []
    for key in ("thermal_top", "thermal_bottom", "one_piece", "top", "bottom",
                "removable_layer", "tights", "socks", "footwear", "outerwear",
                "hat", "scarf", "gloves"):
        if result[key]:
            all_items.append(result[key])
    all_items.extend(result["underwear_items"])
    result["all_items"] = all_items
    result["temp"] = temp

    return result


# ── Форматирование блока ребёнка ────────────────────────────────────────────

_MISSING = " (в гардеробе нет — добавь фото 📸)"


def _format_child_block(
    child_name: str,
    day_type: str,
    outfit: dict,
    outfit_score,
    wow_msg: str,
    temp: float | None = None,
) -> str:
    temp = temp if temp is not None else outfit.get("temp", 15.0)
    lines = [f"👧 {child_name} ({day_type}):"]

    # Термобельё
    if outfit["thermal_top"] or outfit["thermal_bottom"]:
        parts = []
        if outfit["thermal_top"]:
            t = outfit["thermal_top"]
            parts.append(f"→ {t.type} ({t.color})")
        if outfit["thermal_bottom"]:
            t = outfit["thermal_bottom"]
            parts.append(f"→ {t.type} ({t.color})")
        lines.append("🧤 Термобельё: " + " ".join(parts))

    # Бельё
    underwear_parts = []
    if outfit["underwear_text"]:
        underwear_parts.append(f"→ {outfit['underwear_text']}")
    for item in outfit["underwear_items"]:
        underwear_parts.append(f"→ {item.type} ({item.color})")
    if underwear_parts:
        lines.append("👙 Бельё: " + " ".join(underwear_parts))

    # Образ
    lines.append("👗 Образ:")
    if outfit["one_piece"]:
        i = outfit["one_piece"]
        lines.append(f"→ 👗 {i.type} ({i.color})")
    else:
        if outfit["top"]:
            i = outfit["top"]
            lines.append(f"→ 👕 {i.type} ({i.color})")
        else:
            lines.append(f"→ 👕 любой верх по сезону{_MISSING}")
        if outfit["bottom"]:
            i = outfit["bottom"]
            lines.append(f"→ 👖 {i.type} ({i.color})")
        else:
            lines.append(f"→ 👖 любые штаны/юбка{_MISSING}")
    if outfit["removable_layer"]:
        i = outfit["removable_layer"]
        lines.append(f"→ {i.type} ({i.color}) [снять вечером]")

    # Ноги
    leg_item = outfit["tights"] or outfit["socks"]
    if leg_item:
        lines.append(f"🧦 Ноги: → {leg_item.type} ({leg_item.color})")
    elif temp < 10:
        lines.append(f"🧦 Ноги: → 🧦 колготки или тёплые носки{_MISSING}")

    # Обувь
    if outfit["footwear"]:
        i = outfit["footwear"]
        lines.append(f"👟 Обувь: → {i.type} ({i.color})")
    else:
        lines.append(f"👟 Обувь: → 👟 любая закрытая обувь{_MISSING}")

    # Верхняя одежда
    if outfit["outerwear"]:
        i = outfit["outerwear"]
        lines.append(f"🧥 Верхняя одежда: → {i.type} ({i.color})")
    elif temp <= 15:
        if temp < 5:
            lines.append(f"🧥 Верхняя одежда: → 🧥 тёплая куртка или пуховик{_MISSING}")
        else:
            lines.append(f"🧥 Верхняя одежда: → 🧥 любая куртка/ветровка{_MISSING}")

    # Аксессуары
    acc_parts = []
    for key in ("hat", "scarf", "gloves"):
        if outfit[key]:
            i = outfit[key]
            acc_parts.append(f"→ {i.type} ({i.color})")
    if acc_parts:
        lines.append("🎩 Аксессуары: " + " ".join(acc_parts))

    lines.append("")
    if outfit_score is not None:
        lines.append(f"⭐ Скор образа: {outfit_score}/10")
    if wow_msg:
        lines.append(f"✨ {wow_msg}")

    return "\n".join(lines)


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

    temp_m = weather.get("temp_morning")
    temp_e = weather.get("temp_evening")
    precip_e = weather.get("precip_evening", 0)

    from services.scoring import matrix_name_for_owner
    from db.models.scoring_matrix import ScoringMatrix
    from sqlalchemy import select as _sel

    child_briefs = []
    all_outfit_ids: list[str] = []
    any_wow = False
    global_warnings: list[str] = []

    for child in children:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child.id, "child")

        if not items:
            child_briefs.append(f"👧 {child.name}: гардероб пуст. Добавь вещи 📸")
            continue

        outfit = _select_outfit(items, season, today, temp_m, temp_e, precip_e or 0)

        # Предупреждения — один раз в глобальный блок
        if outfit["warnings"] and not global_warnings:
            global_warnings.extend(outfit["warnings"])

        if not outfit["all_items"] and not outfit["underwear_text"]:
            child_briefs.append(
                f"👧 {child.name}: подходящих вещей не нашла. Добавь больше вещей 👗"
            )
            continue

        all_outfit_ids.extend(str(i.id) for i in outfit["all_items"])
        scored = [float(i.score_item) for i in outfit["all_items"] if i.score_item]
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

        child_briefs.append(_format_child_block(child.name, day_type, outfit, outfit_score, wow_msg))

    # ── Заголовок с погодой ──────────────────────────────────────────────
    weather_line = ""
    if temp_m is not None:
        sm = "+" if temp_m >= 0 else ""
        se = "+" if (temp_e or 0) >= 0 else ""
        weather_line = f"🌡 {user.city}: {sm}{temp_m}°C → вечером {se}{temp_e}°C"

    header = f"🌅 Доброе утро, {user.name}!"
    if weather_line:
        header += f"\n{weather_line}"
    for warn in global_warnings:
        header += f"\n{warn}"

    brief_text = (
        header
        + "\n\n"
        + "\n\n".join(child_briefs)
        + "\n\nКак тебе образ?"
    )

    # Сохранить BriefLog
    async with AsyncWriteSession() as session:
        log = await create_log(
            session,
            user_id=user.id,
            date=today,
            weather_summary=weather_line,
            outfit_description="\n".join(child_briefs),
            outfit_items=all_outfit_ids,
            is_wow=any_wow,
        )
        await session.commit()
        brief_id = str(log.id)

    # Собираем уникальные photo_id для коллажа (исключаем base_layer/underwear)
    collage_items = [
        i for i in sum([outfit["all_items"] for outfit in
            # пересобираем all_items из child_briefs данных
            # берём напрямую из последнего outfit
            []], [])
    ]
    # Проще: берём вещи из БД по all_outfit_ids
    collage_photo_ids: list[str] = []
    collage_labels: list[str] = []
    if all_outfit_ids:
        from db.models.wardrobe import WardrobeItem as WI
        from sqlalchemy import select as _select2
        import uuid as _uuid2
        async with AsyncReadSession() as session:
            ids_uuid = [_uuid2.UUID(i) for i in all_outfit_ids]
            res = await session.execute(
                _select2(WI).where(
                    WI.id.in_(ids_uuid),
                    WI.show_in_collage.is_(True),
                    WI.category_group.notin_(["underwear"]),
                )
            )
            collage_items_db = res.scalars().all()

        # Каждая вещь = отдельная ячейка с индивидуальным кропом из R2
        collage_photo_urls: list[str | None] = []
        for item in collage_items_db:
            collage_photo_ids.append(item.photo_id)
            collage_labels.append(item.type)
            collage_photo_urls.append(item.photo_url)  # r2_key кропа
    else:
        collage_photo_urls = []

    # Push send task
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    try:
        queue = RedisQueue(redis_client)
        await queue.push(
            "send_morning_brief",
            {
                "telegram_id": user.telegram_id,
                "text": brief_text,
                "brief_id": brief_id,
                "collage_photo_ids": collage_photo_ids,
                "collage_labels": collage_labels,
                "collage_photo_urls": collage_photo_urls,
            },
            priority=QueuePriority.HIGH,
        )
    finally:
        await redis_client.aclose()

    logger.info(
        "morning_brief.generated",
        user_id=str(user_id),
        brief_id=brief_id,
        outfit_ids_count=len(all_outfit_ids),
        collage_photos_count=len(collage_photo_ids),
    )
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
            # Пробуем собрать коллаж
            collage_photo_ids = payload.get("collage_photo_ids", [])
            collage_labels = payload.get("collage_labels", [])
            collage_photo_urls = payload.get("collage_photo_urls")
            collage_bytes = None

            if collage_photo_ids:
                try:
                    from services.image_builder import build_collage
                    collage_bytes = await build_collage(
                        collage_photo_ids, collage_labels, collage_photo_urls
                    )
                except Exception as e:
                    logger.warning("morning_brief.collage_failed", error=str(e))

            if collage_bytes:
                # Отправляем фото с caption и кнопками
                import base64 as _b64
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto",
                    data={
                        "chat_id": telegram_id,
                        "caption": text,
                        "reply_markup": json.dumps(reply_markup),
                    },
                    files={"photo": ("collage.jpg", collage_bytes, "image/jpeg")},
                )
            else:
                # Фолбэк — просто текст
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": telegram_id, "text": text, "reply_markup": reply_markup},
                )
            resp.raise_for_status()
        logger.info("morning_brief.sent", telegram_id=telegram_id, brief_id=brief_id, has_collage=bool(collage_bytes))
        return {"sent": True}
    except Exception as e:
        logger.error("morning_brief.send_failed", telegram_id=telegram_id, error=str(e))
        return {"sent": False, "error": str(e)}
