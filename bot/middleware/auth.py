"""
Bot middleware: проверяет user в БД, создаёт если нет.
Сохраняет db_user в context.user_data.
"""
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from db.base import AsyncWriteSession
from db.crud.users import get_by_telegram_id, create

logger = structlog.get_logger()


class AuthMiddleware:
    @staticmethod
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user:
            return
        tg_user = update.effective_user

        # Кэш в context.user_data
        if "db_user" not in context.user_data:
            try:
                async with AsyncWriteSession() as session:
                    user = await get_by_telegram_id(session, tg_user.id)
                    if not user:
                        user = await create(session, tg_user.id, tg_user.full_name)
                        # Auto-detect language from Telegram
                        tg_lang = getattr(tg_user, "language_code", "") or ""
                        if tg_lang.startswith("en"):
                            user.language = "en"
                        await session.commit()
                    context.user_data["db_user"] = user
            except Exception as e:
                # Race condition: another request created user simultaneously
                # Retry with read-only lookup
                logger.warning("auth.create_race", telegram_id=tg_user.id, error=str(e))
                try:
                    async with AsyncWriteSession() as session:
                        user = await get_by_telegram_id(session, tg_user.id)
                        if user:
                            context.user_data["db_user"] = user
                        else:
                            logger.error("auth.user_not_found_after_retry", telegram_id=tg_user.id)
                except Exception as e2:
                    logger.error("auth.retry_failed", telegram_id=tg_user.id, error=str(e2))
