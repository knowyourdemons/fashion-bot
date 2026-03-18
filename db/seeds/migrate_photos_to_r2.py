"""
Миграция фото из Telegram → R2.
Запуск: python3 -m db.seeds.migrate_photos_to_r2
"""
import asyncio
import uuid
import httpx
import structlog

from config import settings
from db.base import AsyncReadSession, AsyncWriteSession
from db.models.wardrobe import WardrobeItem
from services.storage.r2_storage import R2Storage
from sqlalchemy import select, update

logger = structlog.get_logger()


async def download_from_telegram(file_id: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                params={"file_id": file_id},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning("migrate.getfile_failed", file_id=file_id[:20], result=data)
                return None
            file_path = data["result"]["file_path"]
            resp2 = await client.get(
                f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
            )
            resp2.raise_for_status()
            return resp2.content
    except Exception as e:
        logger.error("migrate.download_failed", file_id=file_id[:20], error=str(e))
        return None


async def migrate():
    r2 = R2Storage()

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(WardrobeItem).where(
                WardrobeItem.deleted_at.is_(None),
                WardrobeItem.photo_url.is_(None),  # ещё не мигрированы
            )
        )
        items = result.scalars().all()

    logger.info("migrate.start", total=len(items))

    # Дедупликация — один photo_id может быть у нескольких вещей
    seen: dict[str, str] = {}  # file_id → r2_key
    ok = 0
    fail = 0

    for item in items:
        file_id = item.photo_id
        item_id = str(item.id)

        if file_id in seen:
            # Уже загружали это фото — просто обновляем photo_url
            r2_key = seen[file_id]
            async with AsyncWriteSession() as session:
                await session.execute(
                    update(WardrobeItem)
                    .where(WardrobeItem.id == item.id)
                    .values(photo_url=r2_key)
                )
                await session.commit()
            logger.info("migrate.reused", item_id=item_id, r2_key=r2_key)
            ok += 1
            continue

        photo_bytes = await download_from_telegram(file_id)
        if not photo_bytes:
            fail += 1
            continue

        filename = f"{item_id}.jpg"
        try:
            r2_key = await r2.upload_photo(photo_bytes, filename)
            seen[file_id] = r2_key

            async with AsyncWriteSession() as session:
                await session.execute(
                    update(WardrobeItem)
                    .where(WardrobeItem.id == item.id)
                    .values(photo_url=r2_key)
                )
                await session.commit()

            logger.info("migrate.ok", item_id=item_id, r2_key=r2_key, size=len(photo_bytes))
            ok += 1
        except Exception as e:
            logger.error("migrate.upload_failed", item_id=item_id, error=str(e))
            fail += 1

        await asyncio.sleep(0.3)  # не спамим Telegram API

    logger.info("migrate.done", ok=ok, fail=fail, total=len(items))
    print(f"\nГотово: {ok} успешно, {fail} ошибок из {len(items)} вещей")


if __name__ == "__main__":
    asyncio.run(migrate())
