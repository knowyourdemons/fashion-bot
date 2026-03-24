#!/usr/bin/env python3
"""Simulate full production pipeline on 7 group photos as if mama sent them."""
import asyncio, io, os, numpy as np, sys
from PIL import Image
sys.path.insert(0, "/app")

PHOTO_ITEMS = {
    "eaf5eec4": [
        {"name": "колготки_горох", "bbox": {"x": 0.0, "y": 0.0, "w": 0.22, "h": 0.8}},
        {"name": "пижама_верх", "bbox": {"x": 0.2, "y": 0.0, "w": 0.35, "h": 0.5}},
        {"name": "пижама_низ", "bbox": {"x": 0.25, "y": 0.45, "w": 0.3, "h": 0.55}},
        {"name": "леггинсы_бежев", "bbox": {"x": 0.52, "y": 0.0, "w": 0.15, "h": 0.9}},
        {"name": "леггинсы_бордо", "bbox": {"x": 0.65, "y": 0.0, "w": 0.18, "h": 0.9}},
        {"name": "шорты_минни", "bbox": {"x": 0.02, "y": 0.7, "w": 0.25, "h": 0.3}},
    ],
    "fa2f0326": [
        {"name": "свитер_серый", "bbox": {"x": 0.0, "y": 0.45, "w": 0.33, "h": 0.55}},
        {"name": "футболка_бантик", "bbox": {"x": 0.18, "y": 0.0, "w": 0.3, "h": 0.42}},
        {"name": "футболка_ежик", "bbox": {"x": 0.42, "y": 0.0, "w": 0.28, "h": 0.42}},
        {"name": "шорты_голубые", "bbox": {"x": 0.37, "y": 0.52, "w": 0.22, "h": 0.25}},
        {"name": "леггинсы_сердца", "bbox": {"x": 0.68, "y": 0.2, "w": 0.25, "h": 0.7}},
    ],
    "5c198098": [
        {"name": "лонгслив_цветы", "bbox": {"x": 0.0, "y": 0.05, "w": 0.38, "h": 0.85}},
        {"name": "платье_серое", "bbox": {"x": 0.33, "y": 0.02, "w": 0.35, "h": 0.88}},
        {"name": "колготки_полос", "bbox": {"x": 0.63, "y": 0.1, "w": 0.32, "h": 0.7}},
    ],
    "bebca692": [
        {"name": "штаны_розовые", "bbox": {"x": 0.0, "y": 0.0, "w": 0.28, "h": 0.48}},
        {"name": "носки_вишня", "bbox": {"x": 0.22, "y": 0.15, "w": 0.12, "h": 0.2}},
        {"name": "майка_лиловая", "bbox": {"x": 0.3, "y": 0.0, "w": 0.25, "h": 0.42}},
        {"name": "свитер_мишка", "bbox": {"x": 0.12, "y": 0.48, "w": 0.35, "h": 0.48}},
        {"name": "блузка_цветы", "bbox": {"x": 0.52, "y": 0.35, "w": 0.38, "h": 0.55}},
        {"name": "тапки_желтые", "bbox": {"x": 0.55, "y": 0.0, "w": 0.12, "h": 0.1}},
    ],
    "777c908d": [
        {"name": "леггинсы_роз1", "bbox": {"x": 0.08, "y": 0.0, "w": 0.42, "h": 0.48}},
        {"name": "шорты_бантики", "bbox": {"x": 0.4, "y": 0.32, "w": 0.32, "h": 0.22}},
        {"name": "носки_пачка", "bbox": {"x": 0.55, "y": 0.0, "w": 0.25, "h": 0.2}},
        {"name": "леггинсы_роз2", "bbox": {"x": 0.18, "y": 0.55, "w": 0.5, "h": 0.4}},
    ],
    "5a41bb31": [
        {"name": "платье_леопард", "bbox": {"x": 0.12, "y": 0.02, "w": 0.32, "h": 0.72}},
        {"name": "трусики_розов", "bbox": {"x": 0.42, "y": 0.02, "w": 0.1, "h": 0.12}},
        {"name": "леггинсы_горох", "bbox": {"x": 0.08, "y": 0.55, "w": 0.3, "h": 0.42}},
        {"name": "футболка_дейзи", "bbox": {"x": 0.52, "y": 0.2, "w": 0.38, "h": 0.52}},
        {"name": "футболка_sweet", "bbox": {"x": 0.48, "y": 0.0, "w": 0.3, "h": 0.25}},
    ],
    "a9d0c645": [
        {"name": "колготки_горох2", "bbox": {"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.88}},
        {"name": "пижама_феи_верх", "bbox": {"x": 0.18, "y": 0.0, "w": 0.4, "h": 0.5}},
        {"name": "пижама_феи_низ", "bbox": {"x": 0.22, "y": 0.45, "w": 0.35, "h": 0.52}},
        {"name": "леггинсы_беж2", "bbox": {"x": 0.5, "y": 0.05, "w": 0.15, "h": 0.85}},
        {"name": "леггинсы_бордо2", "bbox": {"x": 0.63, "y": 0.0, "w": 0.2, "h": 0.9}},
        {"name": "шорты_минни2", "bbox": {"x": 0.02, "y": 0.72, "w": 0.22, "h": 0.28}},
    ],
}

async def main():
    from services.image_processor import (
        _apply_clahe, _run_rmbg14, _run_cloth_seg,
        _postprocess_mask, _check_mask_quality_v2, _intersect_masks,
        _refine_mask_grabcut,
        exif_rotate, soften_edges, pad_square_resize,
    )
    from services.vision import _crop_bbox

    out = "/tmp/mama_test"
    os.makedirs(out, exist_ok=True)

    report = []

    for photo_id, items in PHOTO_ITEMS.items():
        # Find file matching photo_id prefix
        matches = [f for f in os.listdir("/tmp/gyazo_photos") if f.startswith(photo_id)]
        if not matches:
            print(f"\nPhoto {photo_id}: NOT FOUND")
            continue
        path = f"/tmp/gyazo_photos/{matches[0]}"

        raw = open(path, "rb").read()
        raw = exif_rotate(raw)
        img = Image.open(io.BytesIO(raw))
        enhanced = _apply_clahe(raw)
        print(f"\nPhoto {photo_id[:8]}: {img.size}, {len(items)} items")

        for item in items:
            name = item["name"]
            bbox = item["bbox"]

            crop = _crop_bbox(enhanced, bbox, padding=0.04)
            enhanced_crop = _apply_clahe(crop)

            cloth_r = None
            rmbg_r = None
            try:
                cloth_r = _run_cloth_seg(enhanced_crop)
                cloth_r = _postprocess_mask(cloth_r)
                # GrabCut refine if cloth-seg has excess bg (55-75%)
                _ci = Image.open(io.BytesIO(cloth_r)).convert("RGBA")
                _ca = np.array(_ci.split()[3])
                _cr = np.sum(_ca > 128) / _ca.size
                if 0.55 < _cr < 0.75:
                    cloth_r = _refine_mask_grabcut(crop, cloth_r)
                    cloth_r = _postprocess_mask(cloth_r)
            except:
                pass
            try:
                rmbg_r = _run_rmbg14(enhanced_crop)
                rmbg_r = _postprocess_mask(rmbg_r)
            except:
                pass

            result = None
            model_used = "none"
            if cloth_r and _check_mask_quality_v2(cloth_r):
                result = cloth_r
                model_used = "cloth"
            elif cloth_r and rmbg_r:
                inter = _intersect_masks(rmbg_r, cloth_r)
                inter = _postprocess_mask(inter)
                if _check_mask_quality_v2(inter):
                    result = inter
                    model_used = "inter"
                else:
                    _ci2 = Image.open(io.BytesIO(cloth_r)).convert("RGBA")
                    _co2 = np.sum(np.array(_ci2.split()[3]) > 128) / (_ci2.size[0]*_ci2.size[1])
                    if _co2 >= 0.05:
                        result = cloth_r
                        model_used = "cloth+"
                    else:
                        result = rmbg_r
                        model_used = "rmbg+"
            elif rmbg_r:
                result = rmbg_r
                model_used = "rmbg"
            else:
                result = crop
                model_used = "orig"

            result = soften_edges(result, radius=1.5)
            thumb = pad_square_resize(result, 400)

            with open(f"{out}/{photo_id[:8]}_{name}.png", "wb") as f:
                f.write(thumb)

            t = Image.open(io.BytesIO(thumb)).convert("RGBA")
            alpha = np.array(t.split()[3])
            opaque = np.sum(alpha > 128) / alpha.size

            q = "✅" if 0.08 <= opaque <= 0.60 else ("⚠️фон" if opaque > 0.60 else "❌пусто")
            print(f"  {name:22s} {model_used:5s} {opaque:5.0%} {q}")
            report.append({"model": model_used, "quality": q})

    print(f"\n{'='*50}")
    total = len(report)
    good = sum(1 for r in report if "✅" in r["quality"])
    warn = sum(1 for r in report if "⚠️" in r["quality"])
    bad = sum(1 for r in report if "❌" in r["quality"])
    cloth = sum(1 for r in report if r["model"] == "cloth")
    rmbg = sum(1 for r in report if r["model"] == "rmbg")
    print(f"Total: {total} | ✅ {good} | ⚠️ {warn} | ❌ {bad}")
    print(f"cloth-seg: {cloth} | rmbg: {rmbg}")
    print(f"Success rate: {good/total:.0%}" if total > 0 else "No items processed")

asyncio.run(main())
