"""taxonomy_review task — re-classify unknown category items."""
import asyncio

import structlog

logger = structlog.get_logger()


async def run() -> None:
    """Cron trigger — try to reclassify items with is_unknown_category=True."""
    logger.info("taxonomy_review.run.start")

    try:
        from sqlalchemy import select
        from db.base import AsyncReadSession, AsyncWriteSession
        from db.models.wardrobe import WardrobeItem
        from services.normalize import normalize_type
        import sentry_sdk

        # 1. Query all unknown items
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(WardrobeItem).where(
                    WardrobeItem.is_unknown_category.is_(True),
                    WardrobeItem.deleted_at.is_(None),
                )
            )
            unknown_items = list(result.scalars().all())

        if not unknown_items:
            logger.info("taxonomy_review.run.done", total_unknown=0, reclassified=0, still_unknown=0)
            return

        reclassified = 0
        still_unknown = 0

        # 2. Try normalize_type for each
        for item in unknown_items:
            try:
                normalized_type, normalized_cg = normalize_type(
                    item.type, item.category_group
                )

                # If normalization changed the type or category, update
                type_changed = normalized_type != item.type
                cg_changed = normalized_cg != item.category_group

                if type_changed or cg_changed:
                    async with AsyncWriteSession() as session:
                        # Re-fetch in write session
                        db_item = await session.get(WardrobeItem, item.id)
                        if db_item and db_item.is_unknown_category:
                            db_item.type = normalized_type
                            db_item.category_group = normalized_cg
                            db_item.is_unknown_category = False
                            await session.commit()

                    reclassified += 1
                    logger.debug(
                        "taxonomy_review.reclassified",
                        item_id=str(item.id),
                        old_type=item.type,
                        new_type=normalized_type,
                        old_cg=item.category_group,
                        new_cg=normalized_cg,
                    )
                else:
                    still_unknown += 1

            except Exception as e:
                logger.warning(
                    "taxonomy_review.item_error",
                    item_id=str(item.id),
                    error=str(e),
                )
                sentry_sdk.capture_exception(e)
                still_unknown += 1

            await asyncio.sleep(0.1)

        logger.info(
            "taxonomy_review.run.done",
            total_unknown=len(unknown_items),
            reclassified=reclassified,
            still_unknown=still_unknown,
        )

    except Exception as e:
        logger.error("taxonomy_review.run.fatal", error=str(e))
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
