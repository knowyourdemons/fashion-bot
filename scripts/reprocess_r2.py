"""Re-process all wardrobe items: download TG HD → rembg (original colors) → upload to R2.

Fixes washed-out colors in R2 from old pipeline.
After this, brief_card.py can use R2 directly without Telegram fallback.
"""
import asyncio
import sys
import os
import io
import uuid

sys.path.insert(0, "/app")
os.chdir("/app")


async def main():
    import numpy as np
    from PIL import Image
    from sqlalchemy import select, update
    from config import settings
    from telegram import Bot
    from core.redis import init_redis, get_redis
    from db.base import AsyncReadSession, AsyncWriteSession
    from db.models.wardrobe import WardrobeItem
    from services.image_processor import (
        exif_rotate, make_collage_thumbnail, soften_edges, pad_square_resize,
    )
    from services.storage.r2_storage import get_r2_storage
    from services.vision import _crop_bbox
    import base64
    import structlog

    logger = structlog.get_logger()
    await init_redis()
    redis = get_redis()
    bot = Bot(token=settings.telegram_bot_token)
    r2 = get_r2_storage()

    async with AsyncReadSession() as session:
        items = list((await session.execute(
            select(WardrobeItem).where(WardrobeItem.deleted_at.is_(None))
        )).scalars().all())

    print(f"Total items: {len(items)}")
    ok = 0
    errors = 0

    for item in items:
        if not item.photo_id:
            continue

        try:
            # 1. Download HD from Telegram
            f = await bot.get_file(item.photo_id)
            buf = io.BytesIO()
            await f.download_to_memory(buf)
            photo_bytes = buf.getvalue()
            photo_bytes = exif_rotate(photo_bytes)

            tg_img = Image.open(io.BytesIO(photo_bytes))
            print(f"  {item.type}: TG {tg_img.size}", end="")

            # 2. Run make_collage_thumbnail (has original colors fix)
            thumb = make_collage_thumbnail(photo_bytes, needs_bg_removal=True)
            thumb_img = Image.open(io.BytesIO(thumb))
            print(f" → thumb {thumb_img.size}", end="")

            # 3. Build full-size RGBA for R2 (mask from rembg + original colors)
            # Use the same pipeline but at higher resolution
            from services.image_processor import remove_background
            png_bytes = await remove_background(photo_bytes, redis=redis)
            png_bytes = soften_edges(png_bytes, radius=0.5)

            # Restore original colors
            mask_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            orig_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
            orig_img = orig_img.resize(mask_img.size, Image.LANCZOS)
            restored = Image.new("RGBA", mask_img.size)
            restored.paste(orig_img, (0, 0))
            restored.putalpha(mask_img.split()[3])
            # Alpha cleanup
            arr = np.array(restored)
            arr[arr[:, :, 3] < 80, 3] = 0
            restored = Image.fromarray(arr)

            r2_buf = io.BytesIO()
            restored.save(r2_buf, format="PNG")
            r2_bytes = r2_buf.getvalue()

            # 4. Upload to R2
            filename = f"{uuid.uuid4()}.png"
            owner_id = str(item.owner_id)
            key = await r2.upload_photo(
                r2_bytes, filename,
                owner_id=owner_id,
                content_type="image/png",
            )
            photo_url = r2.get_public_url(key) if settings.cloudflare_r2_cdn_url else key

            # 5. Update DB
            async with AsyncWriteSession() as session:
                await session.execute(
                    update(WardrobeItem)
                    .where(WardrobeItem.id == item.id)
                    .values(photo_url=photo_url)
                )
                await session.commit()

            # 6. Cache thumb
            thumb_b64 = base64.b64encode(thumb).decode()
            await redis.set(f"thumb:{item.id}", thumb_b64, ex=86400 * 7)

            ok += 1
            print(f" → R2 {len(r2_bytes)//1024}KB ✓")

        except Exception as e:
            errors += 1
            print(f" → ERROR: {e}")

    print(f"\nDone! ok={ok} errors={errors}")


if __name__ == "__main__":
    asyncio.run(main())
