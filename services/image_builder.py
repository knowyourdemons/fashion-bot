"""
Коллаж из вещей гардероба.
3-зонный layout: outerwear / top+bottom / обувь+аксессуары.
PNG-иконки из assets/silhouettes/, фоны из assets/backgrounds/.
"""
import io
import math
import os
from typing import Optional

import httpx
import structlog
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pilmoji import Pilmoji

from config import settings

logger = structlog.get_logger()

# ── Пути к ресурсам ───────────────────────────────────────────────────────────
_ASSETS_DIR       = os.path.join(os.path.dirname(__file__), "..", "assets")
_SILHOUETTES_DIR  = os.path.join(_ASSETS_DIR, "silhouettes")
_BACKGROUNDS_DIR  = os.path.join(_ASSETS_DIR, "backgrounds")

# ── Размеры (старый grid — backward compat) ───────────────────────────────────
COLS          = 2
THUMB_SIZE    = 300
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
HEADER_H      = 60
FOOTER_H      = 35

# ── Размеры нового layout ─────────────────────────────────────────────────────
CANVAS_W      = 800     # фиксированная ширина
LAYOUT_PAD    = 32      # >= SHADOW_BLUR*3 = 27
LAYOUT_GAP    = 16
ZONE1_CARD_H  = 320     # outerwear
ZONE2_CARD_H  = 280     # top / bottom / one_piece
ZONE3_CARD_H  = 220     # обувь / аксессуары

# ── Цвета ────────────────────────────────────────────────────────────────────
BG_COLOR        = (250, 246, 255)
CARD_BG         = (255, 255, 255)
SHADOW_FILL     = (180, 170, 195)
LABEL_BG        = (245, 240, 252)
LABEL_TEXT      = (139, 123, 139)
LABEL_DIVIDER   = (230, 222, 240)
PLACEHOLDER_BG  = (240, 238, 240)
SILHOUETTE_CLR  = (200, 192, 204)
FOOTER_TEXT_CLR = (175, 165, 190)

# ── Темы ─────────────────────────────────────────────────────────────────────
_THEMES = {
    "girl":  {"top": (250, 246, 255), "bot": (255, 240, 248)},
    "boy":   {"top": (240, 248, 245), "bot": (235, 245, 252)},
    "adult": {"top": (255, 250, 245), "bot": (250, 245, 240)},
}
_BG_MAP = {
    "girl": "bg_girl.png", "boy": "bg_boy.png",
    "adult": "bg_adult.png", "winter": "bg_winter.png",
}

# ── Подписи ───────────────────────────────────────────────────────────────────
_SLOT_EMOJI = {
    "outerwear": "🧥", "top": "👚", "bottom": "👖",
    "one_piece": "👗", "footwear": "👟",
    "hat": "🧢", "scarf": "🧣", "gloves": "🧤",
    "tights": "🧦", "socks": "🧦", "base_layer": "🧦",
    "underwear": "👙", "accessory": "🎀",
    "thermal_top": "🧤", "thermal_bottom": "🧤",
}

_SLOT_NAMES_SHORT = {
    "outerwear": "Куртка", "top": "Верх", "bottom": "Низ",
    "removable_layer": "Кардиган", "one_piece": "Платье",
    "footwear": "Обувь", "hat": "Шапка", "scarf": "Шарф",
    "gloves": "Перчатки", "tights": "Колготки", "socks": "Носки",
}

_PLACEHOLDER_LABELS: dict = {
    "outerwear": "Куртка",
    "top":       "Верх",
    "bottom":    "Низ",
    "removable_layer": "Кардиган",
    "one_piece": {"girl": "Платье", "boy": "Комбинезон", "default": "Платье"},
    "footwear":  "Обувь",
    "hat":       "Шапка",
    "scarf":     "Шарф",
    "gloves":    "Перчатки",
    "tights":    "Колготки",
    "socks":     "Носки",
}


def _get_placeholder_label(slot: str, gender: str = "girl") -> str:
    label = _PLACEHOLDER_LABELS.get(slot, "")
    if isinstance(label, dict):
        return label.get(gender, label.get("default", ""))
    return label


def format_collage_label(slot: str, item_type: str, item_color: str = "") -> str:
    """Подпись: 'Леггинсы пыльно-роз.' — тип + полный цвет, без эмодзи, max 28 символов."""
    parts_t = (item_type or "").split()
    short_type = parts_t[0].capitalize() if parts_t else ""
    color = (item_color or "").strip()

    label = f"{short_type} {color}".strip() if color else short_type

    if not label:
        return _SLOT_NAMES_SHORT.get(slot, "Вещь")

    if len(label) > 28:
        cut = label[:27]
        last_break = max(cut.rfind(" "), cut.rfind("-"))
        if last_break > len(short_type):
            label = cut[:last_break + 1].rstrip() + "."
        else:
            label = cut.rstrip() + "."

    return label


# ── Кэш теней ────────────────────────────────────────────────────────────────
_shadow_cache: dict = {}


def _get_shadow_template(w: int, h: int) -> Image.Image:
    key = (w, h)
    if key not in _shadow_cache:
        pad = SHADOW_BLUR * 3
        shadow = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(shadow)
        draw.rounded_rectangle(
            [(pad + SHADOW_OFFSET, pad + SHADOW_OFFSET),
             (pad + w + SHADOW_OFFSET - 1, pad + h + SHADOW_OFFSET - 1)],
            radius=RADIUS, fill=(*SHADOW_FILL, 90),
        )
        _shadow_cache[key] = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    return _shadow_cache[key]


# ── Загрузка фото ────────────────────────────────────────────────────────────

async def _download_photo(
    client: httpx.AsyncClient,
    file_id: str,
    photo_url: Optional[str] = None,
) -> Optional[bytes]:
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
            params={"file_id": file_id}, timeout=10.0,
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
    img = Image.open(io.BytesIO(photo_bytes))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    return img


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=255)
    return mask


def _fit_item(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    ratio = min(max_w / img.width, max_h / img.height)
    new_w = max(1, int(img.width * ratio))
    new_h = max(1, int(img.height * ratio))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _draw_shadow(canvas: Image.Image, x: int, y: int, w: int, h: int) -> None:
    tmpl = _get_shadow_template(w, h)
    pad = SHADOW_BLUR * 3
    ox = max(0, x - pad)
    oy = max(0, y - pad)
    canvas.alpha_composite(tmpl, (ox, oy))


def _draw_card(canvas: Image.Image, img: Image.Image,
               x: int, y: int, card_w: int, card_h: int, label: str,
               font: ImageFont.FreeTypeFont) -> None:
    """Рисует карточку с реальным фото + подписью (для photo_ids backward compat)."""
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


def _make_gradient_bg(w: int, h: int, theme: str = "girl") -> Image.Image:
    """PIL-градиент (fallback когда PNG-фона нет)."""
    colors = _THEMES.get(theme, _THEMES["girl"])
    top_c, bot_c = colors["top"], colors["bot"]
    base = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(base)
    for yy in range(h):
        t = yy / max(h - 1, 1)
        r = int(top_c[0] + (bot_c[0] - top_c[0]) * t)
        g = int(top_c[1] + (bot_c[1] - top_c[1]) * t)
        b = int(top_c[2] + (bot_c[2] - top_c[2]) * t)
        draw.line([(0, yy), (w, yy)], fill=(r, g, b))
    return base.convert("RGBA")


# ── PNG ресурсы ───────────────────────────────────────────────────────────────

def _load_silhouette(slot: str, gender: str = "girl", adult: bool = False) -> Optional[Image.Image]:
    """Загружает PNG-иконку плейсхолдера. Fallback: None → старый PIL-силуэт."""
    candidates = []
    if adult:
        candidates.append(f"{slot}_adult.png")
    candidates.append(f"{slot}_{gender}.png")
    candidates.append(f"{slot}.png")
    for name in candidates:
        path = os.path.join(_SILHOUETTES_DIR, name)
        if os.path.exists(path):
            try:
                return Image.open(path).convert("RGBA")
            except Exception:
                pass
    return None


def _load_background(w: int, h: int, theme: str = "girl") -> Image.Image:
    """Загружает PNG-фон и растягивает под canvas. Fallback: PIL-градиент."""
    bg_file = _BG_MAP.get(theme, "bg_girl.png")
    bg_path = os.path.join(_BACKGROUNDS_DIR, bg_file)
    if os.path.exists(bg_path):
        try:
            bg = Image.open(bg_path).convert("RGBA")
            return bg.resize((w, h), Image.LANCZOS)
        except Exception:
            pass
    return _make_gradient_bg(w, h, theme)


# ── Силуэты PIL (fallback) ────────────────────────────────────────────────────

def _draw_silhouette(draw: ImageDraw.ImageDraw, slot: str,
                     size: int = 300, color: tuple = SILHOUETTE_CLR,
                     gender: str = "girl") -> None:
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
        if gender == "boy":
            draw.rounded_rectangle([cx-45, 80, cx+45, 140], radius=10, fill=color)
            draw.rounded_rectangle([cx-43, 135, cx-8, 220], radius=10, fill=color)
            draw.rounded_rectangle([cx+8, 135, cx+43, 220], radius=10, fill=color)
            draw.rectangle([cx-30, 70, cx-20, 85], fill=color)
            draw.rectangle([cx+20, 70, cx+30, 85], fill=color)
        else:
            draw.rounded_rectangle([cx-45, 80, cx+45, 155], radius=10, fill=color)
            draw.polygon([(cx-45, 150), (cx+45, 150), (cx+75, 230), (cx-75, 230)], fill=color)
            draw.rounded_rectangle([cx-35, 75, cx-15, 95], radius=5, fill=color)
            draw.rounded_rectangle([cx+15, 75, cx+35, 95], radius=5, fill=color)
    elif slot == "footwear":
        draw.ellipse([cx-55, 175, cx+55, 215], fill=color)
        draw.rounded_rectangle([cx-45, 130, cx+40, 185], radius=20, fill=color)
        draw.ellipse([cx+15, 160, cx+60, 195], fill=color)
    elif slot in ("accessory", "hat"):
        draw.ellipse([cx-55, 95, cx+55, 195], fill=color)
        draw.rounded_rectangle([cx-60, 170, cx+60, 198], radius=8, fill=color)
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


def _draw_adult_silhouette(draw: ImageDraw.ImageDraw, slot: str,
                           size: int = 300, color: tuple = SILHOUETTE_CLR) -> None:
    cx = size // 2
    if slot == "outerwear":
        draw.rounded_rectangle([cx-60, 60, cx+60, 240], radius=15, fill=color)
        draw.rounded_rectangle([cx-95, 65, cx-55, 170], radius=10, fill=color)
        draw.rounded_rectangle([cx+55, 65, cx+95, 170], radius=10, fill=color)
        draw.polygon([(cx-20, 60), (cx+20, 60), (cx+10, 95), (cx-10, 95)], fill=(230, 225, 232))
    elif slot == "top":
        draw.rounded_rectangle([cx-50, 80, cx+50, 210], radius=12, fill=color)
        draw.rounded_rectangle([cx-85, 80, cx-45, 185], radius=8, fill=color)
        draw.rounded_rectangle([cx+45, 80, cx+85, 185], radius=8, fill=color)
        draw.polygon([(cx-20, 78), (cx+20, 78), (cx, 110)], fill=(240, 238, 240))
    elif slot == "bottom":
        draw.rounded_rectangle([cx-50, 70, cx+50, 100], radius=8, fill=color)
        draw.rounded_rectangle([cx-48, 95, cx-5, 240], radius=10, fill=color)
        draw.rounded_rectangle([cx+5, 95, cx+48, 240], radius=10, fill=color)
    elif slot == "one_piece":
        draw.rounded_rectangle([cx-48, 60, cx+48, 145], radius=10, fill=color)
        draw.polygon([(cx-48, 140), (cx+48, 140), (cx+80, 250), (cx-80, 250)], fill=color)
        draw.rectangle([cx-30, 55, cx-15, 70], fill=color)
        draw.rectangle([cx+15, 55, cx+30, 70], fill=color)
    elif slot == "footwear":
        draw.ellipse([cx-60, 200, cx+60, 230], fill=color)
        draw.rounded_rectangle([cx-55, 155, cx+45, 210], radius=18, fill=color)
        draw.rounded_rectangle([cx+25, 205, cx+45, 240], radius=5, fill=color)
        draw.ellipse([cx+20, 175, cx+65, 215], fill=color)
    elif slot in ("accessory", "hat"):
        draw.ellipse([cx-70, 165, cx+70, 195], fill=color)
        draw.rounded_rectangle([cx-45, 100, cx+45, 175], radius=12, fill=color)
    elif slot in ("tights", "base_layer"):
        draw.polygon([(cx-35, 60), (cx+35, 60), (cx+30, 110), (cx-30, 110)], fill=color)
        draw.rounded_rectangle([cx-33, 105, cx-3, 245], radius=8, fill=color)
        draw.rounded_rectangle([cx+3, 105, cx+33, 245], radius=8, fill=color)
        draw.ellipse([cx-37, 235, cx+1, 255], fill=color)
        draw.ellipse([cx+1, 235, cx+37, 255], fill=color)
    else:
        pad = size // 6
        draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=20, fill=color)


# ── Плейсхолдер (PNG иконка + fallback PIL) ───────────────────────────────────

def _make_placeholder(slot: str, label: str, card_w: int = THUMB_SIZE,
                      card_h: int = THUMB_SIZE,
                      adult: bool = False, gender: str = "girl") -> Image.Image:
    """Плейсхолдер: PNG-иконка на сером фоне с подписью (без 'добавь')."""
    img = Image.new("RGBA", (card_w, card_h), PLACEHOLDER_BG + (255,))

    icon = _load_silhouette(slot, gender, adult)
    label_zone = 36   # резервируем снизу под подпись
    if icon:
        max_icon_w = int(card_w * 0.58)
        max_icon_h = int((card_h - label_zone) * 0.72)
        icon = _fit_item(icon, max_icon_w, max_icon_h)
        ix = (card_w - icon.width) // 2
        iy = (card_h - label_zone - icon.height) // 2
        img.paste(icon, (ix, iy), icon)
    else:
        draw = ImageDraw.Draw(img)
        sil_size = min(card_w, card_h - label_zone)
        if adult:
            _draw_adult_silhouette(draw, slot, sil_size)
        else:
            _draw_silhouette(draw, slot, sil_size, gender=gender)

    if label:
        try:
            font_sz = max(12, int(card_h * 0.055))
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_sz)
        except Exception:
            font = ImageFont.load_default()
        draw = ImageDraw.Draw(img)
        try:
            bbox = font.getbbox(label)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(label) * 8
        tx = max(4, (card_w - tw) // 2)
        draw.text((tx, card_h - label_zone + 8), label, fill=(155, 143, 160), font=font)

    return img


# ── Новый layout (3 зоны) ─────────────────────────────────────────────────────

def _draw_slot_card(canvas: Image.Image, slot_data: dict,
                    x: int, y: int, card_w: int, card_h: int,
                    font: ImageFont.FreeTypeFont) -> None:
    """Рисует карточку слота на canvas: фото или PNG-плейсхолдер."""
    slot_key = slot_data.get("slot", "top")
    is_adult  = slot_data.get("adult", False)
    gender    = slot_data.get("gender", "girl")

    _draw_shadow(canvas, x, y, card_w, card_h)

    if slot_data.get("has_item") and slot_data.get("_thumb"):
        item_type  = slot_data.get("item_type", "")
        item_color = slot_data.get("item_color", "")
        label = format_collage_label(slot_key, item_type, item_color)
        _draw_card(canvas, slot_data["_thumb"], x, y, card_w, card_h, label, font)
    else:
        # Уважаем temp-based label из outfit_builder; fallback — иконочное название
        ph_label = slot_data.get("label") or _get_placeholder_label(slot_key, gender)
        ph = _make_placeholder(slot_key, ph_label, card_w, card_h,
                               adult=is_adult, gender=gender)
        mask = _rounded_mask(card_w, card_h, RADIUS)
        ph.putalpha(mask)
        canvas.alpha_composite(ph, (x, y))


def _build_layered_layout(
    slots: list,
    theme: str = "girl",
    header_text: str = "",
    footer_text: str = "Касси -- твой личный стилист",
) -> Image.Image:
    """3-зонный layout коллажа.
    Зона 1: outerwear (full-width если фото, half-width если placeholder).
    Зона 2: top + bottom (2 col) или one_piece (full-width).
    Зона 3: footwear + аксессуары (2 col, мельче). Max 4 элемента.
    """
    # Разбивка по зонам
    zone1 = [s for s in slots if s["slot"] == "outerwear"]
    zone2 = [s for s in slots if s["slot"] in ("top", "removable_layer", "bottom", "one_piece")]
    zone3 = [s for s in slots if s["slot"] in ("footwear", "hat", "scarf", "gloves", "tights", "socks")]

    # Зона 2 крупнее когда нет зоны 1 (тепло/жара)
    zone2_card_h = int(ZONE2_CARD_H * 1.3) if not zone1 else ZONE2_CARD_H

    # Высота canvas
    h = LAYOUT_PAD
    if header_text:
        h += HEADER_H + LAYOUT_GAP
    if zone1:
        h += ZONE1_CARD_H + LAYOUT_GAP
    if zone2:
        h += zone2_card_h + LAYOUT_GAP
    if zone3:
        rows3 = math.ceil(min(len(zone3), 4) / 2)
        h += rows3 * (ZONE3_CARD_H + LAYOUT_GAP)
    if footer_text:
        h += FOOTER_H + LAYOUT_GAP
    h += LAYOUT_PAD

    canvas = _load_background(CANVAS_W, h, theme)

    # Шрифты
    try:
        font    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        hfont   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
        ffont   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except Exception:
        font = hfont = ffont = ImageFont.load_default()

    y_cur = LAYOUT_PAD

    # ── Header (plain PIL — emoji убраны из header_text) ─────────────────────
    if header_text:
        hd = ImageDraw.Draw(canvas)
        try:
            bbox = hfont.getbbox(header_text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(header_text) * 12, 26
        tx = max(LAYOUT_PAD, (CANVAS_W - tw) // 2)
        ty = y_cur + max(2, (HEADER_H - th) // 2)
        hd.text((tx, ty), header_text, fill=LABEL_TEXT + (255,), font=hfont)
        y_cur += HEADER_H + LAYOUT_GAP

    # ── Зона 1: outerwear ────────────────────────────────────────────────────
    for slot_data in zone1:
        if slot_data.get("has_item"):
            card_w = CANVAS_W - LAYOUT_PAD * 2
        else:
            card_w = (CANVAS_W - LAYOUT_PAD * 2 - LAYOUT_GAP) // 2
        _draw_slot_card(canvas, slot_data, LAYOUT_PAD, y_cur, card_w, ZONE1_CARD_H, font)
        y_cur += ZONE1_CARD_H + LAYOUT_GAP

    # ── Зона 2: top + bottom / one_piece ─────────────────────────────────────
    one_piece_slots = [s for s in zone2 if s["slot"] == "one_piece"]
    top_slots       = [s for s in zone2 if s["slot"] in ("top", "removable_layer")]
    bot_slots       = [s for s in zone2 if s["slot"] == "bottom"]

    if zone2:
        if one_piece_slots:
            card_w = CANVAS_W - LAYOUT_PAD * 2
            _draw_slot_card(canvas, one_piece_slots[0], LAYOUT_PAD, y_cur, card_w, zone2_card_h, font)
        else:
            card_w = (CANVAS_W - LAYOUT_PAD * 2 - LAYOUT_GAP) // 2
            if top_slots:
                _draw_slot_card(canvas, top_slots[0], LAYOUT_PAD, y_cur, card_w, zone2_card_h, font)
            if bot_slots:
                _draw_slot_card(canvas, bot_slots[0],
                                LAYOUT_PAD + card_w + LAYOUT_GAP, y_cur,
                                card_w, zone2_card_h, font)
        y_cur += zone2_card_h + LAYOUT_GAP

    # ── Зона 3: обувь + аксессуары ───────────────────────────────────────────
    card_w3 = (CANVAS_W - LAYOUT_PAD * 2 - LAYOUT_GAP) // 2
    zone3_shown = zone3[:4]
    for i, slot_data in enumerate(zone3_shown):
        col = i % 2
        row = i // 2
        x = LAYOUT_PAD + col * (card_w3 + LAYOUT_GAP)
        yy = y_cur + row * (ZONE3_CARD_H + LAYOUT_GAP)
        _draw_slot_card(canvas, slot_data, x, yy, card_w3, ZONE3_CARD_H, font)
    if zone3_shown:
        rows3 = math.ceil(len(zone3_shown) / 2)
        y_cur += rows3 * (ZONE3_CARD_H + LAYOUT_GAP)

    # ── Footer ────────────────────────────────────────────────────────────────
    if footer_text:
        fd = ImageDraw.Draw(canvas)
        try:
            bbox = ffont.getbbox(footer_text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(footer_text) * 9, 18
        tx = max(LAYOUT_PAD, (CANVAS_W - tw) // 2)
        ty = y_cur + max(2, (FOOTER_H - th) // 2)
        fd.text((tx, ty), footer_text, fill=FOOTER_TEXT_CLR + (255,), font=ffont)

    bg_color = _THEMES.get(theme, _THEMES["girl"])["top"]
    final = Image.new("RGB", canvas.size, bg_color)
    final.paste(canvas.convert("RGB"), mask=canvas.split()[3])
    return final


# ── Старый grid (backward compat для photo_ids режима) ────────────────────────

def _build_grid(images: list, labels: list, theme: str = "girl",
                header_text: str = "", footer_text: str = "") -> Image.Image:
    """Grid 2×N (старый режим для photo_ids)."""
    n = len(images)
    if n == 0:
        return Image.new("RGB", (100, 100), BG_COLOR)

    cols = min(COLS, n)
    rows = math.ceil(n / cols)

    card_w = CELL_W + CELL_PAD * 2
    card_h = CELL_H + CELL_PAD * 2 + LABEL_H

    canvas_w = cols * card_w + (cols - 1) * GRID_GAP + OUTER_PAD * 2
    canvas_h = rows * card_h + (rows - 1) * GRID_GAP + OUTER_PAD * 2
    if header_text:
        canvas_h += HEADER_H
    if footer_text:
        canvas_h += FOOTER_H

    scale = 1.0
    long_side = max(canvas_w, canvas_h)
    if long_side > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / long_side
        canvas_w = int(canvas_w * scale)
        canvas_h = int(canvas_h * scale)
        card_w   = int(card_w * scale)
        card_h   = int(card_h * scale)

    header_px = int(HEADER_H * scale) if header_text else 0
    footer_px  = int(FOOTER_H * scale) if footer_text else 0

    canvas = _make_gradient_bg(canvas_w, canvas_h, theme)

    try:
        font_size = max(11, int(15 * scale))
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    gap   = int(GRID_GAP * scale)
    outer = int(OUTER_PAD * scale)

    if header_text:
        try:
            hfont_size = max(14, int(36 * scale))
            hfont = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", hfont_size)
        except Exception:
            hfont = ImageFont.load_default()
        try:
            bbox = hfont.getbbox(header_text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw = len(header_text) * 10
            th = hfont_size
        tx = max(4, (canvas_w - tw) // 2)
        ty = max(2, (header_px - th) // 2)
        canvas_rgb = canvas.convert("RGB")
        with Pilmoji(canvas_rgb) as pmj:
            pmj.text((tx, ty), header_text, fill=LABEL_TEXT, font=hfont)
        canvas = canvas_rgb.convert("RGBA")

    for idx, (img, label) in enumerate(zip(images, labels)):
        col = idx % cols
        row = idx // cols
        x = outer + col * (card_w + gap)
        y = outer + header_px + row * (card_h + gap)
        _draw_shadow(canvas, x, y, card_w, card_h)
        _draw_card(canvas, img, x, y, card_w, card_h, label, font)

    if footer_text:
        try:
            ffont_size = max(10, int(22 * scale))
            ffont = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", ffont_size)
        except Exception:
            ffont = ImageFont.load_default()
        fd = ImageDraw.Draw(canvas)
        try:
            bbox = ffont.getbbox(footer_text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw = len(footer_text) * 8
            th = ffont_size
        tx = max(4, (canvas_w - tw) // 2)
        grid_bottom = outer + header_px + rows * card_h + (rows - 1) * gap
        ty = grid_bottom + max(2, (footer_px - th) // 2)
        fd.text((tx, ty), footer_text, fill=FOOTER_TEXT_CLR + (255,), font=ffont)

    bg_color = _THEMES.get(theme, _THEMES["girl"])["top"]
    final = Image.new("RGB", canvas.size, bg_color)
    final.paste(canvas.convert("RGB"), mask=canvas.split()[3])
    return final


# ── Public API ───────────────────────────────────────────────────────────────

async def build_collage(
    outfit_slots: Optional[list] = None,
    photo_ids: Optional[list] = None,
    labels: Optional[list] = None,
    photo_urls: Optional[list] = None,
    theme: str = "girl",
    header_text: str = "",
    footer_text: str = "Касси · fashioncastle.app",
) -> Optional[bytes]:
    """
    Собирает коллаж.
    Новый режим (outfit_slots): 3-зонный layout с PNG-иконками.
    Старый режим (photo_ids): grid 2×N (backward compat).
    """
    try:
        if outfit_slots:
            # Скачать фото для реальных вещей
            async with httpx.AsyncClient(timeout=15.0) as client:
                for slot_data in outfit_slots:
                    if slot_data.get("has_item"):
                        photo_bytes = await _download_photo(
                            client,
                            slot_data.get("photo_id") or "",
                            slot_data.get("photo_url"),
                        )
                        if photo_bytes:
                            try:
                                slot_data["_thumb"] = _make_thumb(photo_bytes)
                            except Exception as e:
                                logger.warning("image_builder.decode_failed", error=str(e))
                                slot_data["has_item"] = False
                        else:
                            slot_data["has_item"] = False

            result = _build_layered_layout(outfit_slots, theme, header_text, footer_text)
            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=88, optimize=True)
            return buf.getvalue()

        elif photo_ids:
            # Старый режим
            if labels is None:
                labels = [""] * len(photo_ids)
            if photo_urls is None:
                photo_urls = [None] * len(photo_ids)

            thumbs: list = []
            final_labels: list = []
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

            grid = _build_grid(thumbs, final_labels, theme=theme,
                               header_text=header_text, footer_text=footer_text)
            buf = io.BytesIO()
            grid.save(buf, format="JPEG", quality=88, optimize=True)
            return buf.getvalue()

        return None

    except Exception as e:
        logger.error("image_builder.build_failed", error=str(e))
        return None
