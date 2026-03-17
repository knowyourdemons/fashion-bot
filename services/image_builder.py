"""
Коллаж из вещей гардероба.
Пастельный фон, карточки с закруглёнными углами, тени, подписи.
"""
import io
import math
from typing import Optional

import httpx
import structlog
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import settings

logger = structlog.get_logger()

# ── Размеры ──────────────────────────────────────────────────────────────────
COLS = 2
CELL_W = 300        # ширина карточки
CELL_H = 300        # высота изображения в карточке
CELL_PAD = 18       # внутренний отступ
LABEL_H = 38        # высота подписи
GRID_GAP = 20       # отступ между карточками
OUTER_PAD = 28      # внешний отступ коллажа
RADIUS = 18         # радиус скругления углов
SHADOW_OFFSET = 5   # смещение тени
SHADOW_BLUR = 9     # размытие тени
MAX_LONG_SIDE = 1200

# ── Цвета ────────────────────────────────────────────────────────────────────
BG_COLOR      = (250, 246, 255)   # #FAF6FF — мягкий лавандовый
CARD_BG       = (255, 255, 255)   # белая карточка
SHADOW_FILL   = (180, 170, 195)   # тень в тон фона
LABEL_BG      = (245, 240, 252)   # фон подписи
LABEL_TEXT    = (139, 123, 139)   # #8B7B8B — приглушённый лилово-серый
LABEL_DIVIDER = (230, 222, 240)   # линия-разделитель


# ── Загрузка фото ────────────────────────────────────────────────────────────

async def _download_photo(
    client: httpx.AsyncClient,
    file_id: str,
    photo_url: Optional[str] = None,
) -> Optional[bytes]:
    """Скачивает фото: CDN URL (http*), R2 boto3 (wardrobe/...), Telegram (fallback)."""
    if photo_url:
        if photo_url.startswith("http"):
            try:
                r = await client.get(photo_url, timeout=10.0)
                r.raise_for_status()
                return r.content
            except Exception as e:
                logger.warning("image_builder.cdn_failed", url=photo_url[:60], error=str(e))
        else:
            try:
                from services.storage.r2_storage import get_r2_storage
                r2 = get_r2_storage()
                return await r2.get_photo(photo_url)
            except Exception as e:
                logger.warning("image_builder.r2_failed", key=photo_url, error=str(e))

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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    """RGBA маска со скруглёнными углами."""
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=255)
    return mask


def _fit_item(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Вписывает изображение в area, сохраняя пропорции. Возвращает RGBA."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    ratio = min(max_w / img.width, max_h / img.height)
    new_w = max(1, int(img.width * ratio))
    new_h = max(1, int(img.height * ratio))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _draw_shadow(canvas: Image.Image, x: int, y: int, w: int, h: int) -> None:
    """Рисует мягкую тень под карточкой."""
    # shadow_layer того же размера что canvas
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle(
        [(x + SHADOW_OFFSET, y + SHADOW_OFFSET),
         (x + w + SHADOW_OFFSET - 1, y + h + SHADOW_OFFSET - 1)],
        radius=RADIUS,
        fill=(*SHADOW_FILL, 90),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    # Compose shadow onto canvas (canvas уже RGBA)
    canvas.alpha_composite(shadow)


def _draw_card(canvas: Image.Image, img: Image.Image,
               x: int, y: int, card_w: int, card_h: int, label: str,
               font: ImageFont.FreeTypeFont) -> None:
    """Рисует одну карточку с изображением и подписью."""
    img_area_h = card_h - LABEL_H

    # 1. Белый фон карточки (RGBA)
    card = Image.new("RGBA", (card_w, card_h), CARD_BG + (255,))

    # 2. Вставляем вещь по центру img_area с отступом
    inner_w = card_w - CELL_PAD * 2
    inner_h = img_area_h - CELL_PAD * 2
    fitted = _fit_item(img, inner_w, inner_h)

    ix = CELL_PAD + (inner_w - fitted.width) // 2
    iy = CELL_PAD + (inner_h - fitted.height) // 2
    card.paste(fitted, (ix, iy), fitted.split()[3])

    # 3. Блок подписи
    label_area = Image.new("RGBA", (card_w, LABEL_H), LABEL_BG + (255,))
    ld = ImageDraw.Draw(label_area)
    # Тонкая линия сверху
    ld.line([(0, 0), (card_w, 0)], fill=LABEL_DIVIDER + (255,), width=1)
    # Текст по центру
    text = label[:24] + "…" if len(label) > 24 else label
    try:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(text) * 8
    tx = max(4, (card_w - tw) // 2)
    ld.text((tx, 9), text, fill=LABEL_TEXT + (255,), font=font)
    card.paste(label_area, (0, img_area_h))

    # 4. Применяем маску скруглённых углов
    mask = _rounded_mask(card_w, card_h, RADIUS)
    card.putalpha(mask)

    # 5. Вставляем на холст
    canvas.alpha_composite(card, (x, y))


def _make_gradient_bg(w: int, h: int) -> Image.Image:
    """Мягкий вертикальный градиент: #FAF6FF → #FFF0F8."""
    top = (250, 246, 255)
    bot = (255, 240, 248)
    base = Image.new("RGB", (w, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        ImageDraw.Draw(base).line([(0, y), (w, y)], fill=(r, g, b))
    return base.convert("RGBA")


def _build_grid(cells: list[tuple[Image.Image, str]]) -> bytes:
    n = len(cells)
    cols = min(COLS, n)
    rows = math.ceil(n / cols)

    card_w = CELL_W + CELL_PAD * 2
    card_h = CELL_H + CELL_PAD * 2 + LABEL_H

    canvas_w = cols * card_w + (cols - 1) * GRID_GAP + OUTER_PAD * 2
    canvas_h = rows * card_h + (rows - 1) * GRID_GAP + OUTER_PAD * 2

    # Масштабируем если слишком большой
    scale = 1.0
    long_side = max(canvas_w, canvas_h)
    if long_side > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / long_side
        canvas_w = int(canvas_w * scale)
        canvas_h = int(canvas_h * scale)
        card_w = int(card_w * scale)
        card_h = int(card_h * scale)

    canvas = _make_gradient_bg(canvas_w, canvas_h)

    try:
        font_size = max(11, int(15 * scale))
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    gap = int(GRID_GAP * scale)
    outer = int(OUTER_PAD * scale)

    for idx, (img, label) in enumerate(cells):
        col = idx % cols
        row = idx // cols
        x = outer + col * (card_w + gap)
        y = outer + row * (card_h + gap)

        _draw_shadow(canvas, x, y, card_w, card_h)
        _draw_card(canvas, img, x, y, card_w, card_h, label, font)

    # Конвертируем в RGB + JPEG
    final = Image.new("RGB", canvas.size, BG_COLOR)
    final.paste(canvas.convert("RGB"), mask=canvas.split()[3])

    buf = io.BytesIO()
    final.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def build_collage(
    photo_ids: list[str],
    labels: Optional[list[str]] = None,
    photo_urls: Optional[list[Optional[str]]] = None,
) -> Optional[bytes]:
    """
    Скачивает фото (CDN/R2/Telegram), собирает коллаж.
    Возвращает JPEG bytes или None.
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
                cells.append((img, label or ""))
            except Exception as e:
                logger.warning("image_builder.decode_failed", error=str(e))

    if not cells:
        return None

    try:
        return _build_grid(cells)
    except Exception as e:
        logger.error("image_builder.build_failed", error=str(e))
        return None
