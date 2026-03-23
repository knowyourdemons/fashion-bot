"""unknown_items_report task — admin report of unrecognized item types."""
import asyncio
from collections import Counter

import structlog

logger = structlog.get_logger()


async def run() -> None:
    """Cron trigger — send admin report grouping unknown item types by frequency."""
    logger.info("unknown_items_report.run.start")

    try:
        from sqlalchemy import select
        from db.base import AsyncReadSession
        from db.models.wardrobe import WardrobeItem
        from config import settings
        from telegram import Bot
        import sentry_sdk

        # 1. Query unknown items
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(WardrobeItem.type, WardrobeItem.category_group).where(
                    WardrobeItem.is_unknown_category.is_(True),
                    WardrobeItem.deleted_at.is_(None),
                )
            )
            rows = list(result.all())

        if not rows:
            logger.info("unknown_items_report.run.done", total=0)
            return

        # 2. Group by type, sorted by count desc
        type_counts = Counter(row[0] for row in rows)
        sorted_types = type_counts.most_common()

        # 3. Format report
        lines = [
            f"📋 Отчёт: нераспознанные вещи ({len(rows)} шт.)\n",
        ]
        for item_type, count in sorted_types[:30]:  # cap at 30 lines
            lines.append(f"  {item_type}: {count}")

        if len(sorted_types) > 30:
            lines.append(f"\n  ... и ещё {len(sorted_types) - 30} типов")

        text = "\n".join(lines)

        # 4. Send to all admins
        admin_ids = settings.admin_ids_list
        if not admin_ids:
            logger.warning("unknown_items_report.no_admin_ids")
            return

        bot = Bot(token=settings.telegram_bot_token)

        for admin_id in admin_ids:
            try:
                await bot.send_message(chat_id=admin_id, text=text)
            except Exception as e:
                logger.warning(
                    "unknown_items_report.send_failed",
                    admin_id=admin_id,
                    error=str(e),
                )
            await asyncio.sleep(1)

        logger.info(
            "unknown_items_report.run.done",
            total=len(rows),
            unique_types=len(sorted_types),
            admins_notified=len(admin_ids),
        )

    except Exception as e:
        logger.error("unknown_items_report.run.fatal", error=str(e))
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
