"""
Коллаж из вещей гардероба.
Grid 2×2 или 2×3, подписи под каждой вещью.
"""
import io
import math
from typing import Optional

import httpx
import structlog
from PIL import Image, ImageDraw, ImageFont

from config import settings

logger = structlog.get_logger()

CELL_W = 300
CELL_H = 300
LABEL_H = 28
PADDING = 4
COLS = 2
BG_COLOR = (248, 248, 248)
LABEL_BG = (230, 230, 230)
TEXT_COLOR = (50, 50, 50)


async def _download_photo(
    client: httpx.AsyncClient,
    file_id: str,
    photo_url: Optional[str] = None,
) -> Optional[bytes]:
    """Скачивает фото: CDN URL (http*), R2 boto3 (wardrobe/...), Telegram (fallback)."""
    if photo_url:
        if photo_url.startswith("http"):
            # Новый формат: публичный CDN URL
            try:
                r = await client.get(photo_url, timeout=10.0)
                r.raise_for_status()
                return r.content
            except Exception as e:
                logger.warning("image_builder.cdn_failed", url=photo_url[:60], error=str(e))
                # fallback на Telegram
        else:
            # Старый формат: r2_key (wardrobe/...)
            try:
                from services.storage.r2_storage import get_r2_storage
                r2 = get_r2_storage()
                return await r2.get_photo(photo_url)
            except Exception as e:
                logger.warning("image_builder.r2_failed", key=photo_url, error=str(e))
                # fallback на Telegram

    try:
        r = await client.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
            params={"file_id": file_id},
            timeout=10.0,
        )
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        r2_resp = await client.get(
            f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
            timeout=15.0,
        )
        r2_resp.raise_for_status()
        return r2_resp.content
    except Exception as e:
        logger.warning("image_builder.tg_download_failed", file_id=file_id[:20], error=str(e))
        return None


def _fit_image(img: Image.Image, w: int, h: int) -> Image.Image:
    """Вписывает изображение в ячейку на кремовом фоне (поддержка RGBA/PNG)."""
    # Создаём фон цвета BG_COLOR
    cell = Image.new("RGB", (w, h), BG_COLOR)

    # Масштабируем с сохранением пропорций (fit, не crop)
    img_ratio = img.width / img.height
    cell_ratio = w / h
    if img_ratio > cell_ratio:
        new_w = w
        new_h = int(w / img_ratio)
    else:
        new_h = h
        new_w = int(h * img_ratio)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Центрируем на фоне
    offset_x = (w - new_w) // 2
    offset_y = (h - new_h) // 2

    if resized.mode == "RGBA":
        cell.paste(resized, (offset_x, offset_y), mask=resized.split()[3])
    else:
        cell.paste(resized.convert("RGB"), (offset_x, offset_y))

    return cell


def _build_grid(cells: list[tuple[Image.Image, str]]) -> bytes:
    """Собирает коллаж из ячеек [(image, label)]."""
    n = len(cells)
    cols = min(COLS, n)
    rows = math.ceil(n / cols)

    total_w = cols * (CELL_W + PADDING) - PADDING
    total_h = rows * (CELL_H + LABEL_H + PADDING) - PADDING

    canvas = Image.new("RGB", (total_w, total_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    for idx, (img, label) in enumerate(cells):
        col = idx % cols
        row = idx // cols
        x = col * (CELL_W + PADDING)
        y = row * (CELL_H + LABEL_H + PADDING)

        canvas.paste(img, (x, y))

        # Подпись
        lbl_y = y + CELL_H
        draw.rectangle([x, lbl_y, x + CELL_W, lbl_y + LABEL_H], fill=LABEL_BG)
        # Обрезаем длинный текст
        max_chars = 28
        text = label[:max_chars] + "…" if len(label) > max_chars else label
        draw.text((x + 4, lbl_y + 6), text, fill=TEXT_COLOR, font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


async def build_collage(
    photo_ids: list[str],
    labels: Optional[list[str]] = None,
    photo_urls: Optional[list[Optional[str]]] = None,
) -> Optional[bytes]:
    """
    Скачивает фото (из R2 по photo_url если есть, иначе Telegram file_id),
    собирает коллаж grid 2×N. Возвращает JPEG bytes или None.
    """
    if not photo_ids:
        return None

    if labels is None:
        labels = [""] * len(photo_ids)
    if photo_urls is None:
        photo_urls = [None] * len(photo_ids)

    cells: list[tuple[Image.Image, str]] = []
    async with httpx.AsyncClient() as client:
        for file_id, label, purl in zip(photo_ids, labels, photo_urls):
            data = await _download_photo(client, file_id, purl)
            if not data:
                continue
            try:
                img = Image.open(io.BytesIO(data))
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
                img = _fit_image(img, CELL_W, CELL_H)
                cells.append((img, label))
            except Exception as e:
                logger.warning("image_builder.decode_failed", error=str(e))

    if not cells:
        return None

    try:
        return _build_grid(cells)
    except Exception as e:
        logger.error("image_builder.build_failed", error=str(e))
        return None
