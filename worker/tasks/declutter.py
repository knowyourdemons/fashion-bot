"""declutter task — suggest items to remove/donate for premium users."""
import asyncio
from datetime import datetime, timedelta, timezone

import structlog

logger = structlog.get_logger()

SCORE_THRESHOLD = 4.0
MIN_AGE_DAYS = 60
MAX_SUGGESTIONS = 5
LOCK_TTL = 30 * 86400  # 1 month


async def run() -> None:
    """Cron trigger — monthly declutter suggestions for premium users."""
    logger.info("declutter.run.start")

    try:
        from sqlalchemy import select
        from db.base import AsyncReadSession
        from db.models.user import User
        from db.crud.wardrobe import get_owner_items
        from db.crud.children import get_children
        from core.permissions import get_effective_plan
        from core.redis import get_redis
        from services.scoring import calc_item_versatility
        from config import settings
        from telegram import Bot
        import sentry_sdk

        bot = Bot(token=settings.telegram_bot_token)
        redis = get_redis()
        cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)

        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(
                    User.onboarding_completed.is_(True),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
            )
            all_users = list(result.scalars().all())

        eligible = [
            u for u in all_users
            if get_effective_plan(u) in ("premium", "ultra", "admin")
        ]

        sent_count = 0
        errors = 0

        for user in eligible:
            try:
                # Rate limit: 1 message per month
                lock_key = f"declutter_sent:{user.id}"
                if await redis.exists(lock_key):
                    continue

                # Determine owner
                owner_id = user.id
                owner_type = "user"
                if user.segment in ("mom_girl", "mom_boy"):
                    async with AsyncReadSession() as session:
                        children = await get_children(session, user.id)
                    if children:
                        owner_id = children[0].id
                        owner_type = "child"

                async with AsyncReadSession() as session:
                    items = await get_owner_items(session, owner_id, owner_type)

                if len(items) < 10:
                    continue

                # Find declutter candidates
                candidates = []
                for item in items:
                    score = float(item.score_item) if item.score_item is not None else 10.0
                    wear_count = item.wear_count or 0
                    added = item.added_at

                    # Low score + never worn + old enough
                    is_low_score = score < SCORE_THRESHOLD and wear_count == 0
                    is_old = added and added.replace(tzinfo=timezone.utc) < cutoff if added.tzinfo is None else added < cutoff

                    # Orphan check
                    versatility = calc_item_versatility(item, items)
                    is_orphan = versatility < 2

                    if (is_low_score and is_old) or is_orphan:
                        candidates.append(item)

                if not candidates:
                    continue

                # Build message (max 5 items)
                suggestions = candidates[:MAX_SUGGESTIONS]
                lines = [
                    "🧹 Касси предлагает разобрать гардероб!\n",
                    "Эти вещи редко используются и плохо сочетаются с остальными:\n",
                ]
                for item in suggestions:
                    lines.append(f"  • {item.type} ({item.color})")

                lines.append(
                    "\nМожно отдать, продать или убрать на хранение — "
                    "так гардероб станет функциональнее!"
                )
                text = "\n".join(lines)

                await bot.send_message(chat_id=user.telegram_id, text=text)
                await redis.set(lock_key, "1", ex=LOCK_TTL)
                sent_count += 1

            except Exception as e:
                logger.warning("declutter.user_error", user_id=str(user.id), error=str(e))
                sentry_sdk.capture_exception(e)
                errors += 1

            await asyncio.sleep(1)

        logger.info(
            "declutter.run.done",
            eligible=len(eligible),
            sent=sent_count,
            errors=errors,
        )

    except Exception as e:
        logger.error("declutter.run.fatal", error=str(e))
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
