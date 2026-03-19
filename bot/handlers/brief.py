"""Обработка фидбека на Morning Brief."""
import uuid

import sentry_sdk
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from db.base import AsyncWriteSession
from db.crud.brief_log import get_log, update_feedback
from db.crud.wardrobe import update_wear_count
from services.i18n.ru import t

logger = structlog.get_logger()


async def handle_brief_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback pattern: ^brief_feedback: → brief_feedback:up:{brief_id} / brief_feedback:down:{brief_id}"""
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
            await query.message.reply_text(
                "Понятно! Что не подошло? Напиши — помогу подобрать лучше 👗\n"
                "Или нажми «Что надеть» — предложу новый вариант!"
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
