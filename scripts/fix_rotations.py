"""Run Vision flat_lay_rotation for all items missing it, update bbox in DB."""
import asyncio
import sys
import os
import io
import base64

sys.path.insert(0, "/app")
os.chdir("/app")


async def main():
    from core.redis import init_redis, get_redis
    from core.anthropic_client import AnthropicPool
    from sqlalchemy import select, update
    from config import settings
    from telegram import Bot
    from db.base import AsyncReadSession, AsyncWriteSession
    from db.models.wardrobe import WardrobeItem
    from PIL import Image
    import structlog

    logger = structlog.get_logger()
    await init_redis()
    redis = get_redis()
    bot = Bot(token=settings.telegram_bot_token)
    pool = AnthropicPool(redis)

    async with AsyncReadSession() as session:
        items = list((await session.execute(
            select(WardrobeItem).where(WardrobeItem.deleted_at.is_(None))
        )).scalars().all())

    print(f"Total items: {len(items)}")
    fixed = 0
    skipped = 0
    errors = 0

    for item in items:
        bbox = item.bbox or {}
        if bbox.get("flat_lay_rotation"):
            skipped += 1
            print(f"  SKIP: {item.type} (already has rotation={bbox['flat_lay_rotation']})")
            continue

        if not item.photo_id:
            skipped += 1
            continue

        try:
            # Download photo
            f = await bot.get_file(item.photo_id)
            buf = io.BytesIO()
            await f.download_to_memory(buf)
            img = Image.open(io.BytesIO(buf.getvalue()))
            img.thumbnail((512, 512))
            buf2 = io.BytesIO()
            img.save(buf2, format='JPEG', quality=80)
            b64 = base64.b64encode(buf2.getvalue()).decode()

            # Ask Vision
            client, _ = await pool._next_client()
            resp = await client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=50,
                messages=[{
                    'role': 'user',
                    'content': [
                        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': b64}},
                        {'type': 'text', 'text': 'Garment flat-lay photo. What clockwise rotation (0, 90, 180, or 270 degrees) is needed so the neckline/collar/waistband is at the top and hem at bottom? Reply ONLY the number.'}
                    ]
                }]
            )
            rotation_str = resp.content[0].text.strip()
            rotation = int(rotation_str) if rotation_str.isdigit() else 0

            if rotation in (90, 180, 270):
                bbox["flat_lay_rotation"] = rotation
                async with AsyncWriteSession() as session:
                    await session.execute(
                        update(WardrobeItem)
                        .where(WardrobeItem.id == item.id)
                        .values(bbox=bbox)
                    )
                    await session.commit()

                # Clear thumb cache
                await redis.delete(f"thumb:{item.id}")

                fixed += 1
                print(f"  FIX: {item.type} → rotation={rotation}")
            else:
                skipped += 1
                print(f"  OK:  {item.type} → rotation=0 (already correct)")

        except Exception as e:
            errors += 1
            print(f"  ERR: {item.type}: {e}")

    print(f"\nDone! fixed={fixed} skipped={skipped} errors={errors}")
    if fixed > 0:
        print("Run scripts/reprocess_r2.py to regenerate thumbnails")


if __name__ == "__main__":
    asyncio.run(main())
