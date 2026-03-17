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


async def _download_tg_photo(client: httpx.AsyncClient, file_id: str) -> Optional[bytes]:
    """Скачивает фото из Telegram по file_id."""
    try:
        r = await client.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
            params={"file_id": file_id},
            timeout=10.0,
        )
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        r2 = await client.get(
            f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
            timeout=15.0,
        )
        r2.raise_for_status()
        return r2.content
    except Exception as e:
        logger.warning("image_builder.download_failed", file_id=file_id[:20], error=str(e))
        return None


def _fit_image(img: Image.Image, w: int, h: int) -> Image.Image:
    """Вписывает изображение в ячейку с обрезкой по центру."""
    img_ratio = img.width / img.height
    cell_ratio = w / h
    if img_ratio > cell_ratio:
        new_h = h
        new_w = int(h * img_ratio)
    else:
        new_w = w
        new_h = int(w / img_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


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
) -> Optional[bytes]:
    """
    Скачивает фото из Telegram по file_id, собирает коллаж grid 2×N.
    Возвращает JPEG bytes или None если не удалось собрать ни одной ячейки.
    """
    if not photo_ids:
        return None

    if labels is None:
        labels = [""] * len(photo_ids)

    cells: list[tuple[Image.Image, str]] = []
    async with httpx.AsyncClient() as client:
        for file_id, label in zip(photo_ids, labels):
            data = await _download_tg_photo(client, file_id)
            if not data:
                continue
            try:
                img = Image.open(io.BytesIO(data)).convert("RGB")
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
