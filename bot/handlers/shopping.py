"""Шоппинг-лист / Gap analysis handler."""
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from core.permissions import get_effective_plan, can_gap_analysis
from services.i18n import t, get_user_lang
from services.gap_analysis import build_shopping_list, _get_current_season

logger = structlog.get_logger()


async def handle_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    lang = get_user_lang(user)
    effective_plan = get_effective_plan(user)
    redis = context.bot_data["redis"]

    if not can_gap_analysis(effective_plan):
        await update.message.reply_text(t("shopping.premium_only", lang))
        return

    child = None
    from db.base import AsyncReadSession
    from db.crud.wardrobe import get_owner_items
    from db.crud.children import get_children
    from bot.handlers.wardrobe import _get_owner

    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    if owner_type == "child":
        async with AsyncReadSession() as session:
            children = await get_children(session, user.id)
        child = next((c for c in children if c.id == owner_id), None)

    if len(items) < 5:
        await update.message.reply_text(t("shopping.too_few_items", lang))
        return

    generating_msg = await update.message.reply_text(t("shopping.generating", lang))

    result = await build_shopping_list(user, items, redis, child=child)

    try:
        await generating_msg.delete()
    except Exception:
        pass

    if result == "lock":
        await update.message.reply_text(t("shopping.already_running", lang))
    elif result is None:
        await update.message.reply_text(t("shopping.error", lang))
    elif result == "":
        await update.message.reply_text(t("shopping.empty_result", lang))
    else:
        season = _get_current_season(user.timezone or "Europe/Vilnius")
        _oid = str(child.id) if child else str(user.id)
        ttl = await redis.ttl(f"gap_analysis:v6:{_oid}")
        is_cached = ttl < 86000
        logger.info(
            "shopping.sent",
            user_id=str(user.id),
            season=season,
            is_cached=is_cached,
        )
        header_text = t("shopping.header", lang, season=season, list=result)
        if child:
            header_text = f"🛍 Что стоит купить {child.name} {season}:\n\n{result}"
        await update.message.reply_text(header_text)
