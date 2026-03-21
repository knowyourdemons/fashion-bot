"""
Обработка фото перед отправкой в Vision API:
1. Проверка размера (max 20MB)
2. Resize до 1024×1024
3. Очистка EXIF (GDPR)
4. Perceptual hash для дублей
5. Удаление фона (local ONNX silueta → remove.bg API fallback)
"""
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

_ort_session: Optional[ort.InferenceSession] = None
_ort_lock = threading.Lock()

_rmbg_session: Optional[ort.InferenceSession] = None
_rmbg_lock = threading.Lock()


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
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size

    # Preprocess: resize to 1024×1024, normalize to [0,1], CHW layout
    resized = img.resize((1024, 1024), Image.BILINEAR)
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

    # Resize mask back to original size
    mask_img = Image.fromarray(mask).resize((orig_w, orig_h), Image.BILINEAR)

    # Apply mask as alpha channel
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


def pad_square_resize(png_bytes: bytes, size: int = THUMB_SIZE) -> bytes:
    """Auto-trim transparent edges, pad to square, resize to size×size."""
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


def make_collage_thumbnail(photo_bytes: bytes, needs_bg_removal: bool = True) -> bytes:
    """Full thumbnail pipeline for collage display.

    Pipeline: EXIF rotate → auto-brightness → [bg removal] → edge softening
              → auto-trim → pad square → resize 400×400

    Args:
        photo_bytes: raw image bytes (JPEG or PNG)
        needs_bg_removal: if True, run RMBG-1.4 (skip if already bg-removed RGBA)
    Returns:
        PNG bytes 400×400 RGBA ready for collage
    """
    # 1. EXIF rotate
    result = exif_rotate(photo_bytes)

    # 2. Background removal (if needed)
    if needs_bg_removal:
        img_check = Image.open(io.BytesIO(result))
        if img_check.mode not in ("RGBA", "LA", "PA"):
            # Auto-brightness BEFORE bg removal (helps RMBG with dark photos)
            result = auto_brightness(result)
            model = _get_bg_removal_model()
            try:
                if model == "rmbg14":
                    result = _run_rmbg14(result)
                else:
                    result = _run_silueta(result)
            except Exception:
                try:
                    result = _run_silueta(result)
                except Exception:
                    pass  # keep original if all fail

    # 3. Edge softening (only if has alpha)
    img_check = Image.open(io.BytesIO(result))
    if img_check.mode == "RGBA":
        result = soften_edges(result, radius=1.5)
    else:
        # No alpha — apply brightness anyway
        result = auto_brightness(result)

    # 4. Auto-trim + pad to square + resize
    result = pad_square_resize(result, THUMB_SIZE)

    return result


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


def to_base64(image_bytes: bytes) -> str:
    import base64
    return base64.standard_b64encode(image_bytes).decode()


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
