"""
Очистка R2: удаляет файлы удалённых вещей (deleted_at < NOW() - 7 days).
Запускается раз в день.
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update

from db.base import AsyncWriteSession, AsyncReadSession
from db.models.wardrobe import WardrobeItem

logger = structlog.get_logger()


async def run() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(WardrobeItem).where(
                WardrobeItem.deleted_at.isnot(None),
                WardrobeItem.deleted_at < cutoff,
                WardrobeItem.photo_url.isnot(None),
                WardrobeItem.photo_url != "",
            )
        )
        items = list(result.scalars().all())

    if not items:
        logger.info("cleanup_r2.nothing_to_clean")
        return

    logger.info("cleanup_r2.start", count=len(items))

    from services.storage.r2_storage import get_r2_storage
    r2 = get_r2_storage()

    cleaned = 0
    errors = 0

    for item in items:
        photo_url = item.photo_url
        try:
            # Определяем ключ: для CDN URL извлекаем путь, для старого формата используем как есть
            if photo_url.startswith("http"):
                from urllib.parse import urlparse
                key = urlparse(photo_url).path.lstrip("/")
            else:
                key = photo_url

            await r2.delete_photo(key)

            async with AsyncWriteSession() as session:
                await session.execute(
                    update(WardrobeItem)
                    .where(WardrobeItem.id == item.id)
                    .values(photo_url="")
                )
                await session.commit()

            cleaned += 1
        except Exception as e:
            errors += 1
            logger.warning("cleanup_r2.item_failed", item_id=str(item.id), error=str(e))

    logger.info("cleanup_r2.done", cleaned=cleaned, errors=errors)
