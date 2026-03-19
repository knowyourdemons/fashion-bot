"""
Morning Brief задача:
- schedule_all(): каждый час ищет юзеров у кого 07:00 + engagement push + тизеры
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
from worker.tasks.style_config import get_temp_regime
from services.outfit_builder import build_outfit_slots, get_collage_params

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
    teaser_count = 0

    try:
        from sqlalchemy import or_
        from datetime import timezone as _tz
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

        # Тизеры для pure free-юзеров в не-бриф дни
        try:
            from core.permissions import is_brief_day as _ibd_t
            from sqlalchemy import or_ as _or2
            async with AsyncReadSession() as session:
                free_result = await session.execute(
                    select(User).where(
                        User.onboarding_completed.is_(True),
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                        User.plan == "free",
                        User.trial_ends_at.is_(None),
                    )
                )
                free_users = list(free_result.scalars().all())

            for free_user in free_users:
                try:
                    tz = pytz.timezone(free_user.timezone or "Europe/Vilnius")
                    if datetime.now(tz).hour != 7:
                        continue
                    if _ibd_t("free", free_user.timezone or "Europe/Vilnius"):
                        continue  # бриф день → не тизер
                    teaser_lock = f"lock:teaser:{free_user.id}:{date.today().isoformat()}"
                    acquired = await redis_client.set(teaser_lock, 1, ex=86400, nx=True)
                    if not acquired:
                        continue
                    await queue.push(
                        "send_teaser",
                        {"user_id": str(free_user.id)},
                        priority=QueuePriority.LOW,
                    )
                    teaser_count += 1
                except Exception as e:
                    logger.warning("teaser.schedule.user_error", user_id=str(free_user.id), error=str(e))
        except Exception as e:
            logger.warning("teaser.schedule.error", error=str(e))

        # Engagement push для юзеров с trial
        try:
            async with AsyncReadSession() as session:
                trial_result = await session.execute(
                    select(User).where(
                        User.onboarding_completed.is_(True),
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                        User.trial_started_at.isnot(None),
                    )
                )
                trial_users = list(trial_result.scalars().all())

            for trial_user in trial_users:
                try:
                    tz = pytz.timezone(trial_user.timezone or "Europe/Vilnius")
                    if datetime.now(tz).hour != 10:
                        continue
                    eng_lock = f"lock:engagement_check:{trial_user.id}:{date.today().isoformat()}"
                    if not await redis_client.set(eng_lock, 1, ex=86400, nx=True):
                        continue
                    await queue.push(
                        "check_engagement",
                        {"user_id": str(trial_user.id)},
                        priority=QueuePriority.LOW,
                    )
                except Exception as e:
                    logger.warning("engagement.schedule.user_error", user_id=str(trial_user.id), error=str(e))
        except Exception as e:
            logger.warning("engagement.schedule.error", error=str(e))
    finally:
        await redis_client.aclose()

    logger.info("morning_brief.schedule_all", count=count, teaser_count=teaser_count, hour=datetime.utcnow().hour)


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
        slot_order = ["outerwear", "top", "bottom", "one_piece", "footwear"]
        seen_cg: set = set()
        outfit: dict = {}
        for item in sorted(items, key=lambda x: float(x.score_item or 0), reverse=True):
            cg = item.category_group
            if cg not in seen_cg and cg in slot_order:
                outfit[cg] = item
                seen_cg.add(cg)
        outfit_slots = build_outfit_slots(outfit, child=None, temp=temp_m)

    # Заголовок коллажа для взрослых
    precip_e_adult = weather.get("precip_evening", 0)
    _collage_params = get_collage_params(user=user, temp=temp_m, precip=precip_e_adult or 0)
    collage_header = _collage_params["header_text"]

    collage_bytes_val = None
    if outfit_slots:
        try:
            collage_bytes_val = await build_collage(
                outfit_slots=outfit_slots,
                theme=_collage_params["theme"],
                header_text=collage_header,
            )
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
        internal_score = round(sum(scored) / len(scored), 1) if scored else 0.0

        # WOW детектор
        is_wow_outfit = bool(scored and sum(scored) / len(scored) >= 8.0)
        if is_wow_outfit:
            any_wow = True

        _temp = temp_m if temp_m is not None else 10.0
        regime = get_temp_regime(_temp)
        colortype = getattr(child, "colortype", None) or "default"

        # Получить матрицу для тона и wow-сообщений
        from services.scoring import matrix_name_for_owner
        from db.base import AsyncReadSession as _ARS
        from db.models.scoring_matrix import ScoringMatrix as _SM
        from sqlalchemy import select as _select
        _matrix_name = matrix_name_for_owner(user, child)
        _matrix = None
        try:
            async with _ARS() as _sess:
                _res = await _sess.execute(
                    _select(_SM).where(_SM.name == _matrix_name, _SM.is_active.is_(True))
                )
                _matrix = _res.scalar_one_or_none()
        except Exception:
            pass

        _tone = (_matrix.criteria.get("_tone") or "") if _matrix else ""
        _wow_msgs = (_matrix.criteria.get("_wow_messages") or []) if _matrix else []

        # Сгенерировать текстовый комментарий через Haiku
        from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
        import redis.asyncio as _aioredis
        try:
            _pool = get_anthropic_pool()
        except RuntimeError:
            _r = _aioredis.from_url(settings.redis_url, decode_responses=False)
            init_anthropic_pool(_r)
            _pool = get_anthropic_pool()

        from services.scoring_comment import generate_outfit_comment
        child_age = (date.today() - child.birthdate).days // 365
        weather_str = f"{temp_m:.0f}°C" if temp_m is not None else ""
        outfit_comment = await generate_outfit_comment(
            pool=_pool,
            outfit_items=[f"{i.type} {i.color}" for i in outfit["all_items"]],
            weather=weather_str,
            context=day_type,
            score=internal_score,
            is_wow=is_wow_outfit,
            child_name=child.name,
            gender=getattr(child, "gender", None),
            age=child_age,
            tone=_tone,
            wow_messages=_wow_msgs,
        )

        child_briefs.append(_format_child_block(
            child.name, day_type, outfit, outfit_comment,
            temp=_temp, colortype=colortype, regime=regime,
        ))

        # Собираем outfit_slots для коллажа
        child_slots = build_outfit_slots(
            outfit, child=child, temp=_temp, colortype=colortype, regime=regime
        )
        all_outfit_slots.extend(child_slots)

        # Критическое предупреждение при морозе без тёплой одежды
        if _temp is not None and _temp <= 0:
            has_warm = any(
                s["slot"] == "outerwear" and s.get("has_item")
                for s in child_slots
            )
            if not has_warm:
                global_warnings.append(
                    f"⚠️ На улице {_temp:.0f}°C — в гардеробе нет тёплой верхней одежды!"
                )

    # ── Заголовок с погодой ──────────────────────────────────────────────
    weather_line = ""
    if temp_m is not None:
        sm = "+" if temp_m >= 0 else ""
        se = "+" if (temp_e or 0) >= 0 else ""
        weather_line = f"{user.city}: {sm}{temp_m}°C → вечером {se}{temp_e}°C"
    else:
        logger.warning("brief.weather.empty", city=user.city)

    # Заголовок коллажа — берём из первого ребёнка
    _first_child = children[0] if children else None
    _collage_params = get_collage_params(
        child=_first_child, temp=temp_m, precip=precip_e or 0, day_type=day_type
    )
    collage_header = _collage_params["header_text"]
    collage_theme = _collage_params["theme"]

    header = f"🌅 Доброе утро, {user.name}!\n"
    if weather_line:
        header += f"🌡 {weather_line}\n"
    for warn in global_warnings:
        header += f"{warn}\n"

    # Trial degradation — уведомления
    _trial_notice = ""
    from core.permissions import get_trial_days_left as _gtdl
    _days_left = _gtdl(user)
    if _days_left is not None:
        if _days_left == 3:
            _trial_notice = "\n\n⏰ Осталось 3 дня Premium! Потом образы только вт/чт"
        elif _days_left == 2:
            _trial_notice = "\n\n⏰ Осталось 2 дня! Re-roll скоро станет недоступен"
        elif _days_left == 1:
            _trial_notice = "\n\n⏰ Последний день Premium — завтра базовый план"
        elif _days_left == 0:
            _trial_notice = "\n\n⏰ Это последний день Premium!"

    brief_text = (
        header
        + "\n\n"
        + "\n\n".join(child_briefs)
        + "\n\nКак тебе образ?"
        + _trial_notice
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
                "collage_header": collage_header,
                "collage_theme": collage_theme,
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
            {"text": "🔄 Переодень", "callback_data": f"reroll:{brief_id}"},
        ], [
            {"text": "📤 Переслать бабушке", "callback_data": f"share:{brief_id}"},
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
                collage_header = payload.get("collage_header", "")
                collage_theme = payload.get("collage_theme", "girl")

                outfit_slots = payload.get("outfit_slots")
                if outfit_slots:
                    try:
                        from services.image_builder import build_collage
                        collage_bytes = await build_collage(
                            outfit_slots=outfit_slots,
                            theme=collage_theme,
                            header_text=collage_header,
                        )
                    except Exception as e:
                        logger.warning("morning_brief.collage_failed", error=str(e))
                elif collage_photo_ids:
                    try:
                        from services.image_builder import build_collage
                        collage_bytes = await build_collage(
                            photo_ids=collage_photo_ids,
                            labels=collage_labels,
                            photo_urls=collage_photo_urls,
                            theme=collage_theme,
                            header_text=collage_header,
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


# ── Вечерний образ: schedule + task ───────────────────────────────────────

_EVENING_DAY_NAMES = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}
_EVENING_MONTH_NAMES = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


async def schedule_evening() -> None:
    """Каждый час отбирает premium-юзеров у кого сейчас 20:xx → пушит generate_evening_brief."""
    import redis.asyncio as aioredis
    from datetime import timedelta
    from sqlalchemy import select, or_
    from datetime import timezone as _tz
    from db.base import AsyncReadSession
    from db.models.user import User
    from core.queue import RedisQueue, QueuePriority
    from core.permissions import get_effective_plan, is_brief_day_tomorrow

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    queue = RedisQueue(redis_client)
    count = 0

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

        tomorrow_str = (date.today() + __import__("datetime").timedelta(days=1)).isoformat()

        for user in users:
            try:
                tz = pytz.timezone(user.timezone or "Europe/Vilnius")
                if datetime.now(tz).hour != 20:
                    continue
                effective_plan = get_effective_plan(user)
                if not is_brief_day_tomorrow(effective_plan, user.timezone or "Europe/Vilnius"):
                    continue
                lock_key = f"lock:evening_brief:{user.id}:{tomorrow_str}"
                acquired = await redis_client.set(lock_key, 1, ex=86400, nx=True)
                if not acquired:
                    continue
                await queue.push(
                    "generate_evening_brief",
                    {"user_id": str(user.id)},
                    priority=QueuePriority.LOW,
                )
                count += 1
            except Exception as e:
                logger.warning("evening_brief.schedule.user_error", user_id=str(user.id), error=str(e))
    finally:
        await redis_client.aclose()

    logger.info("evening_brief.schedule_all", count=count, hour=datetime.utcnow().hour)


@register("generate_evening_brief")
async def generate_evening_brief(payload: dict) -> dict:
    """Вечерний образ на завтра: погода(day=1) + гардероб → коллаж + push."""
    import uuid as _uuid
    from datetime import timedelta
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    import redis.asyncio as aioredis
    from db.base import AsyncWriteSession, AsyncReadSession
    from db.models.user import User
    from db.crud.wardrobe import get_owner_items
    from db.crud.brief_log import create_log
    from core.queue import RedisQueue, QueuePriority
    from core.permissions import get_effective_plan
    from services.weather import WeatherService

    user_id = _uuid.UUID(payload["user_id"])

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User)
            .options(selectinload(User.children))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()

    if not user:
        return {}

    # Погода на ЗАВТРА через wttr.in day=1
    tomorrow = date.today() + timedelta(days=1)
    temp_m: float = 15.0
    temp_e: float = 15.0
    precip_e: float = 0.0

    if user.city:
        try:
            redis_tmp = aioredis.from_url(settings.redis_url, decode_responses=False)
            svc = WeatherService(redis_tmp)
            w = await svc.get_forecast_day(user.city, day=1)
            await redis_tmp.aclose()
            temp_m = w["temp_morning"]
            temp_e = w["temp_evening"]
            precip_e = w.get("precip_evening", 0.0)
        except Exception as e:
            logger.warning("evening_brief.weather_failed", user_id=str(user_id), error=str(e))

    sm = "+" if temp_m >= 0 else ""
    weather_line = f"🌡 {user.city}: {sm}{temp_m:.0f}°C" if user.city else ""

    # Заголовок коллажа "Завтра, Пн 24 мар · +8°C"
    t_sign = "+" if temp_m >= 0 else ""
    t_str = f"{t_sign}{temp_m:.0f}°C"
    day_str = f"Завтра, {_EVENING_DAY_NAMES[tomorrow.weekday()]}, {tomorrow.day} {_EVENING_MONTH_NAMES[tomorrow.month]}"

    is_adult = user.segment not in ("mom_girl", "mom_boy")

    if is_adult:
        # ── Взрослый вечерний бриф ───────────────────────────────────────
        from worker.tasks.style_config import get_temp_regime as _gtr, COLORTYPE_PALETTES
        from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
        from services.image_builder import build_collage
        from services.outfit_builder import build_outfit_slots, get_collage_params

        regime = _gtr(temp_m)
        colortype = getattr(user, "colortype", None) or "default"

        async with AsyncReadSession() as session:
            items = await get_owner_items(session, user.id, "user")

        outer_advice = _REGIME_OUTER_ADVICE.get(regime, "куртка")
        if items:
            wardrobe_ctx = ", ".join(
                f"{i.type} {i.color}" for i in
                sorted(items, key=lambda x: float(x.score_item or 0), reverse=True)[:10]
            )
            prompt = (
                f"Завтра {sm}{temp_m:.0f}°C, {regime}. Цветотип: {colortype}. "
                f"Гардероб: {wardrobe_ctx}. "
                f"Дай короткий (2-3 предложения) совет по образу на завтра "
                f"используя вещи из гардероба. Русский язык, дружелюбный тон. Только обычный текст."
            )
        else:
            prompt = (
                f"Завтра {sm}{temp_m:.0f}°C, {regime}. Цветотип: {colortype}. "
                f"Дай короткий (2-3 предложения) совет по образу на завтра. "
                f"Русский язык, дружелюбный тон. Только обычный текст."
            )

        try:
            pool = get_anthropic_pool()
        except RuntimeError:
            _r = aioredis.from_url(settings.redis_url, decode_responses=False)
            init_anthropic_pool(_r)
            pool = get_anthropic_pool()

        try:
            resp = await pool.create_message(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            advice = resp.content[0].text.strip()
        except Exception as e:
            logger.warning("evening_brief.adult.haiku_failed", error=str(e))
            advice = f"Завтра {sm}{temp_m:.0f}°C — планируй {outer_advice} ✨"

        collage_header = f"{day_str} · {t_str}"
        brief_text = (
            f"🌙 Добрый вечер, {user.name}!\n"
            f"{weather_line}\n\n"
            f"🌅 Подготовила образ на завтра!\n{advice}"
        )

        # Коллаж из топ-вещей
        outfit_slots: list[dict] = []
        if items:
            slot_order = ["outerwear", "top", "bottom", "one_piece", "footwear"]
            seen_cg: set = set()
            outfit: dict = {}
            for item in sorted(items, key=lambda x: float(x.score_item or 0), reverse=True):
                cg = item.category_group
                if cg not in seen_cg and cg in slot_order:
                    outfit[cg] = item
                    seen_cg.add(cg)
            outfit_slots = build_outfit_slots(outfit, child=None, temp=temp_m)

        collage_bytes_val = None
        if outfit_slots:
            try:
                collage_bytes_val = await build_collage(
                    outfit_slots=outfit_slots,
                    theme="adult",
                    header_text=collage_header,
                )
            except Exception as e:
                logger.warning("evening_brief.adult.collage_failed", error=str(e))

        async with AsyncWriteSession() as session:
            log = await create_log(
                session,
                user_id=user.id,
                date=tomorrow,
                weather_summary=weather_line,
                outfit_description=brief_text,
                outfit_items=[],
                is_wow=False,
            )
            await session.commit()
            brief_id = str(log.id)

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
                priority=QueuePriority.LOW,
            )
        finally:
            await redis_client.aclose()

        logger.info("evening_brief.adult_generated", user_id=str(user_id), brief_id=brief_id)
        return {"brief_id": brief_id}

    # ── Детский вечерний бриф ────────────────────────────────────────────
    children = [c for c in (user.children or []) if c.deleted_at is None]
    if not children:
        return {}

    from services.outfit_selector import _select_outfit, _get_temp_regime
    from services.brief_formatter import _format_child_block
    from services.outfit_builder import build_outfit_slots, get_collage_params
    from services.image_builder import build_collage

    _SEASONS_MAP = _SEASONS
    today_real = date.today()
    month = today_real.month
    season = next(
        (s for s, months in _SEASONS_MAP.items() if month in months),
        "весна",
    )

    child_briefs: list[str] = []
    all_outfit_ids: list[str] = []
    all_outfit_slots: list[dict] = []
    any_wow = False

    for child in children:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child.id, "child")
        if not items:
            continue

        day_type = "садик" if tomorrow.weekday() < 5 else "прогулка"
        outfit = _select_outfit(items, season, tomorrow, temp_m, temp_e, precip_e)
        if not outfit:
            continue

        child_slots = build_outfit_slots(outfit, child=child, temp=temp_m)
        all_outfit_slots.extend(child_slots)
        outfit_ids = [str(v.id) for v in outfit.values() if hasattr(v, "id")]
        all_outfit_ids.extend(outfit_ids)

        child_brief = _format_child_block(child, outfit, temp_m)
        child_briefs.append(child_brief)
        if not any_wow:
            any_wow = False

    if not child_briefs:
        return {}

    # Заголовок коллажа с "Завтра"
    first_child = children[0]
    child_name = first_child.name
    if user.segment in ("mom_girl", "mom_boy"):
        collage_header = f"{day_str} · {t_str} · {child_name}"
    else:
        collage_header = f"{day_str} · {t_str}"

    child_gender = getattr(first_child, "gender", "girl")
    collage_theme = "boy" if child_gender == "boy" else "girl"

    brief_text = (
        f"🌙 Добрый вечер, {user.name}!\n"
        + (f"{weather_line}\n\n" if weather_line else "\n")
        + "🌅 Подготовила образ на завтра! Утром не нужно думать 😊\n\n"
        + "\n\n".join(child_briefs)
        + "\n\nКак тебе образ?"
    )

    async with AsyncWriteSession() as session:
        log = await create_log(
            session,
            user_id=user.id,
            date=tomorrow,
            weather_summary=weather_line,
            outfit_description="\n\n".join(child_briefs),
            outfit_items=all_outfit_ids,
            is_wow=any_wow,
        )
        await session.commit()
        brief_id = str(log.id)

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
                "collage_photo_ids": [],
                "collage_labels": [],
                "collage_photo_urls": [],
                "collage_header": collage_header,
                "collage_theme": collage_theme,
            },
            priority=QueuePriority.LOW,
        )
    finally:
        await redis_client.aclose()

    logger.info(
        "evening_brief.child_generated",
        user_id=str(user_id),
        brief_id=brief_id,
        children=len(children),
    )
    return {"brief_id": brief_id}


@register("send_teaser")
async def send_teaser(payload: dict) -> dict:
    """Тизер для free-юзеров в не-бриф дни — поддерживать engagement."""
    import uuid as _uuid
    from sqlalchemy import select as _sel
    from sqlalchemy.orm import selectinload as _sl
    from db.base import AsyncReadSession
    from db.models.user import User
    import redis.asyncio as aioredis

    user_id = _uuid.UUID(payload["user_id"])

    async with AsyncReadSession() as session:
        result = await session.execute(
            _sel(User)
            .options(_sl(User.children))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()

    if not user:
        return {}

    # Не спамить: Redis lock
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    try:
        teaser_key = f"teaser_sent:{user.id}:{date.today().isoformat()}"
        sent = await redis_client.exists(teaser_key)
        if sent:
            return {}
        await redis_client.set(teaser_key, "1", ex=86400)

        children = [c for c in (user.children or []) if c.deleted_at is None]
        child = children[0] if children else None
        child_name = child.name if child else None

        # Погода (без сбоя если недоступна)
        temp_str = ""
        if user.city:
            try:
                from services.weather import WeatherService
                svc = WeatherService(redis_client)
                wd = await svc.get(user.city)
                sm = "+" if wd.temp_c >= 0 else ""
                temp_str = f"{sm}{wd.temp_c}°C"
            except Exception:
                pass

        import random as _rand
        if child_name:
            teasers = [
                f"Касси здесь! Есть идея образа для {child_name} на сегодня ✨\n"
                "Образы каждый день — в Premium",
                f"Сегодня {'(' + temp_str + ')' if temp_str else ''} знаю что надеть {child_name}! 🌤\n"
                "Ежедневные образы доступны в Premium",
                f"Видела новые вещи в гардеробе — могу собрать разные образы для {child_name}!\n"
                "В Premium — образ каждое утро 🌅",
            ]
        else:
            teasers = [
                "Касси здесь! Сегодня есть идея образа для тебя ✨\n"
                "Образы каждый день — в Premium",
                f"{'(' + temp_str + ') ' if temp_str else ''}Знаю что надеть сегодня! 🌤\n"
                "Ежедневные образы доступны в Premium",
            ]

        teaser_text = _rand.choice(teasers)

        from config import settings as _settings
        from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
        bot = Bot(token=_settings.telegram_bot_token)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Попробовать Premium", callback_data="show_upgrade"),
        ]])
        await bot.send_message(
            chat_id=user.telegram_id,
            text=teaser_text,
            reply_markup=keyboard,
        )
        logger.info("teaser.sent", user_id=str(user.id))
    except Exception as e:
        logger.warning("teaser.failed", user_id=str(user.id), error=str(e))
    finally:
        await redis_client.aclose()

    return {}
