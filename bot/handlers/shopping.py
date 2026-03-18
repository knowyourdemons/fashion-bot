"""Шоппинг-лист / Gap analysis handler."""
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from core.permissions import get_effective_plan, can_gap_analysis
from services.i18n.ru import t
from services.gap_analysis import build_shopping_list, _get_current_season

logger = structlog.get_logger()


async def handle_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    effective_plan = get_effective_plan(user)
    redis = context.bot_data["redis"]

    if not can_gap_analysis(effective_plan):
        await update.message.reply_text(t("shopping.premium_only"))
        return

    # Определить владельца гардероба
    child = None
    from db.base import AsyncReadSession
    from db.crud.wardrobe import get_owner_items
    from db.crud.children import get_children

    if user.segment in ("mom_girl", "mom_boy"):
        async with AsyncReadSession() as session:
            children = await get_children(session, user.id)
        if children:
            child = children[0]
            async with AsyncReadSession() as session:
                items = await get_owner_items(session, child.id, "child")
        else:
            items = []
    else:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, user.id, "user")

    if len(items) < 5:
        await update.message.reply_text(t("shopping.too_few_items"))
        return

    generating_msg = await update.message.reply_text(t("shopping.generating"))

    result = await build_shopping_list(user, items, redis, child=child)

    try:
        await generating_msg.delete()
    except Exception:
        pass

    if result == "lock":
        await update.message.reply_text("Уже анализирую, подожди немного...")
    elif result is None:
        await update.message.reply_text(t("shopping.error"))
    elif result == "":
        await update.message.reply_text(t("shopping.empty_result"))
    else:
        season = _get_current_season(user.timezone or "Europe/Vilnius")
        ttl = await redis.ttl(f"gap_analysis:{user.id}")
        is_cached = ttl < 86000
        logger.info(
            "shopping.sent",
            user_id=str(user.id),
            season=season,
            is_cached=is_cached,
        )
        await update.message.reply_text(t("shopping.header", season=season, list=result))
