"""Gap analysis cron task — 1-е число каждого месяца."""
import asyncio
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()


async def run() -> None:
    """Отправляет шоппинг-лист всем premium/ultra/admin пользователям."""
    from config import settings
    from db.base import AsyncReadSession
    from db.models.user import User
    from db.crud.wardrobe import get_owner_items
    from db.crud.children import get_children
    from core.permissions import get_effective_plan, can_gap_analysis
    from services.gap_analysis import build_shopping_list, _get_current_season
    from services.i18n import t, get_user_lang
    from telegram import Bot
    from core.redis import get_redis
    from sqlalchemy import select

    bot = Bot(token=settings.telegram_bot_token)
    redis_client = get_redis()

    now = datetime.now(timezone.utc)

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User).where(
                User.onboarding_completed.is_(True),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        all_users = list(result.scalars().all())

    # Фильтр: premium/ultra с активной подпиской + admin
    eligible = [
        u for u in all_users
        if can_gap_analysis(get_effective_plan(u))
    ]

    sent_count = 0
    error_count = 0

    for user in eligible:
        try:
            # Сбросить кэш — генерировать свежий анализ
            await redis_client.delete(f"gap_analysis:{user.id}")

            # Загрузить вещи
            child = None
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
                continue

            result_text = await build_shopping_list(user, items, redis_client, child=child)

            if result_text and result_text not in ("lock", ""):
                season = _get_current_season(user.timezone or "Europe/Vilnius")
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=t("shopping.header", season=season, list=result_text),
                )
                sent_count += 1

        except Exception as e:
            logger.warning(
                "gap_analysis.user_error",
                user_id=str(user.id),
                error=str(e),
            )
            error_count += 1

        await asyncio.sleep(0.3)

    logger.info(
        "gap_analysis.run",
        eligible=len(eligible),
        sent=sent_count,
        errors=error_count,
    )
