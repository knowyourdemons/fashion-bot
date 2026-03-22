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
from services.brief_formatter import _format_item, _format_child_block, format_weather_line
from services.brief_card import build_brief_card, get_brief_buttons, _get_segment, _count_real_photos

logger = structlog.get_logger()

# ── [Функции перенесены в services/] ────────────────────────────────────────
# _SEASONS, _geocode_city, _get_weather  → services/brief_weather.py
# _get_temp_regime, _select_outfit       → services/outfit_selector.py
# _format_item, _format_child_block      → services/brief_formatter.py
# Реэкспорт выше сохраняет backward compatibility для тестов.


# ── Cron: schedule_all ─────────────────────────────────────────────────────

async def schedule_all() -> None:
    """Каждый час отбирает юзеров у кого сейчас 07:00 → пушит generate_brief."""
    from sqlalchemy import select
    from db.base import AsyncReadSession
    from db.models.user import User
    from core.queue import RedisQueue, QueuePriority
    from core.redis import get_redis

    redis_client = get_redis()
    queue = RedisQueue(redis_client)
    count = 0
    teaser_count = 0

    _BATCH = 500

    try:
        from sqlalchemy import or_
        from datetime import timezone as _tz

        today_str = date.today().isoformat()
        offset = 0
        users_batch: list = [None]  # sentinel to enter loop

        while users_batch:
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
                    ).order_by(User.id).offset(offset).limit(_BATCH)
                )
                users_batch = list(result.scalars().all())
            offset += _BATCH

            for user in users_batch:
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
            from datetime import timezone as _tz2

            _t_offset = 0
            _t_batch: list = [None]
            while _t_batch:
                async with AsyncReadSession() as session:
                    free_result = await session.execute(
                        select(User).where(
                            User.onboarding_completed.is_(True),
                            User.is_active.is_(True),
                            User.deleted_at.is_(None),
                            User.plan == "free",
                            _or2(
                                User.trial_ends_at.is_(None),
                                User.trial_ends_at <= datetime.now(_tz2.utc),
                            ),
                        ).order_by(User.id).offset(_t_offset).limit(_BATCH)
                    )
                    _t_batch = list(free_result.scalars().all())
                _t_offset += _BATCH

                for free_user in _t_batch:
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
        pass  # singleton — не закрываем

    logger.info("morning_brief.schedule_all", count=count, teaser_count=teaser_count, hour=datetime.utcnow().hour)

    # ── 19:00 cold user reminders (day 1/2/3/5 after onboarding, 0 photos) ──
    await _send_cold_reminders(redis_client)


async def _send_cold_reminders(redis_client) -> None:
    """Send 19:00 reminders to users who completed onboarding but added 0 photos.

    Redis key: cold_reminder:{user_id} = JSON {onboarded_date, next_day, child_name}
    Schedule: day 1 (same day), day 2, day 3, day 5. After day 5 → delete.
    Any photo added → key deleted (in check_milestones / _analyze_and_save).
    """
    _REMINDER_DAYS = {1, 2, 3, 5}  # days after onboarding to send reminders

    try:
        from config import settings as _settings
        from telegram import Bot as _Bot
        from db.crud.wardrobe import get_owner_items

        _keys = []
        _cursor = b"0"
        while True:
            _cursor, _batch = await redis_client.scan(_cursor, match="cold_reminder:*", count=100)
            _keys.extend(_batch)
            if _cursor == b"0":
                break

        if not _keys:
            return

        _bot = _Bot(token=_settings.telegram_bot_token)

        for _rkey in _keys:
            try:
                _raw = await redis_client.get(_rkey)
                if not _raw:
                    continue
                import json as _json
                _data = _json.loads(_raw.decode() if isinstance(_raw, bytes) else _raw)
                _uid = uuid.UUID(_data["user_id"])
                _onboarded = date.fromisoformat(_data["onboarded_date"])
                _child_name = _data.get("child_name", "")
                _days_since = (date.today() - _onboarded).days

                # Past day 5 → stop reminding
                if _days_since > 5:
                    await redis_client.delete(_rkey)
                    continue

                # Not a reminder day
                if _days_since not in _REMINDER_DAYS:
                    continue

                # Check timezone: only send at 19:00 local
                async with AsyncReadSession() as _rs:
                    from sqlalchemy import select as _sel_r
                    _res_r = await _rs.execute(_sel_r(User).where(User.id == _uid))
                    _user_r = _res_r.scalar_one_or_none()
                if not _user_r:
                    await redis_client.delete(_rkey)
                    continue

                _tz_r = pytz.timezone(_user_r.timezone or "Europe/Vilnius")
                if datetime.now(_tz_r).hour != 19:
                    continue

                # Dedup: don't send twice on same day
                _dedup_key = f"cold_sent:{_uid}:{_days_since}"
                if not await redis_client.set(_dedup_key, "1", ex=86400, nx=True):
                    continue

                # Check: already has photos? Cancel all reminders.
                from db.crud.children import get_children as _gc_r
                async with AsyncReadSession() as _rs2:
                    _children_r = await _gc_r(_rs2, _user_r.id)
                _owner_id_r = _children_r[0].id if _children_r else _user_r.id
                _owner_type_r = "child" if _children_r else "user"
                async with AsyncReadSession() as _rs3:
                    _items_r = await get_owner_items(_rs3, _owner_id_r, _owner_type_r)
                if _items_r:
                    await redis_client.delete(_rkey)
                    continue

                # Build day-specific message
                _name = _child_name or getattr(_user_r, "name", "") or ""
                if _days_since == 1:
                    _text = (
                        f"Дома? Сфоткай 3 вещи{' ' + _name if _name else ''} — 2 минуты!\n"
                        "Завтра утром в 07:00 покажу готовый образ 📸"
                    )
                elif _days_since == 2:
                    _text = (
                        f"Привет! Вчера мы познакомились 👋\n"
                        f"Сфоткай 3 вещи{' ' + _name if _name else ''} — завтра утром покажу образ!"
                    )
                elif _days_since == 3:
                    # Get weather for personalized message
                    _temp_str = ""
                    try:
                        from services.brief_weather import _geocode_city, _get_weather
                        if _user_r.city:
                            _coords = await _geocode_city(_user_r.city)
                            if _coords:
                                _w = await _get_weather(_coords[0], _coords[1], _user_r.timezone or "Europe/Vilnius")
                                _t = _w.get("temp_morning")
                                if _t is not None:
                                    _s = "+" if _t >= 0 else ""
                                    _temp_str = f" при {_s}{_t:.0f}°"
                    except Exception:
                        pass
                    _text = (
                        f"{_name + ' з' if _name else 'З'}автра в садик{_temp_str}.\n"
                        "Сфоткай кофту и штаны — подберу образ! 📸"
                    )
                else:  # day 5
                    _text = (
                        "Касси скучает! 😊\n"
                        "Одна минута + 3 фото = образы каждый день.\n"
                        "📸 Сфоткай вещь или отправь фото из галереи!"
                    )

                await _bot.send_message(chat_id=_user_r.telegram_id, text=_text)
                logger.info("cold_reminder.sent", user_id=str(_uid), day=_days_since)

                # Day 5 was last → delete
                if _days_since >= 5:
                    await redis_client.delete(_rkey)

            except Exception as _re:
                logger.warning("cold_reminder.failed", error=str(_re))
    except Exception as _re2:
        logger.warning("cold_reminder.schedule_error", error=str(_re2))


# ── Evening brief comparison helper ────────────────────────────────────────

_WMO_PRECIP_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}


async def _check_evening_brief(user, today_weather: dict) -> dict | None:
    """Compare today's actual weather with yesterday evening's prediction.

    Returns dict with keys:
      - banner: str ("ok" | "changed")
      - text: str (banner text for the user)
      - evening_brief_id: str
      - evening_outfit_items: list[str]  (item IDs from evening brief)
      - delta_detail: str (what changed, if anything)
    Returns None if no evening brief exists.
    """
    from core.redis import get_redis
    redis = get_redis()

    today_str = date.today().isoformat()

    # Check if evening brief exists for today
    evening_brief_id_raw = None
    try:
        evening_brief_id_raw = await redis.get(f"evening_brief_id:{user.id}:{today_str}")
    except Exception:
        pass

    if not evening_brief_id_raw:
        return None

    evening_brief_id = evening_brief_id_raw.decode() if isinstance(evening_brief_id_raw, bytes) else evening_brief_id_raw

    # Load evening weather snapshot
    evening_weather_raw = None
    try:
        evening_weather_raw = await redis.get(f"evening_weather:{user.id}:{today_str}")
    except Exception:
        pass

    if not evening_weather_raw:
        return None

    evening_weather = json.loads(evening_weather_raw if isinstance(evening_weather_raw, str) else evening_weather_raw.decode())

    # Load evening brief outfit items
    evening_outfit_items: list[str] = []
    try:
        import uuid as _uuid_check
        from db.base import AsyncReadSession
        from db.models.brief_log import BriefLog
        from sqlalchemy import select as _sel_check

        async with AsyncReadSession() as session:
            _res = await session.execute(
                _sel_check(BriefLog).where(BriefLog.id == _uuid_check.UUID(evening_brief_id))
            )
            _log = _res.scalar_one_or_none()
            if _log and _log.outfit_items:
                evening_outfit_items = _log.outfit_items if isinstance(_log.outfit_items, list) else []
    except Exception:
        pass

    # Compare weather
    eve_temp_m = evening_weather.get("temp_morning", 0)
    now_temp_m = today_weather.get("temp_morning", 0)
    eve_precip = evening_weather.get("precip_max", 0)
    now_precip = today_weather.get("precip_max", 0)
    eve_wmo = evening_weather.get("wmo_morning", 0)
    now_wmo = today_weather.get("wmo_morning", 0)

    temp_delta = abs((now_temp_m or 0) - (eve_temp_m or 0))
    # Precipitation changed = one has precip WMO code and other doesn't
    eve_has_precip = eve_wmo in _WMO_PRECIP_CODES or eve_precip > 30
    now_has_precip = now_wmo in _WMO_PRECIP_CODES or now_precip > 30
    precip_changed = eve_has_precip != now_has_precip

    if temp_delta < 3 and not precip_changed:
        return {
            "banner": "ok",
            "text": "✅ Всё как планировали",
            "evening_brief_id": evening_brief_id,
            "evening_outfit_items": evening_outfit_items,
            "delta_detail": "",
        }
    else:
        details: list[str] = []
        if temp_delta >= 3:
            sign_eve = "+" if eve_temp_m >= 0 else ""
            sign_now = "+" if now_temp_m >= 0 else ""
            details.append(f"было {sign_eve}{eve_temp_m:.0f}°C → стало {sign_now}{now_temp_m:.0f}°C")
        if precip_changed:
            if now_has_precip and not eve_has_precip:
                details.append("появились осадки")
            elif eve_has_precip and not now_has_precip:
                details.append("осадки отменились")
        delta_str = ", ".join(details) if details else "прогноз обновился"

        return {
            "banner": "changed",
            "text": f"⚠️ Погода изменилась! {delta_str}",
            "evening_brief_id": evening_brief_id,
            "evening_outfit_items": evening_outfit_items,
            "delta_detail": delta_str,
        }


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
    from core.redis import get_redis
    from db.base import AsyncWriteSession, AsyncReadSession
    from db.crud.wardrobe import get_owner_items
    from db.crud.brief_log import create_log
    from core.queue import RedisQueue, QueuePriority
    from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
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

    # ── Check evening brief from yesterday ─────────────────────────────
    evening_check = await _check_evening_brief(user, weather)
    _evening_banner = ""
    if evening_check:
        _evening_banner = evening_check["text"]
        logger.info(
            "brief.adult.evening_check",
            banner=evening_check["banner"],
            delta=evening_check.get("delta_detail", ""),
        )

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
        body_type = getattr(user, "body_type", None)
        body_hint = f" Тип фигуры: {body_type}." if body_type else ""
        prompt = (
            f"Погода: {sm}{temp_m:.0f}°C, {regime}. "
            f"Цветотип: {colortype}.{body_hint} "
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
        _redis_for_pool = get_redis()
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
        brief_text += f"{weather_line}\n"
    if _evening_banner:
        brief_text += f"\n{_evening_banner}\n"
    brief_text += f"\n💡 Идея на сегодня:\n{stylist_advice}"
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
    temp_d_adult = weather.get("temp_day")
    temp_now_adult = weather.get("temp_now")
    _collage_params = get_collage_params(user=user, temp=temp_m, temp_now=temp_now_adult, temp_day=temp_d_adult, temp_evening=temp_e, precip=precip_e_adult or 0)
    collage_header = _collage_params["header_text"]

    # ── Brief card (Jinja2 + Playwright) ──
    import base64 as _b64_adult
    brief_card_bytes = None

    if outfit_slots or not items:
        try:
            brief_card_bytes = await build_brief_card(
                user=user,
                child=None,
                outfit={},
                weather=weather,
                outfit_slots=outfit_slots,
                advice_text=stylist_advice,
                colortype=getattr(user, "colortype", "") or "",
            )
        except Exception as e:
            logger.warning("brief.adult.brief_card_failed", error=str(e))

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

    # Determine segment + real photos for button logic
    _adult_segment = _get_segment(user)
    _adult_real_photos = _count_real_photos(outfit_slots) if outfit_slots else 0

    # Push send task
    redis_client = get_redis()
    try:
        queue = RedisQueue(redis_client)
        _send_payload: dict = {
            "telegram_id": user.telegram_id,
            "text": brief_text,
            "brief_id": brief_id,
            "is_adult": True,
            "segment": _adult_segment,
            "real_photo_count": _adult_real_photos,
        }
        if brief_card_bytes:
            _send_payload["brief_card_b64"] = _b64_adult.b64encode(brief_card_bytes).decode()
        else:
            _send_payload["adult_has_outfit"] = bool(outfit_slots)

        await queue.push(
            "send_morning_brief",
            _send_payload,
            priority=QueuePriority.HIGH,
        )
    finally:
        pass  # singleton — не закрываем

    logger.info("morning_brief.adult_generated", user_id=str(user.id), brief_id=brief_id,
                has_brief_card=bool(brief_card_bytes))
    return {"brief_id": brief_id}


# ── Worker tasks ───────────────────────────────────────────────────────────

@register("generate_brief")
async def generate_brief(payload: dict) -> dict:
    """Генерирует Morning Brief: погода + гардероб → BriefLog → push send."""
    import uuid as _uuid
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from core.redis import get_redis
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

    # ── Check evening brief from yesterday ─────────────────────────────
    evening_check = await _check_evening_brief(user, weather)
    _evening_banner = ""
    if evening_check:
        _evening_banner = evening_check["text"]
        logger.info(
            "brief.child.evening_check",
            banner=evening_check["banner"],
            delta=evening_check.get("delta_detail", ""),
        )

    child_briefs = []
    all_outfit_ids: list[str] = []
    all_outfit_slots: list[dict] = []
    any_wow = False
    global_warnings: list[str] = []
    weather_card_bytes: bytes | None = None  # Mode B card

    for child in children:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child.id, "child")

        if not items:
            child_briefs.append(f"👧 {child.name}: гардероб пуст. Добавь вещи!")
            continue

        # ── Mode B check: мало реальных фото → погодная карточка ──
        real_photos = sum(
            1 for i in items
            if (getattr(i, "photo_url", None) or getattr(i, "photo_id", None))
            and getattr(i, "show_in_collage", True)
            and getattr(i, "category_group", "") != "underwear"
        )
        total_visible = sum(
            1 for i in items
            if getattr(i, "show_in_collage", True)
            and getattr(i, "category_group", "") != "underwear"
        )
        placeholder_ratio = 1 - (real_photos / max(total_visible, 1))

        if real_photos < 3 or placeholder_ratio > 0.5:
            # ── MODE B: погодная карточка ──
            from services.weather_card import build_weather_card, generate_weather_advice, season_palette
            from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
            from core.redis import get_redis as _get_redis_b

            try:
                _pool_b = get_anthropic_pool()
            except RuntimeError:
                _r_b = _get_redis_b()
                init_anthropic_pool(_r_b)
                _pool_b = get_anthropic_pool()

            temp_d = weather.get("temp_day") or temp_m
            precip_max = weather.get("precip_max", precip_e or 0)

            advice = await generate_weather_advice(
                pool=_pool_b,
                child_name=child.name,
                temp_morning=temp_m or 10.0,
                temp_day=temp_d,
                temp_evening=temp_e or temp_m or 10.0,
                precip_max=precip_max,
                day_type=day_type,
            )

            weather_card_bytes = build_weather_card(
                child_name=child.name,
                day_type=day_type,
                temp_morning=temp_m or 10.0,
                temp_day=temp_d,
                temp_evening=temp_e or temp_m or 10.0,
                precip_max=precip_max,
                advice_text=advice,
                items_count=len(items),
            )

            # Текстовый бриф для Mode B
            sm_b = "+" if (temp_m or 0) >= 0 else ""
            child_briefs.append(
                f"👧 {child.name} ({day_type}):\n"
                f"💬 {advice}"
            )

            logger.info(
                "brief.mode_b",
                child=child.name,
                real_photos=real_photos,
                total_visible=total_visible,
            )
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

        # ── Minimum outfit check: need top+bottom or one_piece ──
        from services.outfit_builder import has_minimum_outfit as _has_min
        if not _has_min(outfit):
            _has_top = any(i.category_group == "top" for i in items)
            _has_bottom = any(i.category_group == "bottom" for i in items)
            if not _has_top and not _has_bottom:
                _cta_brief = "Сфоткай кофту и штанишки — соберу образ!"
            elif not _has_top:
                _cta_brief = "Сфоткай кофту или футболку — соберу образ!"
            else:
                _cta_brief = "Сфоткай штаны или юбку — соберу образ!"
            child_briefs.append(
                f"👧 {child.name}: пока мало вещей для полного образа. {_cta_brief} 📸"
            )
            # Still go to Mode B (weather card) path
            from services.weather_card import build_weather_card, generate_weather_advice, season_palette
            from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
            from core.redis import get_redis as _get_redis_min

            try:
                _pool_min = get_anthropic_pool()
            except RuntimeError:
                _r_min = _get_redis_min()
                init_anthropic_pool(_r_min)
                _pool_min = get_anthropic_pool()

            temp_d = weather.get("temp_day") or temp_m
            precip_max = weather.get("precip_max", precip_e or 0)

            advice = await generate_weather_advice(
                pool=_pool_min,
                child_name=child.name,
                temp_morning=temp_m or 10.0,
                temp_day=temp_d,
                temp_evening=temp_e or temp_m or 10.0,
                precip_max=precip_max,
                day_type=day_type,
            )

            weather_card_bytes = build_weather_card(
                child_name=child.name,
                day_type=day_type,
                temp_morning=temp_m or 10.0,
                temp_day=temp_d,
                temp_evening=temp_e or temp_m or 10.0,
                precip_max=precip_max,
                advice_text=advice,
                items_count=len(items),
            )

            child_briefs[-1] = (
                f"👧 {child.name} ({day_type}):\n"
                f"💬 {advice}\n"
                f"📸 {_cta_brief}"
            )
            continue

        # ── AI Outfit Engine v2 ──
        _temp = temp_m if temp_m is not None else 10.0
        colortype = getattr(child, "colortype", None) or "default"

        from services.outfit_engine import select_outfit_ai
        from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
        from core.redis import get_redis as _get_redis
        try:
            _pool = get_anthropic_pool()
        except RuntimeError:
            _r = _get_redis()
            init_anthropic_pool(_r)
            _pool = get_anthropic_pool()

        # Fetch rotation history
        _recent_ids_brief: list[list[str]] = []
        try:
            from db.crud.brief_log import get_recent_outfit_item_ids as _get_rot
            async with AsyncReadSession() as _s_rot_b:
                _recent_ids_brief = await _get_rot(_s_rot_b, user.id, days=5)
        except Exception:
            pass

        child_age = (date.today() - child.birthdate).days // 365
        _engine_result = await select_outfit_ai(
            pool=_pool,
            items=items,
            season=season,
            today=today,
            temp_morning=_temp,
            temp_evening=temp_e or _temp,
            precip_evening=precip_e or 0,
            segment=getattr(user, "segment", "mom_girl"),
            child_name=child.name,
            child_age=child_age,
            child_gender=getattr(child, "gender", None),
            colortype=colortype,
            recent_outfit_ids=_recent_ids_brief,
            day_type=day_type,
            body_type=getattr(user, "body_type", None),
            redis=redis_client,
        )

        outfit = _engine_result.outfit
        outfit_comment = _engine_result.comment
        is_wow_outfit = _engine_result.is_wow

        all_outfit_ids.extend(str(i.id) for i in outfit["all_items"])
        if is_wow_outfit:
            any_wow = True

        # Gap insight: append tip if wardrobe is small (< 15 items)
        if len(items) < 15:
            from services.scoring import get_wardrobe_gaps
            _gaps = get_wardrobe_gaps(items)
            _gap_tips = [g for g in _gaps if "Добавь" in g]
            if _gap_tips:
                outfit_comment += f"\n\n💡 {_gap_tips[0]}"

        regime = get_temp_regime(_temp)

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
    temp_d = weather.get("temp_day")
    temp_now = weather.get("temp_now")
    if temp_now is not None or temp_m is not None:
        parts_w: list[str] = []
        if temp_now is not None:
            sn = "+" if temp_now >= 0 else ""
            parts_w.append(f"сейчас {sn}{round(temp_now)}°C")
        if temp_d is not None:
            sd = "+" if temp_d >= 0 else ""
            parts_w.append(f"днём {sd}{round(temp_d)}°C")
        if temp_e is not None:
            se = "+" if temp_e >= 0 else ""
            parts_w.append(f"вечером {se}{round(temp_e)}°C")
        weather_line = f"{user.city}: {', '.join(parts_w)}"
    else:
        logger.warning("brief.weather.empty", city=user.city)

    # Заголовок коллажа — берём из первого ребёнка
    _first_child = children[0] if children else None
    temp_now_child = weather.get("temp_now")
    _collage_params = get_collage_params(
        child=_first_child, temp=temp_m, temp_now=temp_now_child, temp_day=temp_d,
        temp_evening=temp_e, precip=precip_e or 0, day_type=day_type,
    )
    collage_header = _collage_params["header_text"]
    collage_theme = _collage_params["theme"]

    # Weather line с эмодзи для текстового брифа
    _DAY_NAMES_FULL = {0: "ПОНЕДЕЛЬНИК", 1: "ВТОРНИК", 2: "СРЕДА", 3: "ЧЕТВЕРГ", 4: "ПЯТНИЦА", 5: "СУББОТА", 6: "ВОСКРЕСЕНЬЕ"}
    _MONTH_NAMES_FULL = {1: "ЯНВАРЯ", 2: "ФЕВРАЛЯ", 3: "МАРТА", 4: "АПРЕЛЯ", 5: "МАЯ", 6: "ИЮНЯ", 7: "ИЮЛЯ", 8: "АВГУСТА", 9: "СЕНТЯБРЯ", 10: "ОКТЯБРЯ", 11: "НОЯБРЯ", 12: "ДЕКАБРЯ"}
    _day_name = _DAY_NAMES_FULL.get(today.weekday(), "")
    _date_str = f"{_day_name}, {today.day} {_MONTH_NAMES_FULL.get(today.month, '')}"

    _first_child_name = children[0].name if children else ""
    weather_emoji_line = format_weather_line(weather) if weather else ""

    header = f"<b>{_date_str}</b>\n<b>{_first_child_name}</b>, {day_type}\n"
    if weather_emoji_line:
        header += f"{weather_emoji_line}\n"

    # Weather alerts из services/weather.py (ветер, осадки, дельта вечера)
    if user.city:
        try:
            from services.weather import WeatherService
            from core.redis import get_redis as _get_redis_w
            _ws = WeatherService(_get_redis_w())
            _wd = await _ws.get(user.city)
            _weather_alerts = _wd.get_alerts()
            for _wa in _weather_alerts:
                global_warnings.append(_wa)
        except Exception:
            pass

    for warn in global_warnings:
        header += f"{warn}\n"

    # Evening brief comparison banner
    if _evening_banner:
        header += f"{_evening_banner}\n"

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

    # Утренний бриф = текст в порядке одевания, без коллажа
    brief_text = (
        header.rstrip()
        + "\n\n"
        + "\n\n".join(child_briefs)
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

    # ── PRIMARY: new brief_card with segment themes ──
    import base64 as _b64_brief
    _brief_card_bytes = None

    # Build advice text from child briefs
    _advice_for_card = ""
    if child_briefs:
        for _cb in child_briefs:
            if "\U0001f4ac" in _cb:  # 💬
                _parts = _cb.split("\U0001f4ac", 1)
                if len(_parts) > 1:
                    import re
                    _advice_for_card = re.sub(r"<[^>]+>", "", _parts[1].strip().split("\n")[0].strip())
                    break
        if not _advice_for_card:
            _t = temp_m or 10
            if _t < 5:
                _advice_for_card = f"На улице {'+' if _t >= 0 else ''}{_t:.0f}° -- одевайтесь теплее!"
            elif _t < 15:
                _advice_for_card = f"Прохладно {'+' if _t >= 0 else ''}{_t:.0f}° -- не забудьте куртку"
            else:
                _advice_for_card = "Хорошей прогулки!"

    # Собрать outfit для передачи в brief_card
    _first_outfit = {}
    _first_child = children[0] if children else None
    if all_outfit_slots or _first_child:
        try:
            for _ch in children:
                async with AsyncReadSession() as _s_out:
                    _ch_items = await get_owner_items(_s_out, _ch.id, "child")
                if _ch_items:
                    _first_outfit = _select_outfit(_ch_items, season, today, temp_m, temp_e, precip_e or 0)
                    break
        except Exception:
            pass

    try:
        _ct = getattr(_first_child, "colortype", "") if _first_child else getattr(user, "colortype", "")
        _brief_card_bytes = await build_brief_card(
            user=user,
            child=_first_child,
            outfit=_first_outfit,
            weather=weather,
            outfit_slots=all_outfit_slots,
            advice_text=_advice_for_card,
            colortype=_ct or "",
        )
        if _brief_card_bytes:
            logger.info("morning_brief.brief_card_ok", size=len(_brief_card_bytes))
    except Exception as _bc_err:
        logger.warning("morning_brief.brief_card_failed", error=str(_bc_err))

    redis_client = get_redis()
    try:
        queue = RedisQueue(redis_client)
        _child_segment = _get_segment(user)
        _child_real_photos = _count_real_photos(all_outfit_slots) if all_outfit_slots else 0
        # Find first missing slot for button CTA
        _first_missing = ""
        for _ms in all_outfit_slots:
            if not _ms.get("has_item") and _ms.get("slot") not in ("underwear", "tights", "socks", "base_layer"):
                _first_missing = _ms.get("label") or get_placeholder_label(
                    _ms.get("slot", "top"), _ms.get("gender", "girl"))
                break

        _payload: dict = {
            "telegram_id": user.telegram_id,
            "text": brief_text,
            "brief_id": brief_id,
            "segment": _child_segment,
            "real_photo_count": _child_real_photos,
            "first_missing_slot": _first_missing,
        }
        if _brief_card_bytes:
            _payload["brief_card_b64"] = _b64_brief.b64encode(_brief_card_bytes).decode()
        else:
            _payload["text_only"] = True
            _payload["parse_mode"] = "HTML"

        await queue.push(
            "send_morning_brief",
            _payload,
            priority=QueuePriority.HIGH,
        )
    finally:
        pass  # singleton — не закрываем

    _mode = "B" if weather_card_bytes else "A"
    logger.info(
        "morning_brief.generated",
        user_id=str(user_id),
        brief_id=brief_id,
        mode=_mode,
        outfit_ids_count=len(all_outfit_ids),
        collage_photos_count=len(collage_photo_ids),
    )

    # Growth alert — проверить размеры детей (inline, после брифа)
    try:
        from worker.tasks.growth_alert import _check_children_growth
        await _check_children_growth(user, children)
    except Exception as _ga_err:
        logger.warning("growth_alert.inline.error", error=str(_ga_err))

    return {"brief_id": brief_id}


@register("send_morning_brief")
async def send_morning_brief(payload: dict) -> dict:
    """Отправляет Morning Brief через Telegram Bot API (httpx)."""
    import base64 as _b64

    telegram_id = payload["telegram_id"]
    text = payload["text"]
    brief_id = payload["brief_id"]
    is_adult = payload.get("is_adult", False)
    is_text_only = payload.get("text_only", False)
    parse_mode = payload.get("parse_mode")

    is_brief_card = bool(payload.get("brief_card_b64"))
    is_weather_card = bool(payload.get("weather_card_b64"))

    adult_has_outfit = payload.get("adult_has_outfit", False)

    # ── New brief_card button logic ──
    _segment = payload.get("segment", "")
    _real_photo_count = payload.get("real_photo_count", 0)
    _first_missing = payload.get("first_missing_slot", "")

    if _segment and (is_brief_card or is_text_only):
        # Use new button logic from brief_card module
        reply_markup = get_brief_buttons(
            segment=_segment,
            real_photo_count=_real_photo_count,
            brief_id=brief_id,
            first_missing_slot=_first_missing,
        )
    elif is_weather_card:
        reply_markup = {
            "inline_keyboard": [[
                {"text": "Сфоткать", "callback_data": "add_items_hint"},
                {"text": "Потом", "callback_data": f"brief_feedback:later:{brief_id}"},
            ]]
        }
    elif is_adult and not adult_has_outfit:
        # Взрослый бриф без вещей — только совет (fallback)
        reply_markup = {
            "inline_keyboard": [[
                {"text": "Спасибо", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "Ещё совет", "callback_data": "reroll_advice"},
            ]]
        }
    elif is_adult:
        # Взрослый бриф с коллажем (fallback)
        reply_markup = {
            "inline_keyboard": [[
                {"text": "Нравится", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "Другой вариант", "callback_data": f"reroll:{brief_id}"},
            ], [
                {"text": "Переслать", "callback_data": f"share:{brief_id}"},
            ]]
        }
    elif is_text_only or is_brief_card:
        # Детский бриф (fallback)
        reply_markup = {
            "inline_keyboard": [[
                {"text": "Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "Переодень", "callback_data": f"reroll:{brief_id}"},
            ], [
                {"text": "Переслать", "callback_data": f"share:{brief_id}"},
            ]]
        }
    else:
        reply_markup = {
            "inline_keyboard": [[
                {"text": "👍 Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "🔄 Переодень", "callback_data": f"reroll:{brief_id}"},
            ], [
                {"text": "📤 Переслать", "callback_data": f"share:{brief_id}"},
            ]]
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Brief card mode — morning brief as Satori card image
            if is_brief_card:
                _bc_bytes = _b64.b64decode(payload["brief_card_b64"])
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto",
                    data={
                        "chat_id": telegram_id,
                        "reply_markup": json.dumps(reply_markup),
                    },
                    files={"photo": ("brief.png", _bc_bytes, "image/png")},
                )
                resp.raise_for_status()
                logger.info("morning_brief.sent_card", telegram_id=telegram_id, brief_id=brief_id)
                return {"sent": True}

            # Text-only fallback
            if is_text_only:
                _send_data: dict = {
                    "chat_id": telegram_id,
                    "text": text,
                    "reply_markup": json.dumps(reply_markup),
                }
                if parse_mode:
                    _send_data["parse_mode"] = parse_mode
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json=_send_data,
                )
                resp.raise_for_status()
                logger.info("morning_brief.sent_text", telegram_id=telegram_id, brief_id=brief_id)
                return {"sent": True}

            collage_bytes = None

            if is_weather_card:
                # Mode B: weather card PNG
                wc_b64 = payload.get("weather_card_b64")
                if wc_b64:
                    try:
                        collage_bytes = _b64.b64decode(wc_b64)
                    except Exception as e:
                        logger.warning("morning_brief.weather_card.decode_failed", error=str(e))
            elif is_adult:
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
                # Split delivery: фото без caption, текст отдельным сообщением
                _fname = "weather_card.png" if is_weather_card else "collage.jpg"
                _mime = "image/png" if is_weather_card else "image/jpeg"
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto",
                    data={
                        "chat_id": telegram_id,
                        "disable_notification": "true",
                    },
                    files={"photo": (_fname, collage_bytes, _mime)},
                )
                resp.raise_for_status()

                # Сохранить collage_file_id для возможности пересылки
                try:
                    tg_result = resp.json()
                    photos = tg_result.get("result", {}).get("photo", [])
                    if photos:
                        file_id = photos[-1]["file_id"]
                        import uuid as _uuid2
                        from db.base import AsyncWriteSession as _AWS
                        from db.crud.brief_log import update_collage_file_id as _ucfi
                        async with _AWS() as _s:
                            await _ucfi(_s, _uuid2.UUID(brief_id), file_id)
                            await _s.commit()
                except Exception as e:
                    logger.warning("morning_brief.save_file_id_failed", error=str(e))

                # Текст + кнопки — отдельное сообщение
                import asyncio as _asyncio
                await _asyncio.sleep(0.1)
                try:
                    text_resp = await client.post(
                        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                        json={"chat_id": telegram_id, "text": text, "reply_markup": reply_markup},
                    )
                    text_resp.raise_for_status()
                except Exception as e:
                    logger.warning("morning_brief.text_message_failed", error=str(e))
            else:
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": telegram_id, "text": text, "reply_markup": reply_markup},
                )
                resp.raise_for_status()

        logger.info("morning_brief.sent", telegram_id=telegram_id, brief_id=brief_id, has_collage=bool(collage_bytes))
        logger.info("metric.brief_sent",
            user_id=str(payload.get("user_id", telegram_id)),
            brief_type="morning",
            photo_count=payload.get("real_photo_count", 0),
        )
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
    from core.redis import get_redis
    from datetime import timedelta
    from sqlalchemy import select, or_
    from datetime import timezone as _tz
    from db.base import AsyncReadSession
    from db.models.user import User
    from core.queue import RedisQueue, QueuePriority
    from core.permissions import get_effective_plan, is_brief_day_tomorrow

    redis_client = get_redis()
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
                # Trial degradation: skip evening brief in last day
                from core.permissions import get_effective_limits as _gel
                if not _gel(user).get("evening_brief", True):
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
        pass  # singleton — не закрываем

    logger.info("evening_brief.schedule_all", count=count, hour=datetime.utcnow().hour)


@register("generate_evening_brief")
async def generate_evening_brief(payload: dict) -> dict:
    """Вечерний бриф на ЗАВТРА: погода(Open-Meteo day+1) + гардероб → brief_card + push.

    Сохраняет weather snapshot в Redis для утреннего сравнения.
    """
    import uuid as _uuid
    import base64 as _b64
    from datetime import timedelta
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from core.redis import get_redis
    from db.base import AsyncWriteSession, AsyncReadSession
    from db.models.user import User
    from db.crud.wardrobe import get_owner_items
    from db.crud.brief_log import create_log
    from core.queue import RedisQueue, QueuePriority
    from core.permissions import get_effective_plan
    from services.brief_weather import _geocode_city, _get_weather_tomorrow, wmo_to_emoji

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

    tomorrow = date.today() + timedelta(days=1)

    # ── Погода на ЗАВТРА через Open-Meteo ──────────────────────────────
    coords = await _geocode_city(user.city or "")
    weather: dict = {}
    if coords:
        weather = await _get_weather_tomorrow(
            coords[0], coords[1], user.timezone or "Europe/Vilnius"
        )

    temp_m = weather.get("temp_morning") or 15.0
    temp_e = weather.get("temp_evening") or temp_m
    temp_d = weather.get("temp_day") or temp_m
    precip_e = weather.get("precip_evening", 0)
    precip_max = weather.get("precip_max", 0)
    wmo_m = weather.get("wmo_morning", 0)

    sm = "+" if temp_m >= 0 else ""

    # ── Сохранить weather snapshot в Redis для утреннего сравнения ──────
    redis_client = get_redis()
    _evening_weather_key = f"evening_weather:{user.id}:{tomorrow.isoformat()}"
    try:
        await redis_client.set(
            _evening_weather_key,
            json.dumps({
                "temp_morning": temp_m,
                "temp_day": temp_d,
                "temp_evening": temp_e,
                "precip_max": precip_max,
                "wmo_morning": wmo_m,
            }),
            ex=86400,
        )
    except Exception:
        pass

    # ── Заголовок "ЗАВТРА" ─────────────────────────────────────────────
    t_sign = "+" if temp_m >= 0 else ""
    t_str = f"{t_sign}{temp_m:.0f}°C"
    day_str = f"ЗАВТРА, {_EVENING_DAY_NAMES[tomorrow.weekday()]}, {tomorrow.day} {_EVENING_MONTH_NAMES[tomorrow.month]}"

    # Weather line with emoji
    weather_emoji = wmo_to_emoji(wmo_m)
    weather_parts: list[str] = []
    if temp_m is not None:
        weather_parts.append(f"утром {sm}{temp_m:.0f}°C")
    if temp_d is not None:
        sd = "+" if temp_d >= 0 else ""
        weather_parts.append(f"днём {sd}{temp_d:.0f}°C")
    if temp_e is not None:
        se = "+" if temp_e >= 0 else ""
        weather_parts.append(f"вечером {se}{temp_e:.0f}°C")
    weather_line = f"{weather_emoji} {user.city}: {', '.join(weather_parts)}" if user.city and weather_parts else ""

    is_adult = user.segment not in ("mom_girl", "mom_boy")

    if is_adult:
        # ── Взрослый вечерний бриф ───────────────────────────────────────
        from worker.tasks.style_config import get_temp_regime as _gtr, COLORTYPE_PALETTES
        from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
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
            _r = get_redis()
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
            advice = f"Завтра {sm}{temp_m:.0f}°C — планируй {outer_advice}"

        brief_text = (
            f"🌙 Добрый вечер, {user.name}!\n"
            f"<b>{day_str}</b>\n"
            f"{weather_line}\n\n"
            f"🌅 Подготовила образ на завтра!\n{advice}"
        )

        # Outfit из топ-вещей
        outfit_slots: list[dict] = []
        outfit_dict: dict = {}
        if items:
            slot_order = ["outerwear", "top", "bottom", "one_piece", "footwear"]
            seen_cg: set = set()
            for item in sorted(items, key=lambda x: float(x.score_item or 0), reverse=True):
                cg = item.category_group
                if cg not in seen_cg and cg in slot_order:
                    outfit_dict[cg] = item
                    seen_cg.add(cg)
            outfit_slots = build_outfit_slots(outfit_dict, child=None, temp=temp_m)

        # ── Build brief_card (Satori) ──
        brief_card_bytes = None
        try:
            brief_card_bytes = await build_brief_card(
                user=user,
                child=None,
                outfit=outfit_dict,
                weather=weather,
                outfit_slots=outfit_slots,
                advice_text=advice,
                colortype=getattr(user, "colortype", "") or "",
            )
        except Exception as e:
            logger.warning("evening_brief.adult.brief_card_failed", error=str(e))

        # Save BriefLog for tomorrow's date
        outfit_ids = [str(v.id) for v in outfit_dict.values() if hasattr(v, "id")]
        async with AsyncWriteSession() as session:
            log = await create_log(
                session,
                user_id=user.id,
                date=tomorrow,
                weather_summary=weather_line,
                outfit_description=brief_text,
                outfit_items=outfit_ids,
                is_wow=False,
            )
            await session.commit()
            brief_id = str(log.id)

        # Store evening brief_id in Redis for morning reference
        try:
            await redis_client.set(
                f"evening_brief_id:{user.id}:{tomorrow.isoformat()}",
                brief_id,
                ex=86400,
            )
        except Exception:
            pass

        _segment = _get_segment(user)
        _real_photos = _count_real_photos(outfit_slots) if outfit_slots else 0

        try:
            queue = RedisQueue(redis_client)
            _send_payload: dict = {
                "telegram_id": user.telegram_id,
                "text": brief_text,
                "brief_id": brief_id,
                "is_adult": True,
                "is_evening": True,
                "segment": _segment,
                "real_photo_count": _real_photos,
            }
            if brief_card_bytes:
                _send_payload["brief_card_b64"] = _b64.b64encode(brief_card_bytes).decode()
            else:
                _send_payload["text_only"] = True
                _send_payload["parse_mode"] = "HTML"

            await queue.push(
                "send_morning_brief",
                _send_payload,
                priority=QueuePriority.LOW,
            )
        finally:
            pass  # singleton — не закрываем

        logger.info("evening_brief.adult_generated", user_id=str(user_id), brief_id=brief_id)
        return {"brief_id": brief_id}

    # ── Детский вечерний бриф ────────────────────────────────────────────
    children = [c for c in (user.children or []) if c.deleted_at is None]
    if not children:
        return {}

    from services.outfit_selector import _select_outfit as _sel_outfit_eve
    from services.brief_formatter import _format_child_block
    from services.outfit_builder import build_outfit_slots as _bos_eve, get_collage_params

    season = _SEASONS[tomorrow.month]

    child_briefs: list[str] = []
    all_outfit_ids: list[str] = []
    all_outfit_slots: list[dict] = []
    any_wow = False
    _first_outfit_eve: dict = {}

    for child in children:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child.id, "child")
        if not items:
            continue

        day_type = "садик" if tomorrow.weekday() < 5 else "прогулка"

        # ── AI Outfit Engine v2 for evening push ──
        from services.outfit_engine import select_outfit_ai as _sel_ai_eve
        from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
        try:
            _pool_ch = get_anthropic_pool()
        except RuntimeError:
            init_anthropic_pool(redis_client)
            _pool_ch = get_anthropic_pool()

        child_age = (date.today() - child.birthdate).days // 365 if child.birthdate else None
        _eve_result = await _sel_ai_eve(
            pool=_pool_ch,
            items=items,
            season=season,
            today=tomorrow,
            temp_morning=temp_m or 10.0,
            temp_evening=temp_e or temp_m or 10.0,
            precip_evening=precip_e or 0,
            segment=getattr(user, "segment", "mom_girl"),
            child_name=child.name,
            child_age=child_age,
            child_gender=getattr(child, "gender", None),
            colortype=getattr(child, "colortype", None) or "default",
            day_type=day_type,
            redis=redis_client,
        )

        outfit = _eve_result.outfit
        if not outfit:
            continue

        if not _first_outfit_eve:
            _first_outfit_eve = outfit

        child_slots = _bos_eve(outfit, child=child, temp=temp_m)
        all_outfit_slots.extend(child_slots)
        outfit_ids = [str(v.id) for v in outfit.get("all_items", []) if hasattr(v, "id")]
        all_outfit_ids.extend(outfit_ids)

        child_brief = _format_child_block(
            child.name, day_type, outfit, _eve_result.comment, temp=temp_m,
        )
        child_briefs.append(child_brief)

    if not child_briefs:
        return {}

    first_child = children[0]
    child_name = first_child.name

    brief_text = (
        f"🌙 Добрый вечер, {user.name}!\n"
        f"<b>{day_str}</b>\n"
        + (f"{weather_line}\n\n" if weather_line else "\n")
        + "🌅 Подготовила образ на завтра! Утром не нужно думать\n\n"
        + "\n\n".join(child_briefs)
    )

    # ── Build brief_card (Satori) ──
    _advice_eve = ""
    for _cb in child_briefs:
        if "\U0001f4ac" in _cb:
            _parts = _cb.split("\U0001f4ac", 1)
            if len(_parts) > 1:
                import re
                _advice_eve = re.sub(r"<[^>]+>", "", _parts[1].strip().split("\n")[0].strip())
                break

    brief_card_bytes = None
    try:
        _ct_eve = getattr(first_child, "colortype", "") if first_child else getattr(user, "colortype", "")
        brief_card_bytes = await build_brief_card(
            user=user,
            child=first_child,
            outfit=_first_outfit_eve,
            weather=weather,
            outfit_slots=all_outfit_slots,
            advice_text=_advice_eve or "Образ на завтра готов!",
            colortype=_ct_eve or "",
        )
    except Exception as e:
        logger.warning("evening_brief.child.brief_card_failed", error=str(e))

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

    # Store evening brief_id in Redis for morning reference
    try:
        await redis_client.set(
            f"evening_brief_id:{user.id}:{tomorrow.isoformat()}",
            brief_id,
            ex=86400,
        )
    except Exception:
        pass

    _segment_eve = _get_segment(user)
    _real_photos_eve = _count_real_photos(all_outfit_slots) if all_outfit_slots else 0

    try:
        queue = RedisQueue(redis_client)
        _send_payload: dict = {
            "telegram_id": user.telegram_id,
            "text": brief_text,
            "brief_id": brief_id,
            "is_evening": True,
            "segment": _segment_eve,
            "real_photo_count": _real_photos_eve,
        }
        if brief_card_bytes:
            _send_payload["brief_card_b64"] = _b64.b64encode(brief_card_bytes).decode()
        else:
            _send_payload["text_only"] = True
            _send_payload["parse_mode"] = "HTML"

        await queue.push(
            "send_morning_brief",
            _send_payload,
            priority=QueuePriority.LOW,
        )
    finally:
        pass  # singleton — не закрываем

    logger.info(
        "evening_brief.generated",
        user_id=str(user_id),
        brief_id=brief_id,
        is_adult=is_adult,
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
    from core.redis import get_redis

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
    redis_client = get_redis()
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
        pass  # singleton — не закрываем

    return {}
