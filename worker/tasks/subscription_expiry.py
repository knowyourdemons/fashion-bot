"""Trial expiry notifications."""
import structlog
from datetime import datetime, timezone, timedelta

logger = structlog.get_logger()


async def run() -> None:
    """Ежедневно в 09:00 UTC — уведомляет пользователей у которых trial закончился."""
    from db.base import AsyncReadSession
    from db.models.user import User
    from sqlalchemy import select
    from config import settings
    from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
    from core.permissions import PRICES

    bot = Bot(token=settings.telegram_bot_token)
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(hours=24)
    count = 0

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User).where(
                User.trial_ends_at.between(yesterday, now),
                User.plan == "free",
                User.onboarding_completed.is_(True),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        users = list(result.scalars().all())

    for user in users:
        try:
            text = (
                f"Касси скучает по тебе! 🌸\n\n"
                f"14 дней пролетели незаметно...\n"
                f"Выбери план чтобы продолжить:\n\n"
                f"📅 {PRICES['premium_monthly']['label']}\n"
                f"📅 {PRICES['premium_quarterly']['label']}\n"
                f"📅 {PRICES['premium_yearly']['label']}\n"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Выбрать план", callback_data="show_upgrade")],
                [InlineKeyboardButton("Остаться на Free", callback_data="stay_free")],
            ])
            await bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=keyboard,
            )
            logger.info("trial.expiry_notified", user_id=str(user.id))
            count += 1
        except Exception as e:
            logger.warning("trial.expiry_notify_failed",
                user_id=str(user.id), error=str(e))

    logger.info("subscription_expiry.run", notified=count)
