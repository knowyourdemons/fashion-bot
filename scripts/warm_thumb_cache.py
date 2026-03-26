"""Pre-warm thumbnail cache for all wardrobe items.

Downloads HD originals from Telegram, runs rembg pipeline,
caches results in Redis. After this, collage rendering is instant.
"""
import asyncio
import sys
import os

sys.path.insert(0, "/app")
os.chdir("/app")


async def main():
    from core.redis import init_redis, get_redis
    from sqlalchemy import select
    from db.base import AsyncReadSession
    from db.models.wardrobe import WardrobeItem
    from services.brief_card import _get_cached_thumb, _cache_thumb
    from services.image_processor import make_collage_thumbnail
    from services.vision import _crop_bbox
    from config import settings
    from telegram import Bot
    from PIL import Image
    import io
    import httpx
    import structlog

    logger = structlog.get_logger()
    await init_redis()
    bot = Bot(token=settings.telegram_bot_token)

    async with AsyncReadSession() as session:
        items = list((await session.execute(
            select(WardrobeItem).where(WardrobeItem.deleted_at.is_(None))
        )).scalars().all())

    print(f"Total items: {len(items)}")
    cached = 0
    built = 0
    errors = 0

    for item in items:
        # Skip if already cached
        existing = await _get_cached_thumb(str(item.id))
        if existing:
            cached += 1
            continue

        if not item.photo_id:
            continue

        try:
            # Download HD from Telegram
            f = await bot.get_file(item.photo_id)
            buf = io.BytesIO()
            await f.download_to_memory(buf)
            raw = buf.getvalue()

            img = Image.open(io.BytesIO(raw))
            tg_size = img.size

            # Bbox crop
            bbox = getattr(item, "bbox", None)
            if bbox and isinstance(bbox, dict) and bbox.get("w", 1.0) < 0.95:
                raw = _crop_bbox(raw, bbox)

            # Check if needs rembg
            img_check = Image.open(io.BytesIO(raw))
            needs_rembg = img_check.mode not in ("RGBA", "LA", "PA")

            # Build thumbnail
            thumb = make_collage_thumbnail(raw, needs_bg_removal=needs_rembg)

            # Cache
            await _cache_thumb(str(item.id), thumb)
            built += 1
            print(f"  OK: {item.type} ({tg_size[0]}x{tg_size[1]} → thumb {len(thumb)//1024}KB)")

        except Exception as e:
            errors += 1
            print(f"  ERR: {item.type}: {e}")

    print(f"\nDone! cached={cached} built={built} errors={errors}")


if __name__ == "__main__":
    asyncio.run(main())
