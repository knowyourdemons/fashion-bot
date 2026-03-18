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
from worker.tasks.style_config import get_placeholder_label, get_temp_regime, SLOT_EMOJI, _needs_tights

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
        if _needs_tights(result, temp):
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
        result["socks"] = (
            _first_any("base_layer", ["носк", "socks", "гольф"])
            or _first_any("footwear", ["носк", "socks", "гольф"])
        )
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

_MISSING = " (в гардеробе нет — добавь фото)"


def _format_item(item) -> str:
    """Форматирует вещь: тип (цвет), без дубля цвета если уже есть в названии."""
    type_lower = (item.type or "").lower()
    color_lower = (item.color or "").lower()
    if not color_lower:
        return (item.type or "").strip()
    # Сравниваем по стему (без последних 2 символов), чтобы
    # "серебристый" находился в "серебристые", "розовый" в "розовые" и т.д.
    stem = color_lower[:-2] if len(color_lower) > 5 else color_lower
    if stem in type_lower:
        return (item.type or "").strip()
    return f"{(item.type or '').strip()} ({item.color})"


def _format_child_block(
    child_name: str,
    day_type: str,
    outfit: dict,
    outfit_score,
    is_wow: bool = False,
    temp: float | None = None,
    colortype: str = "default",
    regime: str = "прохладно",
) -> str:
    temp = temp if temp is not None else outfit.get("temp", 15.0)
    lines = [f"👧 {child_name} ({day_type}):"]

    # Термобельё
    if outfit["thermal_top"] or outfit["thermal_bottom"]:
        parts = []
        if outfit["thermal_top"]:
            parts.append(f"→ {_format_item(outfit['thermal_top'])}")
        if outfit["thermal_bottom"]:
            parts.append(f"→ {_format_item(outfit['thermal_bottom'])}")
        lines.append("🧤 Термобельё: " + " ".join(parts))

    # Бельё
    underwear_parts = []
    if outfit["underwear_text"]:
        underwear_parts.append(f"→ {outfit['underwear_text']}")
    for item in outfit["underwear_items"]:
        underwear_parts.append(f"→ {_format_item(item)}")
    if underwear_parts:
        lines.append("👙 Бельё: " + " ".join(underwear_parts))

    # Образ
    lines.append("👗 Образ:")
    if outfit["one_piece"]:
        i = outfit["one_piece"]
        lines.append(f"→ {SLOT_EMOJI['one_piece']} {_format_item(i)}")
    else:
        if outfit["top"]:
            lines.append(f"→ {SLOT_EMOJI['top']} {_format_item(outfit['top'])}")
        else:
            lbl = get_placeholder_label("top", colortype, regime)
            lines.append(f"→ {SLOT_EMOJI['top']} {lbl or 'верх — любой по сезону'}")
        if outfit["bottom"]:
            lines.append(f"→ {SLOT_EMOJI['bottom']} {_format_item(outfit['bottom'])}")
        else:
            lbl = get_placeholder_label("bottom", colortype, regime)
            lines.append(f"→ {SLOT_EMOJI['bottom']} {lbl or 'низ — любой по сезону'}")
    if outfit["removable_layer"]:
        lines.append(f"→ {_format_item(outfit['removable_layer'])} [снять вечером]")

    # Ноги
    leg_item = outfit["tights"] or outfit["socks"]
    if leg_item:
        lines.append(f"🧦 Ноги: → {_format_item(leg_item)}")
    elif temp < 10:
        lbl = get_placeholder_label("tights", colortype, regime)
        lines.append(f"🧦 Ноги: → {lbl or 'колготки или тёплые носки'}")

    # Обувь
    if outfit["footwear"]:
        lines.append(f"{SLOT_EMOJI['footwear']} Обувь: → {_format_item(outfit['footwear'])}")
    else:
        lbl = get_placeholder_label("footwear", colortype, regime)
        lines.append(f"{SLOT_EMOJI['footwear']} Обувь: → {lbl or 'обувь — любая по сезону'}")

    # Верхняя одежда
    if outfit["outerwear"]:
        lines.append(f"{SLOT_EMOJI['outerwear']} Верхняя одежда: → {_format_item(outfit['outerwear'])}")
    elif temp <= 15:
        lbl = get_placeholder_label("outerwear", colortype, regime)
        if lbl:
            lines.append(f"{SLOT_EMOJI['outerwear']} Верхняя одежда: → {lbl}")

    # Аксессуары
    acc_parts = []
    for key in ("hat", "scarf", "gloves"):
        if outfit[key]:
            acc_parts.append(f"→ {_format_item(outfit[key])}")
    if acc_parts:
        lines.append("🎩 Аксессуары: " + " ".join(acc_parts))

    lines.append("")
    if outfit_score is not None:
        lines.append(f"⭐ Скор образа: {outfit_score}/10")
    if is_wow:
        from worker.tasks.style_config import get_wow_phrase
        lines.append(f"✨ {get_wow_phrase()}")

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


# ── Взрослый бриф ──────────────────────────────────────────────────────────

_REGIME_OUTER_ADVICE = {
    "сильный_мороз": "тёплое пальто или пуховик",
    "мороз":         "тёплая куртка или пальто",
    "холодно":       "куртка или тренч",
    "прохладно":     "лёгкая куртка или кардиган",
    "тепло":         "лёгкий жакет или без верхней одежды",
    "жара":          "лёгкий образ без верхней одежды",
}


async def _generate_adult_brief(user, payload: dict) -> dict:
    """Бриф для взрослых: погода + совет стилиста через Haiku + коллаж."""
    import redis.asyncio as aioredis
    from db.base import AsyncWriteSession, AsyncReadSession
    from db.crud.wardrobe import get_owner_items
    from db.crud.brief_log import create_log
    from core.queue import RedisQueue, QueuePriority
    from core.anthropic_client import get_anthropic_pool
    from services.image_builder import build_collage
    from worker.tasks.style_config import (
        get_placeholder_label, get_temp_regime, COLORTYPE_PALETTES, _needs_tights,
    )

    # Погода
    coords = await _geocode_city(user.city or "")
    weather = {}
    if coords:
        weather = await _get_weather(coords[0], coords[1], user.timezone or "Europe/Vilnius")

    today = date.today()
    temp_m = weather.get("temp_morning") or 10.0
    temp_e = weather.get("temp_evening") or temp_m
    sm = "+" if temp_m >= 0 else ""
    se = "+" if temp_e >= 0 else ""
    weather_line = f"🌡 {user.city}: {sm}{temp_m:.0f}°C → вечером {se}{temp_e:.0f}°C" if user.city else ""

    regime = _get_temp_regime(temp_m)
    colortype = getattr(user, "colortype", None) or "default"

    # Гардероб пользователя
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, user.id, "user")

    # Совет стилиста через Haiku
    outer_advice = _REGIME_OUTER_ADVICE.get(regime, "куртка")

    if items:
        wardrobe_context = ", ".join(
            f"{i.type} {i.color}" for i in
            sorted(items, key=lambda x: float(x.score_item or 0), reverse=True)[:10]
        )
        prompt = (
            f"Погода: {sm}{temp_m:.0f}°C, {regime}. "
            f"Цветотип: {colortype}. "
            f"Гардероб: {wardrobe_context}. "
            f"Дай короткий (2-3 предложения) совет по образу на день "
            f"используя вещи из гардероба. Говори на русском, тон дружелюбный."
        )
    else:
        palette = COLORTYPE_PALETTES.get(colortype, COLORTYPE_PALETTES.get("default", {}))
        top_colors = palette.get("top", ["нейтральный"])
        outer_colors = palette.get("outerwear", ["нейтральный"])
        color_hint = f"{top_colors[0]} верх и {outer_colors[0]} {outer_advice}"
        prompt = (
            f"Погода: {sm}{temp_m:.0f}°C, {regime}. "
            f"Цветотип: {colortype}. "
            f"Дай короткий (2-3 предложения) совет по образу на день. "
            f"Рекомендуй {color_hint}. Говори на русском, тон дружелюбный."
        )

    pool = get_anthropic_pool()
    try:
        advice_resp = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
        )
        stylist_advice = advice_resp.content[0].text.strip()
    except Exception as e:
        logger.warning("brief.adult.haiku_failed", error=str(e))
        stylist_advice = f"Сегодня {sm}{temp_m:.0f}°C — выбери {outer_advice} ✨"

    # Приветствие
    _hour = datetime.now().hour
    if _hour < 12:
        greeting = "Доброе утро"
    elif _hour < 18:
        greeting = "Добрый день"
    else:
        greeting = "Добрый вечер"

    brief_text = f"🌅 {greeting}, {user.name}!\n"
    if weather_line:
        brief_text += f"{weather_line}\n\n"
    brief_text += f"👗 Совет дня:\n{stylist_advice}"
    if not items:
        brief_text += "\n\n📸 Добавь вещи в гардероб — буду подбирать образы каждое утро!"

    # Коллаж из вещей пользователя
    outfit_slots: list[dict] = []
    if items:
        season = _SEASONS[today.month]
        slot_order = ["outerwear", "top", "bottom", "one_piece", "footwear", "accessory"]
        seen_cg: set = set()
        outfit: dict = {}
        for item in sorted(items, key=lambda x: float(x.score_item or 0), reverse=True):
            cg = item.category_group
            if cg not in seen_cg and cg in slot_order:
                outfit[cg] = item
                seen_cg.add(cg)

        for slot in slot_order:
            if slot == "outerwear" and temp_m >= 20:
                continue
            if slot in ("top", "bottom") and outfit.get("one_piece"):
                continue
            if slot == "one_piece" and (outfit.get("top") or outfit.get("bottom")):
                continue

            item = outfit.get(slot)
            if item and getattr(item, "show_in_collage", True):
                outfit_slots.append({
                    "slot": slot,
                    "label": f"{item.type} {item.color}"[:20],
                    "photo_id": item.photo_id,
                    "photo_url": item.photo_url,
                    "has_item": True,
                    "adult": True,
                })
            else:
                ph_label = get_placeholder_label(slot, colortype, regime)
                if ph_label is None:
                    continue
                color_part = ph_label.split(" — ", 1)[1] if " — " in ph_label else "(нет в гардеробе)"
                outfit_slots.append({
                    "slot": slot,
                    "short_label": slot,
                    "label": color_part,
                    "photo_id": None,
                    "photo_url": None,
                    "has_item": False,
                    "adult": True,
                })

    collage_bytes_val = None
    if outfit_slots:
        try:
            collage_bytes_val = await build_collage(outfit_slots=outfit_slots)
        except Exception as e:
            logger.warning("brief.adult.collage_failed", error=str(e))

    # Сохранить BriefLog
    async with AsyncWriteSession() as session:
        log = await create_log(
            session,
            user_id=user.id,
            date=today,
            weather_summary=weather_line,
            outfit_description=brief_text,
            outfit_items=[],
            is_wow=False,
        )
        await session.commit()
        brief_id = str(log.id)

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
                "is_adult": True,
                "collage_bytes_b64": (
                    __import__("base64").b64encode(collage_bytes_val).decode()
                    if collage_bytes_val else None
                ),
            },
            priority=QueuePriority.HIGH,
        )
    finally:
        await redis_client.aclose()

    logger.info("morning_brief.adult_generated", user_id=str(user.id), brief_id=brief_id)
    return {"brief_id": brief_id}


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

    # Проверить должен ли прийти бриф сегодня
    from core.permissions import get_effective_plan, is_brief_day as _is_brief_day
    _effective_plan = get_effective_plan(user)
    if not _is_brief_day(_effective_plan, user.timezone or "Europe/Vilnius"):
        logger.info("brief.skipped_not_brief_day",
            user_id=str(user_id), plan=_effective_plan)
        return {}

    is_adult_brief = user.segment not in ("mom_girl", "mom_boy")

    if is_adult_brief:
        return await _generate_adult_brief(user, payload)

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

    child_briefs = []
    all_outfit_ids: list[str] = []
    all_outfit_slots: list[dict] = []
    any_wow = False
    global_warnings: list[str] = []

    _slot_order = ["outerwear", "top", "bottom", "one_piece", "footwear", "hat", "tights"]
    _slot_labels = {
        "outerwear": "куртку", "top": "верх", "bottom": "низ",
        "one_piece": "платье", "footwear": "обувь",
        "hat": "шапку", "tights": "колготки",
    }

    for child in children:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child.id, "child")

        if not items:
            child_briefs.append(f"👧 {child.name}: гардероб пуст. Добавь вещи!")
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
        if is_wow_outfit:
            any_wow = True

        _temp = temp_m if temp_m is not None else 10.0
        regime = get_temp_regime(_temp)
        colortype = getattr(child, "colortype", None) or "default"

        child_briefs.append(_format_child_block(
            child.name, day_type, outfit, outfit_score, is_wow=is_wow_outfit,
            temp=_temp, colortype=colortype, regime=regime,
        ))

        # Собираем outfit_slots для коллажа с плейсхолдерами
        # Маппинг ключей outfit → slot name (hat и socks маппятся на стандартные слоты)
        _outfit_key_to_slot = {
            "outerwear": "outerwear",
            "top":       "top",
            "bottom":    "bottom",
            "one_piece": "one_piece",
            "footwear":  "footwear",
            "hat":       "hat",
            "tights":    "tights",
            "socks":     "tights",
        }
        tights_needed = _needs_tights(outfit, _temp)
        seen_slots: set[str] = set()
        for outfit_key, slot in _outfit_key_to_slot.items():
            # Логические исключения
            if outfit_key in ("top", "bottom") and outfit.get("one_piece"):
                continue
            if outfit_key == "one_piece" and (outfit.get("top") or outfit.get("bottom")):
                continue
            # Не дублировать слот (socks и tights → один tights)
            if slot in seen_slots:
                continue
            if slot == "tights" and not tights_needed:
                continue

            item = outfit.get(outfit_key)
            if item and getattr(item, "show_in_collage", True):
                seen_slots.add(slot)
                all_outfit_slots.append({
                    "slot": slot,
                    "label": _format_item(item)[:20],
                    "photo_id": item.photo_id,
                    "photo_url": item.photo_url,
                    "has_item": True,
                })
            else:
                ph_label = get_placeholder_label(slot, colortype, regime)
                if ph_label is None:
                    continue  # слот не нужен при данной погоде
                seen_slots.add(slot)
                if " — " in ph_label:
                    color_part = ph_label.split(" — ", 1)[1]
                else:
                    color_part = "(нет в гардеробе)"
                short_label = _slot_labels.get(slot, slot)
                all_outfit_slots.append({
                    "slot": slot,
                    "short_label": short_label,
                    "label": color_part,
                    "photo_id": None,
                    "photo_url": None,
                    "has_item": False,
                })

    # ── Заголовок с погодой ──────────────────────────────────────────────
    weather_line = ""
    if temp_m is not None:
        sm = "+" if temp_m >= 0 else ""
        se = "+" if (temp_e or 0) >= 0 else ""
        weather_line = f"{user.city}: {sm}{temp_m}°C → вечером {se}{temp_e}°C"
    else:
        logger.warning("brief.weather.empty", city=user.city)

    header = f"🌅 Доброе утро, {user.name}!\n"
    if weather_line:
        header += f"🌡 {weather_line}\n"
    for warn in global_warnings:
        header += f"{warn}\n"

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
                "outfit_slots": all_outfit_slots,
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
    import base64 as _b64

    telegram_id = payload["telegram_id"]
    text = payload["text"]
    brief_id = payload["brief_id"]
    is_adult = payload.get("is_adult", False)

    reply_markup = {
        "inline_keyboard": [[
            {"text": "👍 Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
            {"text": "👎 Другое", "callback_data": f"brief_feedback:down:{brief_id}"},
        ]]
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            collage_bytes = None

            if is_adult:
                # Взрослый бриф: коллаж уже собран и закодирован в base64
                collage_b64 = payload.get("collage_bytes_b64")
                if collage_b64:
                    try:
                        collage_bytes = _b64.b64decode(collage_b64)
                    except Exception as e:
                        logger.warning("morning_brief.adult.decode_failed", error=str(e))
            else:
                # Детский бриф: собираем коллаж из outfit_slots или photo_ids
                collage_photo_ids = payload.get("collage_photo_ids", [])
                collage_labels = payload.get("collage_labels", [])
                collage_photo_urls = payload.get("collage_photo_urls")

                outfit_slots = payload.get("outfit_slots")
                if outfit_slots:
                    try:
                        from services.image_builder import build_collage
                        collage_bytes = await build_collage(outfit_slots=outfit_slots)
                    except Exception as e:
                        logger.warning("morning_brief.collage_failed", error=str(e))
                elif collage_photo_ids:
                    try:
                        from services.image_builder import build_collage
                        collage_bytes = await build_collage(
                            photo_ids=collage_photo_ids,
                            labels=collage_labels,
                            photo_urls=collage_photo_urls,
                        )
                    except Exception as e:
                        logger.warning("morning_brief.collage_failed", error=str(e))

            if collage_bytes:
                # Отправляем фото с caption и кнопками
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
