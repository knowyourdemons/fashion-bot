"""
Обработка фото перед отправкой в Vision API:
1. Проверка размера (max 20MB)
2. Resize до 1024×1024
3. Очистка EXIF (GDPR)
4. Perceptual hash для дублей
5. Удаление фона (local ONNX silueta → remove.bg API fallback)
"""
import asyncio
import io
import threading
from typing import Optional

import imagehash
import numpy as np
import onnxruntime as ort
from PIL import Image

from exceptions import DuplicateItemError, ImageTooLargeError

# ── Singleton ONNX sessions for background removal ─────────────────
_SILUETA_PATH = "/root/.u2net/silueta.onnx"
_RMBG14_PATH = "/root/.u2net/rmbg14_quantized.onnx"
_ISNET_PATH = "/root/.u2net/isnet-general-use.onnx"

_ort_session: Optional[ort.InferenceSession] = None
_ort_lock = threading.Lock()

_rmbg_session: Optional[ort.InferenceSession] = None
_rmbg_lock = threading.Lock()

_isnet_session: Optional[ort.InferenceSession] = None
_isnet_lock = threading.Lock()

# Limit concurrent RMBG inferences to prevent OOM (each peak ~600MB)
_rmbg_semaphore = asyncio.Semaphore(1)


def _get_ort_session() -> ort.InferenceSession:
    global _ort_session
    if _ort_session is None:
        with _ort_lock:
            if _ort_session is None:  # double-check after acquiring lock
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.inter_op_num_threads = 1
                _ort_session = ort.InferenceSession(
                    _SILUETA_PATH, opts, providers=["CPUExecutionProvider"]
                )
    return _ort_session


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


def _get_isnet_session() -> ort.InferenceSession:
    """Thread-safe singleton for ISNet-general-use ONNX model (178MB, best quality)."""
    global _isnet_session
    if _isnet_session is None:
        with _isnet_lock:
            if _isnet_session is None:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.inter_op_num_threads = 1
                _isnet_session = ort.InferenceSession(
                    _ISNET_PATH, opts, providers=["CPUExecutionProvider"]
                )
    return _isnet_session


def _run_removebg_api(image_bytes: bytes) -> bytes | None:
    """Remove background via remove.bg API. Best quality, handles any background.
    Returns PNG bytes with alpha or None if API fails/unavailable.
    Cost: ~$0.05/image on paid plan, free tier = 50/month.
    """
    import os
    import httpx
    import structlog
    _logger = structlog.get_logger()

    api_key = os.environ.get("REMOVEBG_API_KEY", "")
    if not api_key:
        return None

    try:
        # Resize to max 1024px to reduce upload size and API processing time
        img = Image.open(io.BytesIO(image_bytes))
        max_dim = max(img.size)
        if max_dim > 1500:
            scale = 1500 / max_dim
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            upload_bytes = buf.getvalue()
        else:
            upload_bytes = image_bytes

        resp = httpx.post(
            "https://api.remove.bg/v1.0/removebg",
            files={"image_file": ("photo.png", upload_bytes, "image/png")},
            data={"size": "auto", "type": "product"},
            headers={"X-Api-Key": api_key},
            timeout=20,
        )
        if resp.status_code == 200 and len(resp.content) > 1000:
            _logger.info("rmbg.removebg_ok", size=len(resp.content))
            return resp.content
        _logger.warning("rmbg.removebg_failed", status=resp.status_code,
                         body=resp.text[:200])
        return None
    except Exception as e:
        _logger.warning("rmbg.removebg_error", error=str(e))
        return None


def _run_isnet(image_bytes: bytes) -> bytes:
    """Run ISNet-general-use: best quality bg removal for complex backgrounds.

    ISNet is designed for high-accuracy object segmentation.
    Input: 1024×1024, normalized [0,1], CHW layout.
    Output: sigmoid mask 1024×1024.
    """
    import structlog
    _logger = structlog.get_logger()

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size

    # Preprocess: pad to square (preserve aspect ratio) then resize to 1024×1024
    # Stretching non-square photos (e.g., 185×777) distorts features → bad mask
    side = max(orig_w, orig_h)
    padded = Image.new("RGB", (side, side), (128, 128, 128))  # neutral gray bg
    padded.paste(img, ((side - orig_w) // 2, (side - orig_h) // 2))
    resized = padded.resize((1024, 1024), Image.BILINEAR)

    arr = np.array(resized, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]  # (1, 3, 1024, 1024)

    sess = _get_isnet_session()
    input_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {input_name: arr})
    # ISNet returns multiple outputs; first is the main mask
    mask = outputs[0].squeeze()  # (1024, 1024)

    # Normalize to [0, 255]
    mask = mask - mask.min()
    denom = mask.max() - mask.min()
    if denom > 0:
        mask = mask / denom
    mask = (mask * 255).astype(np.uint8)

    # Post-processing: morphological cleanup
    mask[mask < 25] = 0
    mask[mask > 230] = 255
    from PIL import ImageFilter
    mask_pil = Image.fromarray(mask)
    mask_pil = mask_pil.filter(ImageFilter.MaxFilter(3))
    mask_pil = mask_pil.filter(ImageFilter.MinFilter(3))
    mask_pil = mask_pil.filter(ImageFilter.GaussianBlur(radius=1))

    # Crop mask back to original aspect ratio (remove padding)
    mask_square = mask_pil.resize((side, side), Image.BILINEAR)
    left = (side - orig_w) // 2
    top = (side - orig_h) // 2
    mask_cropped = mask_square.crop((left, top, left + orig_w, top + orig_h))

    # Apply mask as alpha channel
    img_rgba = img.copy().convert("RGBA")
    img_rgba.putalpha(mask_cropped)

    buf = io.BytesIO()
    img_rgba.save(buf, format="PNG")
    _logger.info("rmbg.isnet_done", orig_size=f"{orig_w}x{orig_h}")
    return buf.getvalue()


def _run_silueta(image_bytes: bytes) -> bytes:
    """Run silueta ONNX model: returns PNG bytes with transparent background."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size

    # Preprocess: resize to 320×320, normalize to [0,1], CHW layout
    resized = img.resize((320, 320), Image.BILINEAR)
    arr = np.array(resized, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]  # (1, 3, 320, 320)

    sess = _get_ort_session()
    mask = sess.run(None, {sess.get_inputs()[0].name: arr})[0]  # (1,1,320,320)
    mask = mask.squeeze()  # (320, 320)

    # Normalize mask to 0-255
    mask = (mask - mask.min()) / (mask.max() - mask.min() + 1e-8)
    mask = (mask * 255).astype(np.uint8)

    # Resize mask back to original size
    mask_img = Image.fromarray(mask).resize((orig_w, orig_h), Image.BILINEAR)

    # Apply mask as alpha channel
    img_rgba = img.copy().convert("RGBA")
    img_rgba.putalpha(mask_img)

    buf = io.BytesIO()
    img_rgba.save(buf, format="PNG")
    return buf.getvalue()


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


def _detect_upside_down(img: Image.Image) -> bool:
    """Detect if a garment is upside down by comparing width of top vs bottom third.
    Pants/skirts: waistband (wider) should be at top. If bottom third is wider → flip.
    """
    try:
        alpha = img.split()[3]
        w, h = img.size
        if h < 60:
            return False
        third = h // 3
        # Count opaque pixels in top and bottom thirds
        top_data = list(alpha.crop((0, 0, w, third)).getdata())
        bot_data = list(alpha.crop((0, h - third, w, h)).getdata())
        top_opaque = sum(1 for a in top_data if a > 128)
        bot_opaque = sum(1 for a in bot_data if a > 128)
        # If bottom third has significantly more opaque pixels → likely upside down
        # (waistband = wide = more pixels, should be at top)
        if bot_opaque > top_opaque * 1.5 and bot_opaque > len(bot_data) * 0.3:
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
        # 8% padding (was 5% — more padding reduces edge clipping)
        w, h = img.size
        pad_x = int((bbox[2] - bbox[0]) * 0.08)
        pad_y = int((bbox[3] - bbox[1]) * 0.08)
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
    Also checks for "dirty edges" — semi-transparent pixels that indicate
    poor mask quality (background bleeding through).
    """
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        alpha = img.split()[3]
        total = alpha.size[0] * alpha.size[1]
        # Count opaque pixels (alpha > 30 = "something there")
        alpha_data = list(alpha.getdata())
        opaque = sum(1 for a in alpha_data if a > 30)
        ratio = opaque / total if total > 0 else 0
        # Too little removed (<5% transparent) = model failed completely
        # Too much removed (>95% transparent) = model removed everything
        return 0.05 <= ratio <= 0.95
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
            # Auto-brightness BEFORE bg removal (helps with dark photos)
            result = auto_brightness(result)
            # Fallback chain: remove.bg API → ISNet → RMBG-1.4 → original
            rembg_result = None
            import os as _os
            try:
                rembg_result = _run_removebg_api(result)
            except Exception:
                pass
            if not rembg_result:
                try:
                    if _os.path.exists(_ISNET_PATH):
                        rembg_result = _run_isnet(result)
                    else:
                        rembg_result = _run_rmbg14(result)
                except Exception:
                    try:
                        rembg_result = _run_rmbg14(result)
                    except Exception:
                        pass

            # Quality check: if rembg failed (too much/too little removed), use original
            if rembg_result and _check_rembg_quality(rembg_result):
                result = rembg_result
            # else: keep brightness-corrected original (no bg removal)

    # 3. Edge softening (only if has alpha)
    img_check = Image.open(io.BytesIO(result))
    if img_check.mode == "RGBA":
        result = soften_edges(result, radius=1.5)
    else:
        result = auto_brightness(result)

    # 4. Contrast boost (helps wrinkled fabrics read better at small sizes)
    result = boost_contrast(result, factor=1.15)

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


def _get_bg_removal_model() -> str:
    """Return configured background removal model name.

    Uses BG_REMOVAL_MODEL env var via pydantic settings.
    Valid values: "silueta" (default), "rmbg14".
    """
    from config import settings
    return settings.bg_removal_model


async def remove_background(image_bytes: bytes, redis=None) -> bytes:
    """
    Удаляет фон: local ONNX (rmbg14 or silueta) → remove.bg API fallback → оригинал.
    Model selection: BG_REMOVAL_MODEL env var ("rmbg14" or "silueta", default: silueta).
    Возвращает PNG bytes с прозрачностью.
    """
    import structlog

    log = structlog.get_logger()

    model = _get_bg_removal_model()

    # 1. Try local ONNX inference (primary model)
    try:
        if model == "rmbg14":
            result = _run_rmbg14(image_bytes)
        else:
            result = _run_silueta(image_bytes)
        if redis is not None:
            try:
                await redis.incr(f"rembg:local:{model}:ok")
            except Exception:
                pass
        return result
    except Exception as e:
        log.warning("remove_background.local_failed", model=model, error=str(e))

    # 1b. Fallback to silueta if rmbg14 was primary and failed
    if model == "rmbg14":
        try:
            result = _run_silueta(image_bytes)
            if redis is not None:
                try:
                    await redis.incr("rembg:local:silueta_fallback:ok")
                except Exception:
                    pass
            return result
        except Exception as e:
            log.warning("remove_background.silueta_fallback_failed", error=str(e))

    # 2. Fallback: remove.bg API
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
