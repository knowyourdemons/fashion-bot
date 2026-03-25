"""
Обработка фото перед отправкой в Vision API:
1. Проверка размера (max 20MB)
2. Resize до 1024×1024
3. Очистка EXIF (GDPR)
4. Perceptual hash для дублей
5. Удаление фона (RMBG-1.4 → cloth-segmentation → GrabCut → remove.bg API)
"""
import asyncio
import io
import math
import threading
from typing import Optional

import imagehash
import numpy as np
import onnxruntime as ort
from PIL import Image

from exceptions import DuplicateItemError, ImageTooLargeError

# ── Singleton ONNX sessions for background removal ─────────────────
_RMBG14_PATH = "/root/.u2net/rmbg14_quantized.onnx"

_rmbg_session: Optional[ort.InferenceSession] = None
_rmbg_lock = threading.Lock()

_CLOTH_SEG_PATH = "/root/.u2net/cloth_seg_u2net.onnx"
_cloth_seg_session: Optional[ort.InferenceSession] = None
_cloth_seg_lock = threading.Lock()

# Limit concurrent RMBG inferences to prevent OOM (each peak ~600MB)
_rmbg_semaphore = asyncio.Semaphore(1)



def _get_rmbg_session() -> ort.InferenceSession:
    """Thread-safe singleton for RMBG-1.4 quantized ONNX model."""
    global _rmbg_session
    if _rmbg_session is None:
        with _rmbg_lock:
            if _rmbg_session is None:  # double-check after acquiring lock
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.inter_op_num_threads = 1
                _rmbg_session = ort.InferenceSession(
                    _RMBG14_PATH, opts, providers=["CPUExecutionProvider"]
                )
    return _rmbg_session



def _get_cloth_seg_session() -> ort.InferenceSession:
    """Thread-safe singleton for cloth-segmentation U2Net ONNX model (clothing-specific)."""
    global _cloth_seg_session
    if _cloth_seg_session is None:
        with _cloth_seg_lock:
            if _cloth_seg_session is None:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.inter_op_num_threads = 1
                _cloth_seg_session = ort.InferenceSession(
                    _CLOTH_SEG_PATH, opts, providers=["CPUExecutionProvider"]
                )
    return _cloth_seg_session




def _run_rmbg14(image_bytes: bytes) -> bytes:
    """Run RMBG-1.4 quantized ONNX model: returns PNG bytes with transparent background.

    RMBG-1.4 uses different preprocessing than silueta:
    - Input: 1x3x1024x1024, normalized to [0,1] (no mean/std normalization for quantized)
    - Output: 1x1x1024x1024 sigmoid mask

    Enhanced pipeline:
    - Pre-crop to center 80% to reduce background noise
    - Post-process mask with morphological cleanup
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size

    # Pad to square (preserve aspect ratio) then resize to 1024×1024
    side = max(orig_w, orig_h)
    padded = Image.new("RGB", (side, side), (128, 128, 128))
    padded.paste(img, ((side - orig_w) // 2, (side - orig_h) // 2))
    resized = padded.resize((1024, 1024), Image.BILINEAR)
    arr = np.array(resized, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]  # (1, 3, 1024, 1024)

    sess = _get_rmbg_session()
    input_name = sess.get_inputs()[0].name
    output_name = sess.get_outputs()[0].name
    mask = sess.run([output_name], {input_name: arr})[0]  # (1,1,1024,1024)
    mask = mask.squeeze()  # (1024, 1024)

    # Sigmoid mask is already in [0,1] range; clamp and scale to 0-255
    mask = np.clip(mask, 0.0, 1.0)
    mask = (mask * 255).astype(np.uint8)

    # ── Post-processing: morphological cleanup ──
    # Threshold to binary (remove semi-transparent noise)
    mask[mask < 30] = 0
    mask[mask > 225] = 255
    # Erode then dilate to remove small artifacts at edges
    from PIL import ImageFilter
    mask_img_raw = Image.fromarray(mask)
    # Gentle morphological close: dilate then erode (fills small holes)
    mask_img_raw = mask_img_raw.filter(ImageFilter.MaxFilter(3))  # dilate
    mask_img_raw = mask_img_raw.filter(ImageFilter.MinFilter(3))  # erode
    # Gentle blur to smooth jagged edges
    mask_img_raw = mask_img_raw.filter(ImageFilter.GaussianBlur(radius=1))

    # Crop mask back to original aspect ratio (remove padding)
    mask_square = mask_img_raw.resize((side, side), Image.BILINEAR)
    left = (side - orig_w) // 2
    top_pad = (side - orig_h) // 2
    mask_img = mask_square.crop((left, top_pad, left + orig_w, top_pad + orig_h))

    # Apply mask to original image
    img_rgba = img.copy().convert("RGBA")
    img_rgba.putalpha(mask_img)

    buf = io.BytesIO()
    img_rgba.save(buf, format="PNG")
    return buf.getvalue()


# ── Collage thumbnail pipeline ─────────────────────────────────────

THUMB_SIZE = 400  # retina for 200px card


def exif_rotate(image_bytes: bytes) -> bytes:
    """Apply EXIF orientation and strip EXIF. Must be first in pipeline."""
    from PIL import ImageOps
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    buf = io.BytesIO()
    fmt = "PNG" if img.mode == "RGBA" else "JPEG"
    img.save(buf, format=fmt, quality=90)
    return buf.getvalue()


def auto_brightness(image_bytes: bytes) -> bytes:
    """Gentle brightness/contrast correction for dark phone photos."""
    from PIL import ImageOps, ImageStat
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode == "RGBA":
        # Only adjust RGB channels, preserve alpha
        r, g, b, a = img.split()
        rgb = Image.merge("RGB", (r, g, b))
        stat = ImageStat.Stat(rgb)
        mean_brightness = sum(stat.mean) / 3.0
        # Only correct if genuinely dark (< 90 out of 255)
        if mean_brightness < 90:
            rgb = ImageOps.autocontrast(rgb, cutoff=1)
        result = rgb.convert("RGBA")
        result.putalpha(a)
    else:
        stat = ImageStat.Stat(img.convert("RGB"))
        mean_brightness = sum(stat.mean) / 3.0
        if mean_brightness < 90:
            img = ImageOps.autocontrast(img.convert("RGB"), cutoff=1)
        result = img
    buf = io.BytesIO()
    fmt = "PNG" if result.mode == "RGBA" else "JPEG"
    result.save(buf, format=fmt, quality=90)
    return buf.getvalue()


def soften_edges(png_bytes: bytes, radius: float = 1.5) -> bytes:
    """Gaussian blur on alpha channel to smooth rembg artifacts."""
    from PIL import ImageFilter
    img = Image.open(io.BytesIO(png_bytes))
    if img.mode != "RGBA":
        return png_bytes
    r, g, b, a = img.split()
    a = a.filter(ImageFilter.GaussianBlur(radius=radius))
    img = Image.merge("RGBA", (r, g, b, a))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _bbox_crop_rgba(png_bytes: bytes, bbox: dict, size: int = THUMB_SIZE) -> bytes:
    """Crop an already-processed RGBA thumbnail by Vision bbox, then re-pad and resize.

    Used AFTER rembg: the full photo has bg removed, now we isolate one item
    by its bbox coordinates. The result is cleaner because rembg had full context.
    """
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    iw, ih = img.size

    x = max(0.0, min(1.0, float(bbox.get("x", 0.0))))
    y = max(0.0, min(1.0, float(bbox.get("y", 0.0))))
    w = max(0.05, min(1.0 - x, float(bbox.get("w", 1.0))))
    h = max(0.05, min(1.0 - y, float(bbox.get("h", 1.0))))

    # Add 10% padding around bbox for context
    pad_x = w * 0.10
    pad_y = h * 0.10
    x = max(0.0, x - pad_x)
    y = max(0.0, y - pad_y)
    w = min(1.0 - x, w + 2 * pad_x)
    h = min(1.0 - y, h + 2 * pad_y)

    left = int(x * iw)
    top = int(y * ih)
    right = int((x + w) * iw)
    bottom = int((y + h) * ih)

    cropped = img.crop((left, top, right, bottom))

    # Auto-trim transparent edges
    alpha = cropped.split()[3]
    trim_bbox = alpha.getbbox()
    if trim_bbox:
        pad_px = int(min(cropped.size) * 0.05)
        trim_bbox = (
            max(0, trim_bbox[0] - pad_px),
            max(0, trim_bbox[1] - pad_px),
            min(cropped.width, trim_bbox[2] + pad_px),
            min(cropped.height, trim_bbox[3] + pad_px),
        )
        cropped = cropped.crop(trim_bbox)

    # Pad to square + resize
    cw, ch = cropped.size
    side = max(cw, ch)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(cropped, ((side - cw) // 2, (side - ch) // 2))
    square = square.resize((size, size), Image.LANCZOS)

    buf = io.BytesIO()
    square.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _run_grabcut(image_bytes: bytes) -> bytes | None:
    """Remove background using OpenCV GrabCut algorithm.

    GrabCut uses iterative graph-cut to separate foreground from background.
    Works well on textured backgrounds (carpet, wood floor, bedsheets)
    where RMBG fails. Uses center rectangle as initial foreground hint.

    Returns PNG bytes with alpha channel, or None on failure.
    """
    try:
        import cv2
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)

        h, w = arr.shape[:2]
        # Initialize mask: assume garment is in center 70% of image
        mask = np.zeros((h, w), np.uint8)
        margin_x = int(w * 0.05)
        margin_y = int(h * 0.05)
        rect = (margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)

        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)

        cv2.grabCut(arr, mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)

        # Mask: 0=bg, 1=fg, 2=probable_bg, 3=probable_fg
        fg_mask = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        fg_mask = cv2.GaussianBlur(fg_mask, (3, 3), 0)

        # Apply mask as alpha
        img_rgba = img.copy().convert("RGBA")
        mask_pil = Image.fromarray(fg_mask)
        img_rgba.putalpha(mask_pil)

        buf = io.BytesIO()
        img_rgba.save(buf, format="PNG")

        import structlog
        structlog.get_logger().info("rmbg.grabcut_done", size=f"{w}x{h}")
        return buf.getvalue()
    except Exception as e:
        import structlog
        structlog.get_logger().warning("rmbg.grabcut_failed", error=str(e))
        return None


def _apply_clahe(image_bytes: bytes) -> bytes:
    """Apply CLAHE to L channel to boost local contrast between garment and textured background.

    Helps RMBG/cloth-seg distinguish clothing from couches, carpets, wood floors
    by enhancing local contrast differences invisible in raw photos.
    """
    try:
        import cv2
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        result = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        img_out = Image.fromarray(result)
        buf = io.BytesIO()
        img_out.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception:
        return image_bytes


def _postprocess_mask(png_bytes: bytes) -> bytes:
    """Post-process bg-removed image: keep largest connected component, morphological cleanup.

    Removes disconnected background fragments (couch corners, carpet pieces)
    that the model incorrectly classified as foreground.
    """
    try:
        import cv2
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        r, g, b, a = img.split()
        alpha = np.array(a)

        # Binarize for connected component analysis
        binary = (alpha > 128).astype(np.uint8)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

        if num_labels <= 2:
            # 0=background, 1=single foreground — nothing to filter
            return png_bytes

        # Find the largest foreground component (label 0 is always background)
        largest_label = 1
        largest_area = 0
        for label_idx in range(1, num_labels):
            area = stats[label_idx, cv2.CC_STAT_AREA]
            if area > largest_area:
                largest_area = area
                largest_label = label_idx

        # Keep the largest component + any component ≥15% of its area.
        # This preserves garment parts (sleeves, collars) that detach from
        # the main body during segmentation, while still removing tiny noise.
        cleaned = np.zeros_like(alpha)
        for label_idx in range(1, num_labels):
            area = stats[label_idx, cv2.CC_STAT_AREA]
            if area >= largest_area * 0.15:
                cleaned[labels == label_idx] = alpha[labels == label_idx]

        # Morphological close to fill small holes in the main component
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)

        # Gentle blur to smooth edges
        cleaned = cv2.GaussianBlur(cleaned, (3, 3), 0)

        img.putalpha(Image.fromarray(cleaned))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return png_bytes


def _intersect_masks(png_a: bytes, png_b: bytes) -> bytes:
    """Intersect two RGBA masks: keep pixels where BOTH have high alpha.

    Combines RMBG (sharp edges, keeps floor) with cloth-seg (knows clothing,
    rough edges) — intersection removes floor while preserving garment shape.
    """
    img_a = Image.open(io.BytesIO(png_a)).convert("RGBA")
    img_b = Image.open(io.BytesIO(png_b)).convert("RGBA")

    # Resize B to match A if needed
    if img_b.size != img_a.size:
        img_b = img_b.resize(img_a.size, Image.LANCZOS)

    alpha_a = np.array(img_a.split()[3], dtype=np.float32)
    alpha_b = np.array(img_b.split()[3], dtype=np.float32)

    # Min of both alphas = intersection
    combined = np.minimum(alpha_a, alpha_b).astype(np.uint8)

    # Use RGB from the image with better edges (A = RMBG typically)
    result = img_a.copy()
    result.putalpha(Image.fromarray(combined))

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


def _check_mask_quality_v2(png_bytes: bytes) -> bool:
    """Improved quality check: alpha ratio + region compactness + single dominant region.

    Returns False if:
    - Alpha ratio outside 8-80% (too much or too little removed)
    - >15% semi-transparent (dirty mask)
    - Largest component < 70% of total foreground (fragmented mask = background leaked)
    - Foreground bounding box covers >90% of image (model kept everything)
    """
    try:
        import cv2
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        alpha = np.array(img.split()[3])
        total = alpha.shape[0] * alpha.shape[1]

        opaque = int(np.sum(alpha > 128))
        ratio = opaque / total if total > 0 else 0
        if not (0.08 <= ratio <= 0.80):
            return False

        semi_transparent = int(np.sum((alpha > 30) & (alpha < 225)))
        if semi_transparent / total > 0.15:
            return False

        # Check region dominance: largest component should be most of the foreground
        binary = (alpha > 128).astype(np.uint8)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels > 1:
            areas = [stats[i, cv2.CC_STAT_AREA] for i in range(1, num_labels)]
            if areas:
                largest = max(areas)
                total_fg = sum(areas)
                if total_fg > 0 and largest / total_fg < 0.70:
                    return False  # fragmented — background leaked into multiple regions

        # Check that foreground bbox doesn't cover almost the entire image
        fg_coords = np.argwhere(binary > 0)
        if len(fg_coords) > 0:
            y_min, x_min = fg_coords.min(axis=0)
            y_max, x_max = fg_coords.max(axis=0)
            bbox_area = (y_max - y_min) * (x_max - x_min)
            if bbox_area / total > 0.92:
                return False  # foreground bbox covers almost entire image — model kept bg

        return True
    except Exception:
        return True


def _run_cloth_seg(image_bytes: bytes) -> bytes:
    """Run cloth-segmentation U2Net: clothing-specific bg removal.

    Trained on iMaterialist fashion dataset (45k images).
    4-class output: 0=background, 1=upper-body, 2=lower-body, 3=full-body.
    Much better than generic RMBG on textured backgrounds (couches, carpets).

    Preprocessing: normalize to [-1, 1] (mean=0.5, std=0.5).
    Input: 768×768 (training resolution).
    """
    import structlog
    _logger = structlog.get_logger()

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size

    # Pad to square then resize to 320×320 (ONNX export fixed size)
    side = max(orig_w, orig_h)
    padded = Image.new("RGB", (side, side), (128, 128, 128))
    padded.paste(img, ((side - orig_w) // 2, (side - orig_h) // 2))
    resized = padded.resize((320, 320), Image.BILINEAR)

    # Normalize: (pixel/255 - 0.5) / 0.5 = pixel/127.5 - 1.0
    arr = np.array(resized, dtype=np.float32) / 255.0
    arr = (arr - 0.5) / 0.5
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]  # (1, 3, 320, 320)

    sess = _get_cloth_seg_session()
    input_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {input_name: arr})

    # U2Net side outputs: 7 × [1, 1, 320, 320]. First output (d0) is the fused main mask.
    # Model trained on iMaterialist clothing → output already in [0, 1] range.
    # Do NOT apply sigmoid — values are already probabilities.
    mask = outputs[0].squeeze()  # (320, 320)
    mask = np.clip(mask, 0.0, 1.0)

    # Binarize: clothing > 0.5, floor/background < 0.5
    mask = np.where(mask > 0.5, 255, 0).astype(np.uint8)

    # Morphological cleanup
    from PIL import ImageFilter
    mask_pil = Image.fromarray(mask)
    mask_pil = mask_pil.filter(ImageFilter.MaxFilter(3))  # dilate: fill small holes
    mask_pil = mask_pil.filter(ImageFilter.MinFilter(3))  # erode: remove noise
    mask_pil = mask_pil.filter(ImageFilter.GaussianBlur(radius=1.5))  # smooth edges

    # Un-pad: resize mask to square then crop to original aspect ratio
    mask_square = mask_pil.resize((side, side), Image.BILINEAR)
    left = (side - orig_w) // 2
    top_pad = (side - orig_h) // 2
    mask_cropped = mask_square.crop((left, top_pad, left + orig_w, top_pad + orig_h))

    img_rgba = img.copy().convert("RGBA")
    img_rgba.putalpha(mask_cropped)

    buf = io.BytesIO()
    img_rgba.save(buf, format="PNG")
    _logger.info("rmbg.cloth_seg_done", orig_size=f"{orig_w}x{orig_h}")
    return buf.getvalue()


def _refine_mask_grabcut(image_bytes: bytes, mask_bytes: bytes, iterations: int = 3) -> bytes:
    """Refine a rough mask using GrabCut seeded by the initial mask.

    GrabCut learns local color models (GMM) for foreground vs background,
    then iteratively refines the boundary. This helps when cloth-seg knows
    WHERE the garment is but the edge is imprecise (e.g., pink on wood).

    Args:
        image_bytes: original RGB image (JPEG/PNG)
        mask_bytes: initial mask as RGBA PNG (from cloth-seg or RMBG)
        iterations: GrabCut iterations (more = better but slower)
    Returns:
        Refined RGBA PNG
    """
    try:
        import cv2
        orig = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        mask_img = Image.open(io.BytesIO(mask_bytes)).convert("RGBA")

        # Resize mask to match original if needed
        if mask_img.size != orig.size:
            mask_img = mask_img.resize(orig.size, Image.LANCZOS)

        alpha = np.array(mask_img.split()[3])
        arr = np.array(orig)

        # Build GrabCut mask from alpha:
        # 0=GC_BGD (sure bg), 1=GC_FGD (sure fg), 2=GC_PR_BGD, 3=GC_PR_FGD
        gc_mask = np.full(alpha.shape, cv2.GC_PR_BGD, dtype=np.uint8)
        gc_mask[alpha > 200] = cv2.GC_FGD      # confident foreground
        gc_mask[alpha > 100] = cv2.GC_PR_FGD    # probable foreground
        gc_mask[alpha < 30] = cv2.GC_BGD        # confident background

        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)

        cv2.grabCut(arr, gc_mask, None, bgd_model, fgd_model,
                    iterations, cv2.GC_INIT_WITH_MASK)

        # Extract refined mask
        refined = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD),
                          255, 0).astype(np.uint8)

        # Smooth edges
        refined = cv2.GaussianBlur(refined, (3, 3), 0)

        result = orig.copy().convert("RGBA")
        result.putalpha(Image.fromarray(refined))

        buf = io.BytesIO()
        result.save(buf, format="PNG")

        import structlog
        structlog.get_logger().info("rmbg.grabcut_refine_done")
        return buf.getvalue()
    except Exception as e:
        import structlog
        structlog.get_logger().warning("rmbg.grabcut_refine_failed", error=str(e))
        return mask_bytes  # return original mask on failure


def _auto_rotate_to_vertical(img: Image.Image) -> Image.Image:
    """Rotate garment to vertical orientation using contour analysis.

    Finds the minimum area bounding rectangle of the opaque region,
    then rotates so the long axis is vertical.

    cv2.minAreaRect returns angle in [-90, 0):
    - angle is rotation of the rect from HORIZONTAL axis
    - We need deviation from VERTICAL to straighten
    """
    try:
        import cv2
        alpha = img.split()[3]
        alpha_arr = np.array(alpha)

        # Threshold to binary for clean contours
        _, binary = cv2.threshold(alpha_arr, 30, 255, cv2.THRESH_BINARY)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return img

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < img.size[0] * img.size[1] * 0.05:
            return img  # contour too small, skip

        rect = cv2.minAreaRect(largest)
        rect_w, rect_h = rect[1]
        angle = rect[2]  # [-90, 0)

        # Calculate deviation from vertical
        if rect_w < rect_h:
            # Long side is roughly vertical, angle is tilt from vertical
            deviation = 90 + angle  # e.g., angle=-70 → deviation=20°
        else:
            # Long side is roughly horizontal, need 90° + correction
            deviation = angle  # e.g., angle=-20 → rotate -20° to go vertical

        # Only rotate if deviation is significant (>5°)
        # <5° = already straight enough
        if abs(deviation) < 5:
            return img

        # For large deviations (>80°) the garment is essentially horizontal
        # → rotate by exactly 90° (cleaner than fractional rotation)
        if abs(deviation) > 80:
            if deviation > 0:
                rotated = img.rotate(-90, expand=True, resample=Image.BICUBIC,
                                     fillcolor=(0, 0, 0, 0))
            else:
                rotated = img.rotate(90, expand=True, resample=Image.BICUBIC,
                                     fillcolor=(0, 0, 0, 0))
        else:
            rotated = img.rotate(-deviation, expand=True, resample=Image.BICUBIC,
                                 fillcolor=(0, 0, 0, 0))
        return rotated
    except Exception:
        return img


def _detect_upside_down(img: Image.Image) -> bool:
    """Detect if a garment is upside down by comparing width of top vs bottom third.

    Only flips when VERY confident: bottom must be 3x wider than top.
    Conservative threshold avoids flipping dresses (skirt wider than shoulders is normal).
    """
    try:
        alpha = img.split()[3]
        w, h = img.size
        if h < 60:
            return False
        third = h // 3
        top_data = list(alpha.crop((0, 0, w, third)).getdata())
        bot_data = list(alpha.crop((0, h - third, w, h)).getdata())
        top_opaque = sum(1 for a in top_data if a > 128)
        bot_opaque = sum(1 for a in bot_data if a > 128)
        # Very conservative: 3x difference needed (was 1.5x — flipped dresses)
        if top_opaque > 0 and bot_opaque > top_opaque * 3.0 and bot_opaque > len(bot_data) * 0.4:
            return True
    except Exception:
        pass
    return False


def pad_square_resize(png_bytes: bytes, size: int = THUMB_SIZE) -> bytes:
    """Auto-trim transparent edges, fix orientation, pad to square, resize."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    # Auto-trim: crop to non-transparent bounding box
    alpha = img.split()[3]
    bbox = alpha.getbbox()
    if bbox:
        # 5% padding
        w, h = img.size
        pad_x = int((bbox[2] - bbox[0]) * 0.05)
        pad_y = int((bbox[3] - bbox[1]) * 0.05)
        bbox = (
            max(0, bbox[0] - pad_x), max(0, bbox[1] - pad_y),
            min(w, bbox[2] + pad_x), min(h, bbox[3] + pad_y),
        )
        img = img.crop(bbox)

    # Auto-rotate to vertical (straighten angled garments)
    if img.mode == "RGBA":
        img = _auto_rotate_to_vertical(img)
        # Re-trim after rotation (rotation may add transparent corners)
        alpha = img.split()[3]
        bbox = alpha.getbbox()
        if bbox:
            w, h = img.size
            pad_x = int((bbox[2] - bbox[0]) * 0.05)
            pad_y = int((bbox[3] - bbox[1]) * 0.05)
            bbox = (
                max(0, bbox[0] - pad_x), max(0, bbox[1] - pad_y),
                min(w, bbox[2] + pad_x), min(h, bbox[3] + pad_y),
            )
            img = img.crop(bbox)

    # Detect and fix upside-down garments (pants with waistband at bottom)
    if _detect_upside_down(img):
        img = img.rotate(180, expand=False)

    # Pad to square
    w, h = img.size
    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - w) // 2, (side - h) // 2))

    # Resize to target
    square = square.resize((size, size), Image.LANCZOS)

    buf = io.BytesIO()
    square.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _check_rembg_quality(png_bytes: bytes) -> bool:
    """Check if bg removal produced a usable result.

    Returns False if:
    - >80% pixels opaque (removed too little — background still visible)
    - <10% pixels opaque (removed too much — garment lost)
    - >15% semi-transparent pixels (dirty mask — background bleeding through)
    """
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        alpha = img.split()[3]
        total = alpha.size[0] * alpha.size[1]
        alpha_data = list(alpha.getdata())
        opaque = sum(1 for a in alpha_data if a > 128)
        ratio = opaque / total if total > 0 else 0
        # Clothing on a photo typically occupies 15-75% of the frame
        if not (0.10 <= ratio <= 0.80):
            return False
        # Dirty mask check: too many semi-transparent pixels = noisy edges
        # Clean masks have mostly 0 (transparent) or 255 (opaque) alpha
        semi_transparent = sum(1 for a in alpha_data if 30 < a < 225)
        semi_ratio = semi_transparent / total if total > 0 else 0
        if semi_ratio > 0.15:
            return False
        return True
    except Exception:
        return True  # fallback — don't block


def sharpen_thumbnail(png_bytes: bytes, factor: float = 1.3) -> bytes:
    """Apply gentle sharpening to improve readability at small sizes."""
    from PIL import ImageEnhance
    img = Image.open(io.BytesIO(png_bytes))
    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(factor)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def boost_contrast(png_bytes: bytes, factor: float = 1.15) -> bytes:
    """Slightly boost contrast for wrinkled/matte fabrics."""
    from PIL import ImageEnhance
    img = Image.open(io.BytesIO(png_bytes))
    if img.mode == "RGBA":
        # Enhance RGB only, preserve alpha
        r, g, b, a = img.split()
        rgb = Image.merge("RGB", (r, g, b))
        enhancer = ImageEnhance.Contrast(rgb)
        rgb = enhancer.enhance(factor)
        r2, g2, b2 = rgb.split()
        img = Image.merge("RGBA", (r2, g2, b2, a))
    else:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(factor)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_collage_thumbnail(photo_bytes: bytes, needs_bg_removal: bool = True) -> bytes:
    """Full thumbnail pipeline for collage display.

    Pipeline: EXIF rotate → auto-brightness → [bg removal + quality check]
              → edge softening → contrast boost → auto-trim → pad square
              → resize 400×400 → sharpen

    Args:
        photo_bytes: raw image bytes (JPEG or PNG)
        needs_bg_removal: if True, run RMBG-1.4 (skip if already bg-removed RGBA)
    Returns:
        PNG bytes 400×400 RGBA ready for collage
    """
    # 1. EXIF rotate
    result = exif_rotate(photo_bytes)

    # 1b. Auto-rotate landscape photos to portrait (garments are taller than wide)
    img_orient = Image.open(io.BytesIO(result))
    if img_orient.width > img_orient.height * 1.3:
        img_orient = img_orient.rotate(90, expand=True)
        buf = io.BytesIO()
        fmt = "PNG" if img_orient.mode == "RGBA" else "JPEG"
        img_orient.save(buf, format=fmt, quality=90)
        result = buf.getvalue()

    # 2. Background removal (if needed)
    if needs_bg_removal:
        img_check = Image.open(io.BytesIO(result))
        if img_check.mode not in ("RGBA", "LA", "PA"):
            import structlog as _sl
            _log = _sl.get_logger()

            # Auto-brightness BEFORE bg removal (helps with dark photos)
            result = auto_brightness(result)
            # CLAHE preprocessing: boosts local contrast to separate garment from
            # textured backgrounds (couches, carpets, wood floors)
            enhanced = _apply_clahe(result)

            # Optimized fallback chain:
            # RMBG-1.4 + postprocess → cloth-segmentation → GrabCut → original
            rembg_result = None

            # Step 1: RMBG-1.4 (general salient object) + largest component filter
            try:
                rembg_result = _run_rmbg14(enhanced)
                rembg_result = _postprocess_mask(rembg_result)
            except Exception:
                pass
            if rembg_result and _check_mask_quality_v2(rembg_result):
                _log.info("rmbg.pipeline_ok", model="rmbg14")
                result = rembg_result
                rembg_result = "done"

            # Step 2: cloth-segmentation (clothing-specific, trained on fashion data)
            if rembg_result != "done":
                try:
                    rembg_result = _run_cloth_seg(enhanced)
                    rembg_result = _postprocess_mask(rembg_result)
                except Exception as e:
                    _log.warning("rmbg.cloth_seg_failed", error=str(e))
                    rembg_result = None
                if rembg_result and _check_mask_quality_v2(rembg_result):
                    _log.info("rmbg.pipeline_ok", model="cloth_seg")
                    result = rembg_result
                    rembg_result = "done"

            # Step 3: GrabCut (graph-cut, works on textured backgrounds)
            if rembg_result != "done":
                rembg_result = _run_grabcut(enhanced)
                if rembg_result and _check_mask_quality_v2(rembg_result):
                    _log.info("rmbg.pipeline_ok", model="grabcut")
                    result = rembg_result
                else:
                    _log.warning("rmbg.pipeline_all_failed")
            # else: keep brightness-corrected original (no bg removal)

    # 3. Edge softening (only if has alpha)
    img_check = Image.open(io.BytesIO(result))
    if img_check.mode == "RGBA":
        result = soften_edges(result, radius=1.5)
    else:
        result = auto_brightness(result)

    # 4. Contrast boost (helps wrinkled fabrics read better at small sizes)
    result = boost_contrast(result, factor=1.05)

    # 5. Auto-trim + pad to square + resize
    result = pad_square_resize(result, THUMB_SIZE)

    # 6. Sharpen (after resize — improves detail at 200px display size)
    result = sharpen_thumbnail(result, factor=1.3)

    return result


async def make_collage_thumbnail_safe(photo_bytes: bytes, needs_bg_removal: bool = True) -> bytes:
    """Async wrapper: limits concurrent RMBG to 1 to prevent OOM.
    5 users × 600MB RMBG peak = 3GB → OOM. Semaphore keeps peak ≤ ~800MB."""
    async with _rmbg_semaphore:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, make_collage_thumbnail, photo_bytes, needs_bg_removal
        )


MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_DIMENSION = 1024
PHASH_THRESHOLD = 5  # порог схожести хешей (0=identical, 64=max diff; 5 = same photo with JPEG artifacts)


def remove_exif(img: Image.Image) -> Image.Image:
    """Удаляет EXIF данные (GDPR)."""
    data = list(img.getdata())
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    return clean


def compute_phash(img: Image.Image) -> str:
    return str(imagehash.phash(img))


def is_duplicate(hash1: str, hash2: str) -> bool:
    h1 = imagehash.hex_to_hash(hash1)
    h2 = imagehash.hex_to_hash(hash2)
    return bool((h1 - h2) < PHASH_THRESHOLD)


def preprocess(
    image_bytes: bytes,
    existing_hashes: Optional[list[str]] = None,
) -> tuple[bytes, str]:
    """
    Обрабатывает изображение:
    - проверяет размер
    - resize + EXIF cleanup
    - вычисляет phash
    - проверяет дубли

    Возвращает (processed_bytes, phash).
    Raises ImageTooLargeError, DuplicateItemError.
    """
    if len(image_bytes) > MAX_SIZE_BYTES:
        raise ImageTooLargeError(
            f"Фото слишком большое: {len(image_bytes) // (1024*1024)}MB. Максимум 20MB."
        )

    img = Image.open(io.BytesIO(image_bytes))

    # Конвертируем в RGB если нужно
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Resize
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    # Phash до удаления EXIF (нет разницы, но до resize уже)
    phash = compute_phash(img)

    # Проверка дублей
    if existing_hashes:
        for existing in existing_hashes:
            if is_duplicate(phash, existing):
                raise DuplicateItemError(
                    "Такая вещь уже есть в гардеробе. Проверь список вещей."
                )

    # Удаляем EXIF
    img = remove_exif(img)

    # Конвертируем обратно в bytes
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), phash



async def remove_background(image_bytes: bytes, redis=None) -> bytes:
    """Remove background using optimized pipeline.

    Chain: CLAHE → RMBG-1.4 + postprocess → cloth-segmentation → GrabCut
           → remove.bg API → original.
    Возвращает PNG bytes с прозрачностью.
    """
    import structlog

    log = structlog.get_logger()

    # CLAHE preprocessing: boost garment/background contrast
    enhanced = _apply_clahe(image_bytes)

    # 1. RMBG-1.4 + largest component postprocessing
    result = None
    try:
        result = _run_rmbg14(enhanced)
        result = _postprocess_mask(result)
    except Exception as e:
        log.warning("remove_background.rmbg14_failed", error=str(e))
        result = None

    if result and _check_mask_quality_v2(result):
        if redis is not None:
            try:
                await redis.incr("rembg:local:rmbg14:ok")
            except Exception:
                pass
        return result
    log.info("remove_background.rmbg14_quality_fail")

    # 2. cloth-segmentation (clothing-specific U2Net)
    try:
        result = _run_cloth_seg(enhanced)
        result = _postprocess_mask(result)
    except Exception as e:
        log.warning("remove_background.cloth_seg_failed", error=str(e))
        result = None

    if result and _check_mask_quality_v2(result):
        if redis is not None:
            try:
                await redis.incr("rembg:local:cloth_seg:ok")
            except Exception:
                pass
        return result
    log.info("remove_background.cloth_seg_quality_fail")

    # 3. GrabCut (graph-cut, good on textured backgrounds)
    try:
        result = _run_grabcut(enhanced)
    except Exception as e:
        log.warning("remove_background.grabcut_failed", error=str(e))
        result = None

    if result and _check_mask_quality_v2(result):
        if redis is not None:
            try:
                await redis.incr("rembg:local:grabcut:ok")
            except Exception:
                pass
        return result
    log.info("remove_background.grabcut_quality_fail")

    # 4. Fallback: remove.bg API
    import httpx
    from config import settings

    if not settings.removebg_api_key:
        return image_bytes

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.remove.bg/v1.0/removebg",
                headers={"X-Api-Key": settings.removebg_api_key},
                data={"size": "auto"},
                files={"image_file": ("image.jpg", image_bytes, "image/jpeg")},
            )
            r.raise_for_status()
        if redis is not None:
            try:
                await redis.incr("removebg:credits:used")
            except Exception:
                pass
        return r.content
    except Exception as e:
        log.warning("remove_background.api_failed", error=str(e))
        if redis is not None:
            try:
                await redis.incr("removebg:credits:failed")
            except Exception:
                pass
        return image_bytes
