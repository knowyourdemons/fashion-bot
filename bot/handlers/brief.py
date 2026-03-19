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
        brief_id = uuid.UUID(parts[2])
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
        await query.edit_message_reply_markup(reply_markup=None)
        if vote == "up":
            await query.message.reply_text("👍 Отлично! Записала что надели.")
        else:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Другой образ", callback_data="outfit_request"),
            ]])
            await query.message.reply_text(
                "Понятно! Напиши что не подошло — подберу лучше 👗",
                reply_markup=keyboard,
            )
        logger.info(
            "brief.feedback",
            brief_id=str(brief_id),
            vote=vote,
        )
    except Exception as e:
        await query.message.reply_text(t("error.generic"))
        logger.error("brief.feedback.error", error=str(e))
        sentry_sdk.capture_exception(e)


async def handle_reroll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback pattern: ^reroll:{brief_id} → сгенерировать новый образ, исключая текущие вещи."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    redis = context.bot_data.get("redis")

    from core.permissions import get_effective_plan, get_limit
    plan = get_effective_plan(user)
    reroll_limit = get_limit("reroll", plan)

    if reroll_limit == 0:
        await query.answer(
            "🔄 Переодевание доступно в Premium! Нажми «Подписка» для доступа.",
            show_alert=True,
        )
        return

    from datetime import date as _date
    today = _date.today().isoformat()
    reroll_key = f"reroll:{user.id}:{today}"
    count = 0
    if redis:
        val = await redis.get(reroll_key)
        count = int(val) if val else 0

    if count >= reroll_limit:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Безлимит →", callback_data="show_upgrade"),
        ]])
        await query.message.reply_text(
            f"На сегодня переодевания закончились ({reroll_limit}/день) 🙈\n"
            "Завтра утром соберу новый образ!",
            reply_markup=keyboard,
        )
        return

    # Получить outfit_items из brief_log для исключения
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

    await query.message.reply_text("🔄 Подбираю другой вариант...")

    from bot.handlers.wardrobe import _generate_outfit_for_user
    await _generate_outfit_for_user(query.message, user, context, exclude_ids=exclude_ids)

    if redis:
        await redis.incr(reroll_key)
        await redis.expire(reroll_key, 86400)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    logger.info("reroll.done", user_id=str(user.id), excluded=len(exclude_ids))
