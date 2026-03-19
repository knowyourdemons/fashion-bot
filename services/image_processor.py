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

# ── Singleton ONNX session for background removal ──────────────────
_SILUETA_PATH = "/root/.u2net/silueta.onnx"
_ort_session: Optional[ort.InferenceSession] = None
_ort_lock = threading.Lock()


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


async def remove_background(image_bytes: bytes, redis=None) -> bytes:
    """
    Удаляет фон: local ONNX (silueta) → remove.bg API fallback → оригинал.
    Возвращает PNG bytes с прозрачностью.
    """
    import structlog

    log = structlog.get_logger()

    # 1. Try local ONNX inference
    try:
        result = _run_silueta(image_bytes)
        if redis is not None:
            try:
                await redis.incr("rembg:local:ok")
            except Exception:
                pass
        return result
    except Exception as e:
        log.warning("remove_background.local_failed", error=str(e))

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
