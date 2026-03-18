"""
Обработка фото перед отправкой в Vision API:
1. Проверка размера (max 20MB)
2. Resize до 1024×1024
3. Очистка EXIF (GDPR)
4. Perceptual hash для дублей
"""
import io
from typing import Optional

import imagehash
from PIL import Image

from exceptions import DuplicateItemError, ImageTooLargeError

MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_DIMENSION = 1024
PHASH_THRESHOLD = 10  # порог схожести хешей


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
    Удаляет фон через remove.bg API. Возвращает PNG bytes с прозрачностью.
    При ошибке или незаданном ключе — возвращает оригинал (fallback).
    redis — опциональный Redis клиент для мониторинга кредитов.
    """
    import httpx
    import structlog
    from config import settings

    log = structlog.get_logger()

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
        log.warning("remove_background.failed", error=str(e))
        if redis is not None:
            try:
                await redis.incr("removebg:credits:failed")
            except Exception:
                pass
        return image_bytes
