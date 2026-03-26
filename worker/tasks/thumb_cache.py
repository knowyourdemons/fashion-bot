"""Warm thumbnail cache for all wardrobe items.

Runs daily at 4:00 — ensures collage rendering is fast (cache hit = 0.3s).
Only rebuilds missing cache entries (items without thumb in Redis).
"""
import asyncio
import base64
import io

import structlog
from PIL import Image
from sqlalchemy import select

from config import settings
from db.base import AsyncReadSession
from db.models.wardrobe import WardrobeItem
from services.brief_card import _get_cached_thumb, _cache_thumb

logger = structlog.get_logger()


async def run() -> None:
    """Check all items, rebuild missing thumbnails from R2."""
    try:
        async with asyncio.timeout(300):  # 5 min max
            await _warm_cache()
    except asyncio.TimeoutError:
        logger.error("thumb_cache.timeout")
    except Exception as e:
        logger.error("thumb_cache.error", error=str(e))


async def _warm_cache() -> None:
    from services.image_processor import soften_edges

    async with AsyncReadSession() as session:
        items = list((await session.execute(
            select(WardrobeItem).where(WardrobeItem.deleted_at.is_(None))
        )).scalars().all())

    built = 0
    cached = 0

    for item in items:
        item_id = str(item.id)

        # Skip if already cached
        existing = await _get_cached_thumb(item_id)
        if existing:
            cached += 1
            continue

        # Build from R2 (already has original colors + bg removed)
        if not item.photo_url:
            continue

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(item.photo_url)
                if resp.status_code != 200:
                    continue
                photo_bytes = resp.content

            img = Image.open(io.BytesIO(photo_bytes))
            if img.mode not in ("RGBA", "LA", "PA"):
                continue  # not bg-removed, skip

            img = img.convert("RGBA")

            # Trim + resize + soften
            alpha_bbox = img.split()[3].getbbox()
            if alpha_bbox:
                p = 5
                alpha_bbox = (
                    max(0, alpha_bbox[0] - p),
                    max(0, alpha_bbox[1] - p),
                    min(img.size[0], alpha_bbox[2] + p),
                    min(img.size[1], alpha_bbox[3] + p),
                )
                img = img.crop(alpha_bbox)

            img.thumbnail((400, 400), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            thumb = soften_edges(buf.getvalue(), radius=0.5)

            await _cache_thumb(item_id, thumb)
            built += 1

        except Exception as e:
            logger.warning("thumb_cache.item_failed", item_id=item_id, error=str(e))

    logger.info("thumb_cache.done", total=len(items), cached=cached, built=built)
