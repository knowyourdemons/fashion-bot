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

# ── Реэкспорт из сервисных модулей (backward compat для тестов) ────────────
from services.brief_weather import _SEASONS, _geocode_city, _get_weather
from services.outfit_selector import _get_temp_regime, _select_outfit
from services.brief_formatter import _format_item, _format_child_block

logger = structlog.get_logger()


# ── [Функции перенесены в services/] ────────────────────────────────────────
# _SEASONS, _geocode_city, _get_weather  → services/brief_weather.py
# _get_temp_regime, _select_outfit       → services/outfit_selector.py
# _format_item, _format_child_block      → services/brief_formatter.py
# Реэкспорт выше сохраняет backward compatibility для тестов.


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
    from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
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
            f"используя вещи из гардероба. Говори на русском, тон дружелюбный. "
            f"Не используй markdown символы (# * _ и т.д.). Только обычный текст."
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
            f"Рекомендуй {color_hint}. Говори на русском, тон дружелюбный. "
            f"Не используй markdown символы (# * _ и т.д.). Только обычный текст."
        )

    try:
        pool = get_anthropic_pool()
    except RuntimeError:
        _redis_for_pool = aioredis.from_url(settings.redis_url, decode_responses=False)
        init_anthropic_pool(_redis_for_pool)
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
            if outfit_key in ("top", "bottom") and outfit.get("one_piece"):
                continue
            if outfit_key == "one_piece" and (outfit.get("top") or outfit.get("bottom")):
                continue
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
                    continue
                seen_slots.add(slot)
                color_part = ph_label.split(" — ", 1)[1] if " — " in ph_label else "(нет в гардеробе)"
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

    # Берём вещи из БД по all_outfit_ids для коллажа
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

        collage_photo_urls: list[str | None] = []
        for item in collage_items_db:
            collage_photo_ids.append(item.photo_id)
            collage_labels.append(item.type)
            collage_photo_urls.append(item.photo_url)
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
