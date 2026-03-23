"""capsule_season — proactive push on season change (1 Mar/Jun/Sep/Dec)."""
import asyncio
from datetime import date

import structlog

from config import settings

logger = structlog.get_logger()

_SEASON_MONTHS = {3, 6, 9, 12}  # start of each season
_SEASON_NAMES = {3: "весну", 6: "лето", 9: "осень", 12: "зиму"}
_SEASON_NAMES_EN = {3: "spring", 6: "summer", 9: "autumn", 12: "winter"}


async def run() -> None:
    """Cron trigger — runs 1st of month, 09:00 UTC. Only acts on season change months."""
    today = date.today()
    if today.day != 1 or today.month not in _SEASON_MONTHS:
        return

    logger.info("capsule_season.start", month=today.month)

    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from sqlalchemy import select

    from db.base import AsyncReadSession
    from db.models.user import User
    from core.permissions import get_effective_plan
    from services.i18n import t, get_user_lang

    bot = Bot(token=settings.telegram_bot_token)
    sent = 0

    try:
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(
                    User.onboarding_completed.is_(True),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
            users = list(result.scalars().all())

        for user in users:
            try:
                plan = get_effective_plan(user)
                if plan not in ("premium", "ultra", "admin"):
                    continue

                lang = get_user_lang(user)
                season = _SEASON_NAMES_EN.get(today.month, "season") if lang == "en" else _SEASON_NAMES.get(today.month, "сезон")

                if lang == "en":
                    text = (
                        f"👗 New season — new capsule!\n\n"
                        f"Want to see the best items for {season}?"
                    )
                else:
                    text = (
                        f"👗 Новый сезон — новая капсула!\n\n"
                        f"Хочешь узнать лучшие вещи на {season}?"
                    )

                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t("capsule.profile_btn", lang),
                        callback_data="capsule:build",
                    ),
                ]])

                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    reply_markup=kb,
                )
                sent += 1
                await asyncio.sleep(1)

            except Exception as e:
                logger.warning("capsule_season.user_error",
                               user_id=str(user.id), error=str(e))

    except Exception as e:
        logger.error("capsule_season.error", error=str(e))

    logger.info("capsule_season.done", sent=sent)
