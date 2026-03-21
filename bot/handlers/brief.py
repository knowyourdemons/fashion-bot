"""Обработка фидбека на Morning Brief."""
import uuid
import sentry_sdk
import structlog
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.base import AsyncWriteSession
from db.crud.brief_log import get_log, update_feedback
from db.crud.wardrobe import update_wear_count
from services.i18n.ru import t
logger = structlog.get_logger()
async def handle_brief_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback pattern: ^brief_feedback: -> brief_feedback:up:{brief_id} / brief_feedback:down:{brief_id}"""
    query = update.callback_query
    await query.answer()
    try:
        parts = query.data.split(":")
        vote = parts[1]           # "up" or "down"
        brief_id_str = parts[2]
        if brief_id_str == "noop":
            if vote == "up":
                try:
                    await query.edit_message_caption(caption="✅ Надели!")
                except Exception:
                    await query.edit_message_reply_markup(reply_markup=None)
            else:
                await query.edit_message_reply_markup(reply_markup=None)
            return
        brief_id = uuid.UUID(brief_id_str)
        async with AsyncWriteSession() as session:
            log = await get_log(session, brief_id)
            if not log:
                await query.message.reply_text(t("error.not_found"))
                return
            await update_feedback(session, brief_id, vote)
            if vote == "up":
                item_ids = [uuid.UUID(i) for i in (log.outfit_items or [])]
                await update_wear_count(session, item_ids)
            await session.commit()
        # Clean UX: edit caption on collage, not new message
        if vote == "up":
            try:
                await query.edit_message_caption(caption="✅ Надели!")
            except Exception:
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
        else:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Другой образ", callback_data="outfit_request"),
            ]])
            try:
                await query.edit_message_caption(
                    caption="Подберу другой 👗",
                    reply_markup=keyboard,
                )
            except Exception:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(
                    "Понятно! Напиши что не подошло — подберу лучше 👗",
                    reply_markup=keyboard,
                )
        logger.info(
            "brief.feedback",
            brief_id=str(brief_id),
            vote=vote,
        )
        user = context.user_data.get("db_user")
        logger.info("metric.brief_feedback",
            user_id=str(user.id) if user else "unknown",
            feedback=vote,
        )
    except Exception as e:
        await query.message.reply_text(t("error.generic"))
        logger.error("brief.feedback.error", error=str(e))
        sentry_sdk.capture_exception(e)


async def _reroll_adult_advice(message, user) -> None:
    """Перегенерировать совет и отредактировать существующее сообщение."""
    from worker.tasks.style_config import COLORTYPE_PALETTES
    from core.anthropic_client import get_anthropic_pool, init_anthropic_pool
    from core.redis import get_redis

    coords = None
    weather: dict = {}
    if user.city:
        from services.brief_weather import _geocode_city, _get_weather
        coords = await _geocode_city(user.city)
        if coords:
            weather = await _get_weather(coords[0], coords[1], user.timezone or "Europe/Vilnius")

    temp_m = weather.get("temp_morning", 10)
    from services.outfit_selector import _get_temp_regime
    from worker.tasks.morning_brief import _REGIME_OUTER_ADVICE
    regime = _get_temp_regime(temp_m)
    outer_advice = _REGIME_OUTER_ADVICE.get(regime, "куртка")
    sm = "+" if temp_m >= 0 else ""
    colortype = getattr(user, "colortype", None) or "default"

    from db.base import AsyncReadSession
    from db.crud.wardrobe import get_owner_items
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, user.id, "user")

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
            f"Не используй markdown символы (# * _ и т.д.). Только обычный текст. "
            f"Дай ДРУГОЙ совет, не повторяй предыдущий."
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
            f"Не используй markdown символы (# * _ и т.д.). Только обычный текст. "
            f"Дай ДРУГОЙ совет, не повторяй предыдущий."
        )

    try:
        pool = get_anthropic_pool()
    except RuntimeError:
        _redis = get_redis()
        init_anthropic_pool(_redis)
        pool = get_anthropic_pool()

    try:
        resp = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
        )
        advice = resp.content[0].text.strip()
    except Exception as e:
        logger.warning("reroll.adult.haiku_failed", error=str(e))
        advice = f"Сегодня {sm}{temp_m:.0f}°C — выбери {outer_advice} ✨"

    text = f"💡 Идея на сегодня:\n{advice}"

    if items:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Нравится", callback_data="brief_feedback:up:noop"),
            InlineKeyboardButton("🔄 Другой", callback_data="reroll_advice"),
        ]])
    else:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Спасибо", callback_data="brief_feedback:up:noop"),
            InlineKeyboardButton("🔄 Ещё совет", callback_data="reroll_advice"),
        ]])

    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await message.reply_text(text, reply_markup=keyboard)


async def handle_reroll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback pattern: ^reroll:{brief_id} или ^reroll_advice → новый образ/совет.

    Flow:
      - reroll_advice (no brief_id): advice-only reroll via Haiku (adults without items)
      - reroll:{brief_id}: outfit reroll — works for BOTH adults and children
        1. Get current outfit item_ids from brief_log
        2. Add them to Redis exclude set reroll:{user_id}:{date} (SADD, TTL 24h)
        3. Generate new outfit with those items excluded via _generate_outfit_for_user
        4. Send as new photo message, remove buttons from old message
    """
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    redis = context.bot_data.get("redis")
    is_advice_reroll = query.data == "reroll_advice"

    # ── Check reroll limits ──
    from core.permissions import get_effective_plan, get_limit, get_effective_limits
    plan = get_effective_plan(user)
    effective = get_effective_limits(user)
    reroll_limit = effective.get("reroll", get_limit("reroll", plan))

    from datetime import date as _date
    today = _date.today().isoformat()
    reroll_key = f"reroll_count:{user.id}:{today}"
    count = 0
    if redis:
        val = await redis.get(reroll_key)
        count = int(val) if val else 0

    if count >= reroll_limit:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✨ Подписка →", callback_data="show_upgrade",
            ),
        ]])
        await query.message.reply_text(
            "Хочешь больше? В Premium — безлимитные варианты! ✨",
            reply_markup=keyboard,
        )
        return

    # ── Advice-only reroll (adults without items) ──
    if is_advice_reroll:
        # Edit existing message instead of sending new one
        try:
            await query.edit_message_text("🔄 Генерирую новый совет...")
        except Exception:
            pass
        await _reroll_adult_advice(query.message, user)

        if redis:
            await redis.incr(reroll_key)
            await redis.expire(reroll_key, 86400)

        logger.info("reroll.adult_advice.done", user_id=str(user.id))
        return

    # ── Outfit reroll (adults with items + children) ──
    # Get outfit_items from brief_log to build exclude set
    parts = query.data.split(":", 1)
    brief_id_str = parts[1] if len(parts) > 1 else None
    exclude_ids: set = set()

    if brief_id_str:
        try:
            from db.crud.brief_log import get_log
            from db.base import AsyncReadSession
            async with AsyncReadSession() as session:
                log = await get_log(session, uuid.UUID(brief_id_str))
            if log and log.outfit_items:
                exclude_ids = {uuid.UUID(i) for i in log.outfit_items}
        except Exception as e:
            logger.warning("reroll.log_fetch_failed", error=str(e))

    # Accumulate excludes in Redis set (persists across rerolls within the day)
    exclude_set_key = f"reroll:{user.id}:{today}"
    if redis and exclude_ids:
        try:
            await redis.sadd(exclude_set_key, *[str(eid) for eid in exclude_ids])
            await redis.expire(exclude_set_key, 86400)
        except Exception:
            pass

    # Load all previously excluded items from Redis
    if redis:
        try:
            raw_excluded = await redis.smembers(exclude_set_key)
            for raw in raw_excluded:
                try:
                    exclude_ids.add(uuid.UUID(raw.decode() if isinstance(raw, bytes) else raw))
                except Exception:
                    pass
        except Exception:
            pass

    # Show loading state on existing collage
    old_message = query.message
    try:
        await query.edit_message_caption(caption="🔄 Подбираю другой вариант...")
    except Exception:
        pass

    from bot.handlers.wardrobe import _generate_outfit_for_user
    await _generate_outfit_for_user(old_message, user, context, exclude_ids=exclude_ids)

    if redis:
        await redis.incr(reroll_key)
        await redis.expire(reroll_key, 86400)

    # Delete old collage (new one already sent by _generate_outfit_for_user)
    try:
        await old_message.delete()
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    logger.info("reroll.done", user_id=str(user.id), excluded=len(exclude_ids))


async def handle_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: share:{brief_id} → переслать коллаж чистым фото без кнопок."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 1)
    brief_id_str = parts[1] if len(parts) > 1 else None
    if not brief_id_str:
        await query.message.reply_text("📤 Перешли картинку выше — на ней всё написано 👗")
        return

    try:
        from db.base import AsyncReadSession
        async with AsyncReadSession() as session:
            log = await get_log(session, uuid.UUID(brief_id_str))

        if log and log.collage_file_id:
            # Определить имя ребёнка для caption
            user = context.user_data.get("db_user")
            child_name = None
            if user and user.segment in ("mom_girl", "mom_boy"):
                from db.crud.children import get_children
                async with AsyncReadSession() as session:
                    children = await get_children(session, user.id)
                if children:
                    child_name = children[0].name

            caption = (
                f"Образ для {child_name} на сегодня. Собрала Касси — твой личный стилист 👗"
                if child_name else
                "Образ дня от Касси — твоего личного стилиста 👗"
            )
            await query.message.reply_photo(
                photo=log.collage_file_id,
                caption=caption,
            )
        else:
            await query.message.reply_text(
                "📤 Перешли картинку выше — на ней всё написано 👗"
            )
    except Exception as e:
        logger.error("brief.share.error", error=str(e))
        await query.message.reply_text("📤 Перешли картинку выше 👗")
