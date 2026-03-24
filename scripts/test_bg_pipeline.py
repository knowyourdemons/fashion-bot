#!/usr/bin/env python3
"""Test bg removal pipeline on real wardrobe photos.

Saves intermediate results to /tmp/bg_pipeline/ for visual inspection.
Run inside app container:
    docker exec docker-app-1 python3 /app/scripts/test_bg_pipeline.py
"""
import asyncio
import io
import os
import re
import sys

import httpx
import numpy as np
from PIL import Image

# Add app to path
sys.path.insert(0, "/app")


def safe(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "", s.replace(" ", "_"))[:25]


async def main():
    out = "/tmp/bg_pipeline"
    os.makedirs(out, exist_ok=True)

    from db.base import AsyncReadSession
    from db.models.wardrobe import WardrobeItem
    import sqlalchemy as sa

    async with AsyncReadSession() as session:
        result = await session.execute(
            sa.select(
                WardrobeItem.id, WardrobeItem.type, WardrobeItem.color,
                WardrobeItem.photo_id, WardrobeItem.photo_url, WardrobeItem.bbox,
            )
            .where(WardrobeItem.deleted_at.is_(None))
            .order_by(WardrobeItem.added_at.desc())
        )
        items = result.all()

    # Group by photo_id
    by_photo: dict[str, list] = {}
    for item in items:
        pid = item.photo_id or "none"
        by_photo.setdefault(pid, []).append(item)

    from services.image_processor import (
        _apply_clahe, _run_rmbg14, _run_cloth_seg, _run_grabcut,
        _postprocess_mask, _check_mask_quality_v2,
        exif_rotate, auto_brightness, soften_edges, pad_square_resize,
        _bbox_crop_rgba, remove_background,
    )
    from services.vision import _crop_bbox

    for pid, group in by_photo.items():
        is_multi = len(group) > 1
        label = "MULTI" if is_multi else "SINGLE"
        print(f"\n{'='*60}")
        print(f"{label} photo ({len(group)} items): {pid[:30]}...")

        # Download current R2 result for comparison
        for item in group:
            if not item.photo_url:
                continue
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(item.photo_url)
            fname = f"{out}/{label}_{safe(item.type)}_current.png"
            with open(fname, "wb") as f:
                f.write(r.content)

        # Try to get original from Telegram
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                    params={"file_id": pid},
                )
                if r.json().get("ok"):
                    file_path = r.json()["result"]["file_path"]
                    r2 = await client.get(
                        f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
                        timeout=15,
                    )
                    original = r2.content
                else:
                    print(f"  Telegram file expired, skipping pipeline test")
                    continue
        except Exception as e:
            print(f"  Can't get original: {e}")
            continue

        original = exif_rotate(original)
        img = Image.open(io.BytesIO(original))
        print(f"  Original: {img.size} {img.mode}")

        # Save original
        with open(f"{out}/{label}_original.jpg", "wb") as f:
            f.write(original)

        # Step 1: CLAHE
        enhanced = _apply_clahe(original)
        with open(f"{out}/{label}_1_clahe.jpg", "wb") as f:
            f.write(enhanced)

        # Step 2: Full-photo bg removal
        try:
            rmbg_full = _run_rmbg14(enhanced)
            rmbg_full = _postprocess_mask(rmbg_full)
            with open(f"{out}/{label}_2_rmbg_full.png", "wb") as f:
                f.write(rmbg_full)
            q = _check_mask_quality_v2(rmbg_full)
            alpha = np.array(Image.open(io.BytesIO(rmbg_full)).convert("RGBA").split()[3])
            print(f"  RMBG full: opaque={np.sum(alpha>128)/alpha.size:.1%} quality={q}")
        except Exception as e:
            print(f"  RMBG full failed: {e}")
            rmbg_full = None

        # For each item: test both strategies
        for item in group:
            bbox = item.bbox
            if not bbox:
                continue
            name = safe(item.type)
            bbox_area = float(bbox.get("w", 1)) * float(bbox.get("h", 1))
            print(f"\n  Item: {item.type} (bbox area={bbox_area:.2f})")

            # Strategy A: crop first → rembg (better for multi-item)
            try:
                crop = _crop_bbox(enhanced, bbox)
                rmbg_crop = _run_rmbg14(crop)
                rmbg_crop = _postprocess_mask(rmbg_crop)
                thumb_a = pad_square_resize(soften_edges(rmbg_crop), 400)
                with open(f"{out}/{label}_{name}_A_crop_first.png", "wb") as f:
                    f.write(thumb_a)
                a_alpha = np.array(Image.open(io.BytesIO(thumb_a)).convert("RGBA").split()[3])
                print(f"    A (crop→rembg): opaque={np.sum(a_alpha>128)/a_alpha.size:.1%}")
            except Exception as e:
                print(f"    A failed: {e}")

            # Strategy B: rembg full → bbox crop (better for single-item)
            if rmbg_full:
                try:
                    cropped = _bbox_crop_rgba(rmbg_full, bbox)
                    thumb_b = pad_square_resize(cropped, 400)
                    with open(f"{out}/{label}_{name}_B_rembg_first.png", "wb") as f:
                        f.write(thumb_b)
                    b_alpha = np.array(Image.open(io.BytesIO(thumb_b)).convert("RGBA").split()[3])
                    print(f"    B (rembg→crop): opaque={np.sum(b_alpha>128)/b_alpha.size:.1%}")
                except Exception as e:
                    print(f"    B failed: {e}")

            # Strategy C: cloth-seg on crop
            try:
                crop = _crop_bbox(enhanced, bbox)
                cloth = _run_cloth_seg(crop)
                cloth = _postprocess_mask(cloth)
                thumb_c = pad_square_resize(soften_edges(cloth), 400)
                with open(f"{out}/{label}_{name}_C_clothseg.png", "wb") as f:
                    f.write(thumb_c)
                c_alpha = np.array(Image.open(io.BytesIO(thumb_c)).convert("RGBA").split()[3])
                print(f"    C (cloth-seg):   opaque={np.sum(c_alpha>128)/c_alpha.size:.1%}")
            except Exception as e:
                print(f"    C failed: {e}")

    print(f"\n{'='*60}")
    print(f"Results saved to {out}/")
    print(f"Copy to host: docker cp docker-app-1:{out} /tmp/bg_pipeline")


if __name__ == "__main__":
    from config import settings
    asyncio.run(main())
