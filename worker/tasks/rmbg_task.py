"""
Background removal task: crop + rembg + R2 upload.

Deferred from the photo upload flow so the user gets an immediate response.
Runs in the fast worker (HIGH priority queue).
"""
import uuid

import httpx
import structlog

from config import settings
from worker.fast_worker import register

logger = structlog.get_logger()


@register("rmbg_process")
async def process_rmbg(payload: dict) -> dict:
    """Download photo from Telegram, crop bbox, remove background, upload to R2, update DB."""
    item_id = uuid.UUID(payload["item_id"])
    file_id = payload["file_id"]
    owner_id = payload.get("owner_id", "")
    bbox = payload.get("bbox")

    logger.info("rmbg_process.start", item_id=str(item_id), file_id=file_id[:20])

    # 1. Download original photo from Telegram
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]

        r2_resp = await client.get(
            f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
            timeout=15.0,
        )
        r2_resp.raise_for_status()
        photo_bytes = r2_resp.content

    if not photo_bytes:
        logger.warning("rmbg_process.empty_photo", item_id=str(item_id))
        return {"status": "skip", "reason": "empty_photo"}

    # 1b. EXIF rotate (phone photos may be sideways)
    from services.image_processor import exif_rotate
    try:
        photo_bytes = exif_rotate(photo_bytes)
    except Exception as e:
        logger.warning("rmbg_process.exif_failed", error=str(e))

    from services.image_processor import remove_background, soften_edges
    from core.redis import get_redis
    redis = None
    try:
        redis = get_redis()
    except Exception:
        pass

    # 2. Strategy depends on whether this is a multi-item photo (small bbox)
    #    Multi-item: crop first → bg removal on isolated item (avoids neighbor bleed)
    #    Single-item: bg removal on full photo → better context for the model
    is_multi_item = False
    if bbox:
        bbox_area = float(bbox.get("w", 1.0)) * float(bbox.get("h", 1.0))
        is_multi_item = bbox_area < 0.55  # multi-item bboxes are typically <0.4

    good_crop = True

    if is_multi_item and bbox:
        # MULTI-ITEM: tight crop → cloth-seg first (knows clothing vs floor),
        # RMBG fallback. Tight crop (2% padding) to minimize neighbor bleed.
        from services.vision import _crop_bbox, _check_crop_quality
        from services.image_processor import (
            _apply_clahe, _run_cloth_seg, _run_rmbg14,
            _postprocess_mask, _check_mask_quality_v2, pad_square_resize,
        )
        try:
            crop_bytes = _crop_bbox(photo_bytes, bbox, padding=0.04)
        except Exception as e:
            logger.warning("rmbg_process.crop_failed", item_id=str(item_id), error=str(e))
            crop_bytes = photo_bytes

        enhanced_crop = _apply_clahe(crop_bytes)
        png_bytes = None

        # Run both models — we may need the intersection or GrabCut refinement
        cloth_result = None
        rmbg_result = None

        try:
            cloth_result = _run_cloth_seg(enhanced_crop)
            cloth_result = _postprocess_mask(cloth_result)

            # If cloth-seg has excess background (55-75%), refine with GrabCut
            from services.image_processor import _refine_mask_grabcut
            _ci = Image.open(io.BytesIO(cloth_result)).convert("RGBA")
            _ca = np.array(_ci.split()[3])
            _cr = np.sum(_ca > 128) / _ca.size
            if 0.55 < _cr < 0.75:
                cloth_result = _refine_mask_grabcut(crop_bytes, cloth_result)
                cloth_result = _postprocess_mask(cloth_result)
                logger.info("rmbg_process.grabcut_refined", before=f"{_cr:.0%}")
        except Exception as e:
            logger.warning("rmbg_process.cloth_seg_failed", error=str(e))

        try:
            rmbg_result = _run_rmbg14(enhanced_crop)
            rmbg_result = _postprocess_mask(rmbg_result)
        except Exception as e:
            logger.warning("rmbg_process.rmbg14_failed", error=str(e))

        # Strategy selection:
        # 1. cloth-seg alone if quality ok (best for removing floor)
        # 2. Intersection of both masks (cloth-seg knowledge + RMBG edges)
        # 3. RMBG alone as last resort
        if cloth_result and _check_mask_quality_v2(cloth_result):
            png_bytes = cloth_result
            logger.info("rmbg_process.model_ok", model="cloth_seg")
        elif cloth_result and rmbg_result:
            # Intersection: keeps only pixels where BOTH models agree = foreground
            # cloth-seg removes floor, RMBG provides sharp edges
            from services.image_processor import _intersect_masks
            intersected = _intersect_masks(rmbg_result, cloth_result)
            intersected = _postprocess_mask(intersected)
            if _check_mask_quality_v2(intersected):
                png_bytes = intersected
                logger.info("rmbg_process.model_ok", model="intersect")
            else:
                # Intersection too aggressive — pick the better single mask.
                # If cloth-seg has <5% opaque, it missed the garment → use RMBG.
                cloth_img = Image.open(io.BytesIO(cloth_result)).convert("RGBA")
                cloth_opaque = np.sum(np.array(cloth_img.split()[3]) > 128)
                cloth_ratio = cloth_opaque / (cloth_img.size[0] * cloth_img.size[1])
                if cloth_ratio >= 0.05:
                    png_bytes = cloth_result
                    logger.info("rmbg_process.model_ok", model="cloth_seg_loose")
                else:
                    png_bytes = rmbg_result
                    logger.info("rmbg_process.model_ok", model="rmbg14_rescue")
        elif rmbg_result:
            png_bytes = rmbg_result
            logger.info("rmbg_process.model_ok", model="rmbg14_fallback")
        else:
            png_bytes = crop_bytes

        try:
            png_bytes = soften_edges(png_bytes, radius=1.5)
        except Exception:
            pass
        good_crop = _check_crop_quality(png_bytes)
        logger.info("rmbg_process.strategy", strategy="multi_cloth_first", bbox_area=f"{bbox_area:.2f}")
    else:
        # SINGLE-ITEM: bg removal on full photo (model has full context)
        png_bytes = await remove_background(photo_bytes, redis=redis)
        try:
            png_bytes = soften_edges(png_bytes, radius=1.5)
        except Exception:
            pass

        # Crop by bbox if needed (for single-item with small bbox)
        if bbox:
            from services.image_processor import _bbox_crop_rgba
            from services.vision import _check_crop_quality
            try:
                png_bytes = _bbox_crop_rgba(png_bytes, bbox)
            except Exception as e:
                logger.warning("rmbg_process.crop_failed", item_id=str(item_id), error=str(e))
            good_crop = _check_crop_quality(png_bytes)
        logger.info("rmbg_process.strategy", strategy="rembg_first", bbox_area=f"{float(bbox.get('w',1))*float(bbox.get('h',1)):.2f}" if bbox else "1.00")

    # 5. Upload to R2
    is_png = png_bytes[:4] == b'\x89PNG'
    ext = "png" if is_png else "jpg"
    content_type = "image/png" if is_png else "image/jpeg"

    from services.storage.r2_storage import get_r2_storage
    r2 = get_r2_storage()
    filename = f"{uuid.uuid4()}.{ext}"
    key = await r2.upload_photo(
        png_bytes, filename,
        owner_id=owner_id,
        content_type=content_type,
    )
    photo_url = r2.get_public_url(key) if settings.cloudflare_r2_cdn_url else key

    # 6. Update WardrobeItem in DB
    import sqlalchemy as sa
    from db.base import AsyncWriteSession
    from db.models.wardrobe import WardrobeItem

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(WardrobeItem)
            .where(WardrobeItem.id == item_id)
            .values(
                photo_url=photo_url,
                show_in_collage=good_crop,
            )
        )
        await session.commit()

    logger.info(
        "rmbg_process.done",
        item_id=str(item_id),
        photo_url=photo_url[:60] if photo_url else None,
        good_crop=good_crop,
    )

    # 7. Generate and cache collage thumbnail (400×400 retina)
    if redis:
        try:
            from services.image_processor import pad_square_resize, auto_brightness
            import base64 as _b64
            # png_bytes is already bg-removed + edge-softened
            thumb_bytes = auto_brightness(png_bytes)
            thumb_bytes = pad_square_resize(thumb_bytes, 400)
            thumb_b64 = _b64.b64encode(thumb_bytes).decode()
            await redis.set(f"thumb:{item_id}", thumb_b64, ex=86400 * 7)  # 7 day TTL
            logger.info("rmbg_process.thumb_cached", item_id=str(item_id), size=len(thumb_bytes))
        except Exception as e:
            logger.warning("rmbg_process.thumb_failed", error=str(e))

    # 8. Invalidate wardrobe summary cache
    if redis and owner_id:
        try:
            await redis.delete(f"wardrobe_summary:{owner_id}")
        except Exception:
            pass

    return {"status": "ok", "item_id": str(item_id), "photo_url": photo_url}
