"""
Миграция: переложить файлы R2 в новую структуру wardrobe/{owner_id}/{filename}
и обновить photo_url на CDN URL.

Запуск: python -m db.seeds.migrate_r2_cdn
"""
import asyncio
import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import structlog
from sqlalchemy import select, update

from config import settings
from db.base import AsyncWriteSession, AsyncReadSession
from db.models.wardrobe import WardrobeItem
from services.storage.r2_storage import get_r2_storage

logger = structlog.get_logger()


async def migrate() -> None:
    if not settings.cloudflare_r2_cdn_url:
        print("ERROR: CLOUDFLARE_R2_CDN_URL не задан")
        return

    r2 = get_r2_storage()

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(WardrobeItem).where(
                WardrobeItem.photo_url.isnot(None),
                WardrobeItem.photo_url != "",
                WardrobeItem.deleted_at.is_(None),
            )
        )
        items = list(result.scalars().all())

    to_migrate = [i for i in items if not (i.photo_url or "").startswith("http")]
    print(f"Найдено {len(items)} вещей с photo_url, из них {len(to_migrate)} требуют миграции")

    migrated = 0
    errors = 0

    for item in to_migrate:
        old_key = item.photo_url
        filename = old_key.split("/")[-1]
        new_key = f"wardrobe/{item.owner_id}/{filename}"
        new_url = r2.get_public_url(new_key)

        try:
            # Скачать из старого пути
            photo_bytes = await r2.get_photo(old_key)

            # Залить в новый путь
            await r2.upload_photo(photo_bytes, filename, owner_id=str(item.owner_id))

            # Обновить запись в БД
            async with AsyncWriteSession() as session:
                await session.execute(
                    update(WardrobeItem)
                    .where(WardrobeItem.id == item.id)
                    .values(photo_url=new_url)
                )
                await session.commit()

            # Удалить старый файл
            await r2.delete_photo(old_key)

            migrated += 1
            logger.info("migrate.done", item_id=str(item.id), old=old_key, new=new_url)
            print(f"  ✅ {old_key} → {new_url}")

        except Exception as e:
            errors += 1
            logger.error("migrate.failed", item_id=str(item.id), key=old_key, error=str(e))
            print(f"  ❌ {old_key}: {e}")

    print(f"\nГотово: {migrated} мигрировано, {errors} ошибок")


if __name__ == "__main__":
    asyncio.run(migrate())
