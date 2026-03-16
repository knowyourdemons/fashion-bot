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
        key = f"session:user:{tg_user.id}"

        # Кэш в context.user_data
        if "db_user" not in context.user_data:
            async with AsyncWriteSession() as session:
                user = await get_by_telegram_id(session, tg_user.id)
                if not user:
                    user = await create(session, tg_user.id, tg_user.full_name)
                    await session.commit()
                context.user_data["db_user"] = user
