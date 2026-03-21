"""Trial expiry notifications — day 12 (warning) + day 14 (expired)."""
import structlog
from datetime import datetime, timezone, timedelta

logger = structlog.get_logger()


async def _count_briefs(user_id) -> int:
    """Count total briefs generated for user during trial."""
    from db.base import AsyncReadSession
    from db.models.brief_log import BriefLog
    from sqlalchemy import select, func

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(func.count()).select_from(BriefLog).where(
                BriefLog.user_id == user_id,
            )
        )
        return result.scalar() or 0


async def run() -> None:
    """Ежедневно в 09:00 UTC — day 12 warning + day 14 expiry notifications."""
    from db.base import AsyncReadSession
    from db.models.user import User
    from sqlalchemy import select
    from config import settings
    from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

    bot = Bot(token=settings.telegram_bot_token)
    now = datetime.now(timezone.utc)
    count_warned = 0
    count_expired = 0

    # ── Day 12: trial ends in 2 days (warning) ──────────────────────────
    two_days_from_now = now + timedelta(days=2)
    two_days_start = two_days_from_now - timedelta(hours=12)
    two_days_end = two_days_from_now + timedelta(hours=12)

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User).where(
                User.trial_ends_at.between(two_days_start, two_days_end),
                User.onboarding_completed.is_(True),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        warning_users = list(result.scalars().all())

    for user in warning_users:
        try:
            # Check Redis dedup: don't send twice
            try:
                from core.redis import get_redis
                _r = get_redis()
                dedup_key = f"trial_warn_d12:{user.id}"
                already_sent = await _r.get(dedup_key)
                if already_sent:
                    continue
            except Exception:
                pass

            brief_count = await _count_briefs(user.id)
            name = (user.name or "").split()[0] or ""

            text = (
                f"Пробный период заканчивается через 2 дня.\n"
                f"За это время Касси подобрала {brief_count} образов!\n"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Продолжить $9/мес", callback_data="pay_stars:premium_monthly")],
                [InlineKeyboardButton("Посмотреть планы", callback_data="show_upgrade")],
            ])
            await bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=keyboard,
            )

            # Mark as sent (TTL 5 days)
            try:
                await _r.set(dedup_key, "1", ex=432000)
            except Exception:
                pass

            logger.info("trial.day12_warned", user_id=str(user.id), briefs=brief_count)
            count_warned += 1
        except Exception as e:
            logger.warning("trial.day12_warn_failed",
                user_id=str(user.id), error=str(e))

    # ── Day 14: trial expired ────────────────────────────────────────────
    yesterday = now - timedelta(hours=24)

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
        expired_users = list(result.scalars().all())

    for user in expired_users:
        try:
            # Check Redis dedup
            try:
                from core.redis import get_redis
                _r = get_redis()
                dedup_key = f"trial_expired_d14:{user.id}"
                already_sent = await _r.get(dedup_key)
                if already_sent:
                    continue
            except Exception:
                pass

            text = (
                "Пробный период завершён! Спасибо \U0001f495\n"
                "Бесплатный план: образ вт/чт, 3 сообщения/день.\n"
                "Каждый день?"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Premium $9/мес", callback_data="pay_stars:premium_monthly")],
                [InlineKeyboardButton("Посмотреть планы", callback_data="show_upgrade")],
            ])
            await bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=keyboard,
            )

            # Mark as sent (TTL 5 days)
            try:
                await _r.set(dedup_key, "1", ex=432000)
            except Exception:
                pass

            logger.info("trial.day14_expired", user_id=str(user.id))
            count_expired += 1
        except Exception as e:
            logger.warning("trial.day14_expired_failed",
                user_id=str(user.id), error=str(e))

    logger.info("subscription_expiry.run",
        warned=count_warned, expired=count_expired)


async def notify_single_user_trial_expiry(telegram_id: int) -> None:
    """Отправить уведомление об окончании trial одному пользователю (для теста)."""
    from config import settings
    from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

    bot = Bot(token=settings.telegram_bot_token)
    text = (
        "Пробный период завершён! Спасибо \U0001f495\n"
        "Бесплатный план: образ вт/чт, 3 сообщения/день.\n"
        "Каждый день?"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Premium $9/мес", callback_data="pay_stars:premium_monthly")],
        [InlineKeyboardButton("Посмотреть планы", callback_data="show_upgrade")],
    ])
    await bot.send_message(chat_id=telegram_id, text=text, reply_markup=keyboard)
