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
COLS          = 2
THUMB_SIZE    = 300       # размер ячейки (квадрат)
CELL_W        = THUMB_SIZE
CELL_H        = THUMB_SIZE
CELL_PAD      = 18
LABEL_H       = 38
GRID_GAP      = 20
OUTER_PAD     = 28
RADIUS        = 18
SHADOW_OFFSET = 5
SHADOW_BLUR   = 9
MAX_LONG_SIDE = 1200

# ── Цвета ────────────────────────────────────────────────────────────────────
BG_COLOR       = (250, 246, 255)   # #FAF6FF — мягкий лавандовый
CARD_BG        = (255, 255, 255)   # белая карточка
SHADOW_FILL    = (180, 170, 195)   # тень в тон фона
LABEL_BG       = (245, 240, 252)   # фон подписи
LABEL_TEXT     = (139, 123, 139)   # #8B7B8B — приглушённый лилово-серый
LABEL_DIVIDER  = (230, 222, 240)   # линия-разделитель
PLACEHOLDER_BG = (240, 238, 240)   # #F0EEF0 — фон плейсхолдера
SILHOUETTE_CLR = (200, 192, 204)   # #C8C0CC — сиреневато-серый силуэт


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

    if not file_id:
        return None
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
        logger.warning("image_builder.tg_download_failed",
                       file_id=(file_id[:20] if file_id else ""), error=str(e))
        return None


def _make_thumb(photo_bytes: bytes) -> Image.Image:
    """Открывает байты изображения в PIL Image."""
    img = Image.open(io.BytesIO(photo_bytes))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    return img


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
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle(
        [(x + SHADOW_OFFSET, y + SHADOW_OFFSET),
         (x + w + SHADOW_OFFSET - 1, y + h + SHADOW_OFFSET - 1)],
        radius=RADIUS,
        fill=(*SHADOW_FILL, 90),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    canvas.alpha_composite(shadow)


def _draw_card(canvas: Image.Image, img: Image.Image,
               x: int, y: int, card_w: int, card_h: int, label: str,
               font: ImageFont.FreeTypeFont) -> None:
    """Рисует одну карточку с изображением и подписью."""
    img_area_h = card_h - LABEL_H

    card = Image.new("RGBA", (card_w, card_h), CARD_BG + (255,))

    inner_w = card_w - CELL_PAD * 2
    inner_h = img_area_h - CELL_PAD * 2
    fitted = _fit_item(img, inner_w, inner_h)

    ix = CELL_PAD + (inner_w - fitted.width) // 2
    iy = CELL_PAD + (inner_h - fitted.height) // 2
    card.paste(fitted, (ix, iy), fitted.split()[3])

    label_area = Image.new("RGBA", (card_w, LABEL_H), LABEL_BG + (255,))
    ld = ImageDraw.Draw(label_area)
    ld.line([(0, 0), (card_w, 0)], fill=LABEL_DIVIDER + (255,), width=1)
    text = label[:24] + "…" if len(label) > 24 else label
    try:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(text) * 8
    tx = max(4, (card_w - tw) // 2)
    ld.text((tx, 9), text, fill=LABEL_TEXT + (255,), font=font)
    card.paste(label_area, (0, img_area_h))

    mask = _rounded_mask(card_w, card_h, RADIUS)
    card.putalpha(mask)

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


# ── Плейсхолдеры (детские силуэты, только PIL) ───────────────────────────────

def _draw_silhouette(draw: ImageDraw.ImageDraw, slot: str,
                     size: int = 300, color: tuple = SILHOUETTE_CLR) -> None:
    """Рисует детский силуэт одежды на size×size холсте."""
    cx = size // 2

    if slot == "outerwear":
        draw.rounded_rectangle([cx-55, 90, cx+55, 210], radius=15, fill=color)
        draw.rounded_rectangle([cx-90, 95, cx-50, 175], radius=10, fill=color)
        draw.rounded_rectangle([cx+50, 95, cx+90, 175], radius=10, fill=color)
        draw.ellipse([cx-35, 55, cx+35, 100], fill=color)
        draw.rectangle([cx-2, 95, cx+2, 205], fill=(230, 225, 232))

    elif slot == "top":
        draw.rounded_rectangle([cx-50, 100, cx+50, 210], radius=12, fill=color)
        draw.rounded_rectangle([cx-80, 100, cx-45, 145], radius=8, fill=color)
        draw.rounded_rectangle([cx+45, 100, cx+80, 145], radius=8, fill=color)
        draw.ellipse([cx-22, 93, cx+22, 115], fill=PLACEHOLDER_BG)

    elif slot == "bottom":
        draw.rounded_rectangle([cx-50, 80, cx+50, 115], radius=8, fill=color)
        draw.rounded_rectangle([cx-48, 110, cx-8, 220], radius=10, fill=color)
        draw.rounded_rectangle([cx+8, 110, cx+48, 220], radius=10, fill=color)

    elif slot == "one_piece":
        draw.rounded_rectangle([cx-45, 80, cx+45, 155], radius=10, fill=color)
        draw.polygon([(cx-45, 150), (cx+45, 150), (cx+75, 230), (cx-75, 230)], fill=color)
        draw.rounded_rectangle([cx-35, 75, cx-15, 95], radius=5, fill=color)
        draw.rounded_rectangle([cx+15, 75, cx+35, 95], radius=5, fill=color)

    elif slot == "footwear":
        draw.ellipse([cx-55, 175, cx+55, 215], fill=color)
        draw.rounded_rectangle([cx-45, 130, cx+40, 185], radius=20, fill=color)
        draw.ellipse([cx+15, 160, cx+60, 195], fill=color)

    elif slot in ("accessory", "hat"):
        # Основа: большой полукруг (верхняя половина)
        draw.ellipse([cx-55, 95, cx+55, 195], fill=color)
        # Отворот: прямоугольник снизу
        draw.rounded_rectangle([cx-60, 170, cx+60, 198], radius=8, fill=color)
        # Помпон: маленький круг сверху
        draw.ellipse([cx-16, 72, cx+16, 105], fill=color)

    elif slot in ("tights", "base_layer"):
        draw.polygon([(cx-40, 70), (cx+40, 70), (cx+35, 120), (cx-35, 120)], fill=color)
        draw.rounded_rectangle([cx-38, 115, cx-5, 230], radius=8, fill=color)
        draw.rounded_rectangle([cx+5, 115, cx+38, 230], radius=8, fill=color)
        draw.ellipse([cx-42, 220, cx-2, 240], fill=color)
        draw.ellipse([cx+2, 220, cx+42, 240], fill=color)

    else:
        pad = size // 6
        draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=20, fill=color)


_SLOT_LABELS_RU = {
    "outerwear": "добавь куртку",
    "top":       "добавь верх",
    "bottom":    "добавь низ",
    "one_piece": "добавь платье",
    "footwear":  "добавь обувь",
    "accessory": "добавь шапку",
    "hat":       "добавь шапку",
    "tights":    "добавь колготки",
    "base_layer":"добавь колготки",
}


def _make_placeholder(slot: str, label: str, size: int = THUMB_SIZE) -> Image.Image:
    """Ячейка-плейсхолдер: детский силуэт на сером фоне."""
    img = Image.new("RGBA", (size, size), PLACEHOLDER_BG + (255,))
    draw = ImageDraw.Draw(img)
    _draw_silhouette(draw, slot, size)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    except Exception:
        font = ImageFont.load_default()

    text = _SLOT_LABELS_RU.get(slot, f"добавь {label}")
    try:
        bbox_t = draw.textbbox((0, 0), text, font=font)
        text_w = bbox_t[2] - bbox_t[0]
    except Exception:
        text_w = len(text) * 8
    draw.text(
        ((size - text_w) // 2, size - 28),
        text, fill=(155, 143, 160), font=font,
    )
    return img


# ── Grid ─────────────────────────────────────────────────────────────────────

def _build_grid(images: list, labels: list) -> Image.Image:
    """Собирает сетку карточек. Возвращает PIL Image (RGB)."""
    n = len(images)
    if n == 0:
        return Image.new("RGB", (100, 100), BG_COLOR)

    cols = min(COLS, n)
    rows = math.ceil(n / cols)

    card_w = CELL_W + CELL_PAD * 2
    card_h = CELL_H + CELL_PAD * 2 + LABEL_H

    canvas_w = cols * card_w + (cols - 1) * GRID_GAP + OUTER_PAD * 2
    canvas_h = rows * card_h + (rows - 1) * GRID_GAP + OUTER_PAD * 2

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
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    gap = int(GRID_GAP * scale)
    outer = int(OUTER_PAD * scale)

    for idx, (img, label) in enumerate(zip(images, labels)):
        col = idx % cols
        row = idx // cols
        x = outer + col * (card_w + gap)
        y = outer + row * (card_h + gap)
        _draw_shadow(canvas, x, y, card_w, card_h)
        _draw_card(canvas, img, x, y, card_w, card_h, label, font)

    final = Image.new("RGB", canvas.size, BG_COLOR)
    final.paste(canvas.convert("RGB"), mask=canvas.split()[3])
    return final


# ── Public API ───────────────────────────────────────────────────────────────

async def build_collage(
    outfit_slots: Optional[list] = None,
    photo_ids: Optional[list] = None,
    labels: Optional[list] = None,
    photo_urls: Optional[list] = None,
) -> Optional[bytes]:
    """
    Собирает коллаж.
    Новый режим: outfit_slots — список слотов с has_item/photo_url/slot.
    Старый режим: photo_ids + labels + photo_urls (backward compat).
    Возвращает JPEG bytes или None.
    """
    thumbs: list = []
    final_labels: list = []

    if outfit_slots:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for slot_data in outfit_slots:
                slot_key = slot_data.get("slot", "top")
                lbl = slot_data.get("label") or ""

                if slot_data.get("has_item"):
                    photo_bytes = await _download_photo(
                        client,
                        slot_data.get("photo_id") or "",
                        slot_data.get("photo_url"),
                    )
                    if photo_bytes:
                        try:
                            thumb = _make_thumb(photo_bytes)
                            thumbs.append(thumb)
                            final_labels.append(lbl)
                            continue
                        except Exception as e:
                            logger.warning("image_builder.decode_failed", error=str(e))
                    # Не удалось скачать → плейсхолдер
                    ph = _make_placeholder(slot_key, lbl)
                    thumbs.append(ph)
                    final_labels.append(f"добавь {lbl}")
                else:
                    ph = _make_placeholder(slot_key, lbl)
                    thumbs.append(ph)
                    final_labels.append(f"добавь {lbl}")
    else:
        # ── Старый режим: photo_ids ────────────────────────────────────────
        if not photo_ids:
            return None
        if labels is None:
            labels = [""] * len(photo_ids)
        if photo_urls is None:
            photo_urls = [None] * len(photo_ids)

        async with httpx.AsyncClient(timeout=15.0) as client:
            for file_id, label, purl in zip(photo_ids, labels, photo_urls):
                data = await _download_photo(client, file_id, purl)
                if not data:
                    continue
                try:
                    img = Image.open(io.BytesIO(data))
                    thumbs.append(img)
                    final_labels.append(label or "")
                except Exception as e:
                    logger.warning("image_builder.decode_failed", error=str(e))

    if not thumbs:
        return None

    try:
        grid = _build_grid(thumbs, final_labels)
        buf = io.BytesIO()
        grid.save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.error("image_builder.build_failed", error=str(e))
        return None
