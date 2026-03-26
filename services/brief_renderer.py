"""
Рендеринг карточек через Playwright + Jinja2 HTML шаблоны.

Central module: data → Jinja2 template → HTML → POST to Playwright → PNG.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import httpx
import structlog
from jinja2 import Environment, FileSystemLoader

logger = structlog.get_logger()

# ── Jinja2 env ────────────────────────────────────────────────────────────────

TEMPLATE_DIR = Path(__file__).parent.parent / "renderer" / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
)

# ── Renderer config ──────────────────────────────────────────────────────────

RENDERER_URL = "http://renderer:3100/render"
RENDERER_TIMEOUT = 15


# ── Color themes ──────────────────────────────────────────────────────────────

THEMES = {
    "mom": {
        "css_class": "mom",
        "bg_start": "#F5EDE8",
        "bg_end": "#F0E8E4",
        "text": "#5B3A4A",
        "muted": "#B09888",
        "accent": "#D080A0",
    },
    "woman": {
        "css_class": "woman",
        "bg_start": "#E8EDF5",
        "bg_end": "#E4E8F0",
        "text": "#3A4A5B",
        "muted": "#8898A8",
        "accent": "#7090C0",
    },
}


# ── Color mapping ─────────────────────────────────────────────────────────────

COLOR_BG: dict[str, str] = {
    # Stems to match all gender forms (розовый/розовая/розовое)
    "розов": "bg-pink",
    "красн": "bg-red",
    "алы": "bg-red",
    "бордо": "bg-red",
    "синий": "bg-blue",
    "синя": "bg-blue",
    "голуб": "bg-blue",
    "бирюз": "bg-blue",
    "бежев": "bg-beige",
    "кремов": "bg-beige",
    "слонов": "bg-beige",
    "серебр": "bg-beige",
    "сер": "bg-beige",
    "зелён": "bg-green",
    "зелен": "bg-green",
    "хаки": "bg-green",
    "мятн": "bg-green",
    "оливк": "bg-green",
    "бел": "bg-lavender",
    "молочн": "bg-lavender",
    "чёрн": "bg-black",
    "черн": "bg-black",
    "графит": "bg-black",
    "коричнев": "bg-brown",
    "шоколад": "bg-brown",
    "кофе": "bg-brown",
    "верблюж": "bg-brown",
    "фиолет": "bg-purple",
    "сирен": "bg-purple",
    "лаванд": "bg-lavender",
    "тёмно-син": "bg-navy",
    "темно-син": "bg-navy",
    "индиго": "bg-navy",
    "деним": "bg-navy",
    "оранж": "bg-beige",
    "персик": "bg-pink",
    "коралл": "bg-pink",
    "жёлт": "bg-beige",
    "золот": "bg-beige",
    "горчич": "bg-brown",
    "нейтральн": "bg-beige",
    "телесн": "bg-beige",
    "абрикос": "bg-pink",
    "лосос": "bg-pink",
    "пудров": "bg-pink",
    "пыльн": "bg-pink",
    "фукси": "bg-pink",
    "рубинов": "bg-red",
    "терракот": "bg-brown",
    "ржав": "bg-brown",
    "бронзов": "bg-brown",
    "бронз": "bg-brown",
    "тауп": "bg-brown",
    "рыж": "bg-brown",
    "мандарин": "bg-beige",
    "лимон": "bg-beige",
    "изумруд": "bg-green",
    "дымчат": "bg-beige",
    "электрик": "bg-blue",
    "ярко-син": "bg-blue",
    "серебрист": "bg-beige",
}

COLOR_HEX: dict[str, str] = {
    "розов": "#E0A0B0",
    "красн": "#D06060",
    "алы": "#D06060",
    "бордо": "#8B3A3A",
    "синий": "#4060C0",
    "синя": "#4060C0",
    "голуб": "#70A0D0",
    "бирюз": "#40B0B0",
    "бежев": "#C8B8A0",
    "кремов": "#D8CDB8",
    "слонов": "#D8CDB8",
    "серебр": "#C0C0C0",
    "сер": "#A0A0A0",
    "зелён": "#60A060",
    "зелен": "#60A060",
    "хаки": "#8A8A60",
    "мятн": "#80C8A0",
    "оливк": "#808040",
    "бел": "#E8E8E8",
    "молочн": "#F0EAE0",
    "чёрн": "#303030",
    "черн": "#303030",
    "графит": "#404040",
    "коричнев": "#8A6A4A",
    "шоколад": "#6A4A2A",
    "кофе": "#7A5A3A",
    "верблюж": "#B09060",
    "фиолет": "#9070B0",
    "сирен": "#A080C0",
    "лаванд": "#B8A0D0",
    "тёмно-син": "#304080",
    "темно-син": "#304080",
    "индиго": "#304080",
    "деним": "#4060A0",
    "оранж": "#D08040",
    "персик": "#E0B090",
    "коралл": "#D07070",
    "жёлт": "#D0C060",
    "золот": "#C8A840",
    "горчич": "#B09030",
    "нейтральн": "#C8B8A0",
    "телесн": "#D8C0A8",
    "абрикос": "#E8A878",
    "лосос": "#E89080",
    "пудров": "#D8A8B0",
    "пыльн": "#C8A0A0",
    "фукси": "#D04080",
    "рубинов": "#A02040",
    "терракот": "#C06040",
    "ржав": "#B06030",
    "бронзов": "#A08040",
    "бронз": "#A08040",
    "тауп": "#A09080",
    "рыж": "#C07030",
    "мандарин": "#E08030",
    "лимон": "#D8D040",
    "изумруд": "#308060",
    "дымчат": "#B0B0B0",
    "электрик": "#2060E0",
    "ярко-син": "#2060E0",
    "серебрист": "#C0C0C8",
}

TYPE_EMOJI: dict[str, str] = {
    "outerwear": "🧥",
    "top": "👚",
    "bottom": "👖",
    "footwear": "👟",
    "hat": "🧢",
    "scarf": "🧣",
    "gloves": "🧤",
    "one_piece": "👗",
    "removable_layer": "👚",
    "tights": "🧦",
    "socks": "🧦",
}

TYPE_RU: dict[str, str] = {
    "outerwear": "Куртка",
    "top": "Верх",
    "bottom": "Штаны",
    "footwear": "Обувь",
    "hat": "Шапка",
    "scarf": "Шарф",
    "gloves": "Перчатки",
    "one_piece": "Комбинезон",
    "removable_layer": "Кардиган",
    "tights": "Колготки",
    "socks": "Носки",
}

TYPE_MISS_CSS: dict[str, str] = {
    "outerwear": "miss-outer",
    "top": "miss-top",
    "bottom": "miss-top",
    "footwear": "miss-foot",
    "hat": "miss-acc",
    "scarf": "miss-acc",
    "gloves": "miss-acc",
    "one_piece": "miss-top",
    "removable_layer": "miss-top",
}

# flat-lay position class per slot
_FI_CLASS: dict[str, str] = {
    "outerwear": "outer",
    "top": "top",
    "bottom": "bottom",
    "footwear": "shoe",
    "hat": "hat",
    "scarf": "scarf",
}

# emoji size overrides for flat-lay small slots
_FI_EMOJI_SIZE: dict[str, int] = {
    "footwear": 20,
    "hat": 16,
    "scarf": 14,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_segment(user) -> str:
    """Determine segment from user: 'mom' or 'woman'."""
    seg = getattr(user, "segment", None) or ""
    if seg in ("mom_girl", "mom_boy"):
        return "mom"
    return "woman"


def get_theme(segment: str) -> dict:
    return THEMES.get(segment, THEMES["mom"])


_COLOR_BG_SORTED = sorted(COLOR_BG.items(), key=lambda x: len(x[0]), reverse=True)
_COLOR_HEX_SORTED = sorted(COLOR_HEX.items(), key=lambda x: len(x[0]), reverse=True)


def get_color_bg(color: str) -> str:
    """CSS class for pastel background by item color."""
    if not color:
        return "bg-grey"
    c = color.lower()
    for key, cls in _COLOR_BG_SORTED:
        if key in c:
            return cls
    return "bg-grey"


def get_color_hex(color: str) -> str:
    """HEX color for palette dots."""
    if not color:
        return "#C0C0C0"
    c = color.lower()
    for key, hx in _COLOR_HEX_SORTED:
        if key in c:
            return hx
    return "#C0C0C0"


def _sign(t: float) -> str:
    return "+" if t >= 0 else ""


def format_temp(t: float | None) -> str:
    """Format temp with sign: '+4°' or '-2°'."""
    if t is None:
        return ""
    return f"{_sign(t)}{t:.0f}°"


def prepare_weather_data(weather: dict) -> dict:
    """Prepare weather dict for template rendering."""
    if not weather:
        return {}

    from services.brief_weather import wmo_to_emoji

    temp_now = weather.get("temp_now")
    temp_m = weather.get("temp_morning")
    temp_d = weather.get("temp_day")
    temp_e = weather.get("temp_evening")
    wmo_m = weather.get("wmo_morning", 0)
    wmo_d = weather.get("wmo_day", wmo_m)
    wmo_e = weather.get("wmo_evening", wmo_m)

    # Use current temp as the "morning" reference if available
    ref_temp = temp_now if temp_now is not None else temp_m
    evening_warn = (
        ref_temp is not None
        and temp_e is not None
        and temp_e < ref_temp - 3
    )

    return {
        "temp_now": temp_now,
        "temp_morning": temp_m,
        "temp_day": temp_d,
        "temp_evening": temp_e,
        "temp_now_str": format_temp(temp_now),
        "temp_morning_str": format_temp(temp_m),
        "temp_day_str": format_temp(temp_d),
        "temp_evening_str": format_temp(temp_e) if (temp_e is not None and round(temp_e) != round(temp_now or temp_m or 0)) else "",
        "icon_morning": wmo_to_emoji(wmo_m),
        "icon_day": wmo_to_emoji(wmo_d),
        "icon_evening": wmo_to_emoji(wmo_e),
        "evening_warn": evening_warn,
    }


def prepare_items_hybrid(outfit_slots: list[dict]) -> tuple[list[dict], list[dict]]:
    """Prepare items and missing lists for hybrid template.

    Returns (items, missing).
    """
    from services.image_builder import format_collage_label

    items = []
    missing = []
    real_count = 0

    for s in outfit_slots:
        slot = s.get("slot", "top")
        if slot in ("underwear", "tights", "socks", "base_layer"):
            continue

        if s.get("has_item"):
            real_count += 1
            label = format_collage_label(
                slot,
                s.get("item_type", ""),
                s.get("item_color", ""),
            )
            color = s.get("item_color", "")

            photo_b64 = ""
            if s.get("_photo_bytes"):
                try:
                    photo_b64 = base64.b64encode(s["_photo_bytes"]).decode()
                except Exception:
                    photo_b64 = ""

            # Detect solid vs patterned: if color has pattern words → not solid
            _color_lower = (color or "").lower()
            _type_lower = (s.get("item_type", "") or "").lower()
            _pattern_words = ["принт", "узор", "полоск", "клетк", "цветоч", "горох", "камуфляж", "леопард"]
            is_solid = not any(pw in _color_lower or pw in _type_lower for pw in _pattern_words)

            items.append({
                "label": label,
                "bg_class": get_color_bg(color),
                "emoji": TYPE_EMOJI.get(slot, "👕"),
                "color_hex": get_color_hex(color),
                "photo_base64": photo_b64,
                "is_solid": is_solid,
                "size_class": "",  # filled below
            })
        else:
            missing.append({
                "emoji": TYPE_EMOJI.get(slot, "👕"),
                "name_ru": TYPE_RU.get(slot, slot),
                "miss_css": TYPE_MISS_CSS.get(slot, "miss-acc"),
            })

    # Assign size classes
    n = len(items)
    for i, item in enumerate(items):
        if n == 1:
            item["size_class"] = "w100"
        elif n <= 4:
            item["size_class"] = "w50"
        else:
            item["size_class"] = "w50" if i < 2 else "w33"

    return items, missing


def prepare_items_full(outfit_slots: list[dict]) -> list[dict]:
    """Prepare items for full flat-lay template."""
    from services.image_builder import format_collage_label

    items = []
    for s in outfit_slots:
        slot = s.get("slot", "top")
        if slot in ("underwear", "tights", "socks", "base_layer"):
            continue
        if not s.get("has_item"):
            continue

        color = s.get("item_color", "")
        label = format_collage_label(slot, s.get("item_type", ""), color)

        photo_b64 = ""
        if s.get("_photo_bytes"):
            try:
                photo_b64 = base64.b64encode(s["_photo_bytes"]).decode()
            except Exception:
                photo_b64 = ""

        # Detect solid vs patterned
        _color_lower = (color or "").lower()
        _type_lower = (s.get("item_type", "") or "").lower()
        _pattern_words = ["принт", "узор", "полоск", "клетк", "цветоч", "горох", "камуфляж", "леопард"]
        is_solid = not any(pw in _color_lower or pw in _type_lower for pw in _pattern_words)

        items.append({
            "label": label,
            "bg_class": get_color_bg(color),
            "emoji": TYPE_EMOJI.get(slot, "👕"),
            "fi_class": _FI_CLASS.get(slot, "top"),
            "emoji_size": _FI_EMOJI_SIZE.get(slot),
            "photo_base64": photo_b64,
            "extra_style": "",
            "color_hex": get_color_hex(color),
            "is_solid": is_solid,
        })

    return items


def prepare_items_morning(outfit_slots: list[dict]) -> list[dict]:
    """Prepare items for morning update mini-collage."""
    items = []
    for s in outfit_slots:
        slot = s.get("slot", "top")
        if slot not in ("outerwear", "top", "bottom"):
            continue

        color = s.get("item_color", "")
        photo_b64 = ""
        if s.get("_photo_bytes"):
            try:
                from services.image_builder import _auto_trim
                trimmed = _auto_trim(s["_photo_bytes"])
                photo_b64 = base64.b64encode(trimmed).decode()
            except Exception:
                photo_b64 = ""

        items.append({
            "bg_class": get_color_bg(color),
            "emoji": TYPE_EMOJI.get(slot, "👕"),
            "fi_class": _FI_CLASS.get(slot, "top"),
            "photo_base64": photo_b64,
        })

    return items


def prepare_date_context(user, child) -> tuple[str, str]:
    """Return (date_str, context_str) for template header."""
    from datetime import date as _date

    _DAY_SHORT = {0: "ПН", 1: "ВТ", 2: "СР", 3: "ЧТ", 4: "ПТ", 5: "СБ", 6: "ВС"}
    _MONTH_UP = {
        1: "ЯНВАРЯ", 2: "ФЕВРАЛЯ", 3: "МАРТА", 4: "АПРЕЛЯ",
        5: "МАЯ", 6: "ИЮНЯ", 7: "ИЮЛЯ", 8: "АВГУСТА",
        9: "СЕНТЯБРЯ", 10: "ОКТЯБРЯ", 11: "НОЯБРЯ", 12: "ДЕКАБРЯ",
    }

    today = _date.today()
    day_name = _DAY_SHORT.get(today.weekday(), "")
    month = _MONTH_UP.get(today.month, "")
    date_str = f"{day_name}, {today.day} {month}"

    if child:
        context_str = "САДИК" if today.weekday() < 5 else "ПРОГУЛКА"
    else:
        context_str = ""

    return date_str, context_str


def prepare_layers(weather: dict, outfit_slots: list[dict]) -> list[dict]:
    """Build layers list for weather card (0 photos)."""
    temp_m = weather.get("temp_morning", 10.0) if weather else 10.0

    layers = [
        {"emoji": "🩲", "name": "базовый", "css_class": "base"},
    ]

    # Main clothing layers from outfit
    slot_layer_map = {
        "top": ("👚", "кофта"),
        "removable_layer": ("👚", "кардиган"),
        "bottom": ("👖", "штаны"),
        "one_piece": ("👗", "платье"),
        "outerwear": ("🧥", "куртка"),
        "footwear": ("👟", "обувь"),
        "hat": ("🧢", "шапка"),
        "scarf": ("🧣", "шарф"),
        "gloves": ("🧤", "перчатки"),
    }

    for s in outfit_slots:
        slot = s.get("slot", "")
        if slot in ("underwear", "tights", "socks", "base_layer"):
            continue
        emoji_name = slot_layer_map.get(slot)
        if not emoji_name:
            continue

        # Accent for outerwear, warn for rain gear
        css = "base"
        if slot == "outerwear":
            css = "accent"

        layers.append({
            "emoji": emoji_name[0],
            "name": s.get("item_type", emoji_name[1]).split()[0].lower() if s.get("has_item") else emoji_name[1],
            "css_class": css,
        })

    # Rain warning
    precip = weather.get("precip_max", 0) if weather else 0
    if precip and precip >= 50:
        layers.append({"emoji": "🌂", "name": "зонт!", "css_class": "warn"})

    return layers


def prepare_underwear_line(outfit: dict) -> str:
    """Build base layer text like '🩲 колготки · майка'."""
    parts = []
    if outfit.get("underwear_text"):
        parts.append(outfit["underwear_text"])
    for item in outfit.get("underwear_items", []):
        n = (getattr(item, "type", "") or "").split()[0].lower()
        if n:
            parts.append(n)
    leg = outfit.get("tights") or outfit.get("socks")
    if leg and hasattr(leg, "type"):
        parts.append(getattr(leg, "type", "колготки"))

    if parts:
        return "🩲 " + " · ".join(parts)
    return ""


# ── Flat-lay layout engine ────────────────────────────────────────────────────

# Canvas 440x520. Magazine flat-lay — items fill 80%+ of space.
# Reference: top-left big landscape top, top-right tall outerwear,
# center big portrait pants, bottom row shoes+bag+accessories.
# Light overlap between zones is OK (magazine feel).

# Reference: 3 layers in row 1: top(left,z=2) → mid_layer(center,z=3) → outerwear(right,z=4)
# Each layer slightly overlaps the previous, covering its right sleeve.
# Row 2: pants center. Row 3: accessories across bottom.
_FLATLAY_SLOTS = {
    # slot: (top, left, width, height, rotate, z-index)
    # Row 1: layered left→right with increasing z
    "top":        (10,  0,   175, 140, 0, 2),
    "top_2":      (5,   100, 195, 155, 0, 3),
    "outerwear":  (0,   230, 200, 200, 0, 4),
    # Row 2: bottom center-right, partially under outerwear
    "bottom":     (165, 115, 195, 265, 0, 5),
    "tights":     (280, 60,  80, 150, 0, 4),  # behind bottom, peeking below skirt
    # One-piece: central, tall — replaces top+bottom
    "one_piece":  (10,  80,  240, 380, 0, 3),
    # Row 3: pinned to bottom. Bag left, shoes right, accessories between.
    "bag":        (410, 0,   105, 105, 0, 6),
    "accessory_1":(170, 0,   75,  75,  0, 7),  # очки left
    "accessory_2":(325, 320, 65,  60,  0, 7),  # ремень right, above shoes
    "footwear_1": (410, 310, 125, 105, 0, 6),  # aligned bottom with bag
    "hat":        (0,   360, 75,  75,  0, 7),
    "scarf":      (85,  355, 70,  85,  0, 6),
    "gloves":     (165, 370, 65,  60,  0, 7),  # right of scarf, no overlap
}

_FLATLAY_SLOTS_ONE_PIECE = {
    "one_piece":  (5,   60,  250, 390, 0, 3),
    "outerwear":  (0,   240, 200, 200, 0, 4),
    "footwear_1": (410, 310, 125, 105, 0, 5),
    "accessory_1":(170, 0,   75,  75,  0, 6),
    "accessory_2":(260, 310, 75,  75,  0, 6),
    "bag":        (370, 0,   110, 110, 0, 5),
    "hat":        (170, 350, 75,  75,  0, 6),
    "scarf":      (260, 0,   70,  90,  0, 6),
    "gloves":     (260, 350, 65,  65,  0, 6),  # next to hat
    "tights":     (280, 330, 70,  120, 0, 2),
}


def prepare_items_flatlay(outfit_slots: list[dict]) -> list[dict]:
    """Prepare items with absolute positions for flat-lay template.

    Placeholders are weather-aware: only slots present in outfit_slots
    (from build_outfit_slots) get placeholders. No hardcoded essential slots.
    """

    # Use one_piece layout ONLY if one_piece is present AND no top+bottom
    has_one_piece = any(
        s.get("slot") == "one_piece" and s.get("has_item") and s.get("_photo_bytes")
        for s in outfit_slots
    )
    has_top = any(s.get("slot") == "top" and s.get("has_item") for s in outfit_slots)
    has_bottom = any(s.get("slot") == "bottom" and s.get("has_item") for s in outfit_slots)
    # Only use one_piece layout if it's truly the only main garment
    use_one_piece_layout = has_one_piece and not (has_top and has_bottom)
    layout = _FLATLAY_SLOTS_ONE_PIECE if use_one_piece_layout else _FLATLAY_SLOTS

    # Assign slots — support multiple items per type (top_2, footwear_2, etc.)
    slot_items = {}  # slot_key -> outfit_slot data
    type_counts = {}  # slot_type -> count

    for s in outfit_slots:
        slot = s.get("slot", "top")
        if not s.get("has_item") or not s.get("_photo_bytes"):
            continue
        if slot in ("underwear", "socks", "base_layer"):
            continue

        # Map to layout key, supporting multiples
        if slot in ("accessory", "hat", "scarf", "gloves", "tights"):
            if slot in layout and slot not in slot_items:
                key = slot
            else:
                type_counts["accessory"] = type_counts.get("accessory", 0) + 1
                key = f"accessory_{type_counts['accessory']}"
        elif slot == "bag":
            key = "bag"
        else:
            # top, bottom, footwear, outerwear, one_piece
            type_counts[slot] = type_counts.get(slot, 0) + 1
            cnt = type_counts[slot]
            # Try exact name first, then with _N suffix
            key = slot if cnt == 1 else f"{slot}_{cnt}"
            if key not in layout:
                key = f"{slot}_{cnt}"  # footwear → footwear_1

        if key and key in layout and key not in slot_items:
            slot_items[key] = s

    # Build positioned items
    items = []
    for key, s in slot_items.items():
        top, left, width, height, rotate, z = layout[key]

        photo_b64 = ""
        slot_name = s.get("slot", "top")
        try:
            from PIL import Image as _PILImg
            import io as _io
            _img = _PILImg.open(_io.BytesIO(s["_photo_bytes"])).convert("RGBA")

            # 0. Clean bg artifacts
            import numpy as _np
            _arr = _np.array(_img)
            # 0a. Alpha threshold: < 80 → transparent
            _arr[_arr[:, :, 3] < 80, 3] = 0
            # 0b. Keep only largest connected component (removes floor/bg islands)
            try:
                import cv2 as _cv2
                _alpha_bin = (_arr[:, :, 3] > 128).astype(_np.uint8)
                _n_labels, _labels = _cv2.connectedComponents(_alpha_bin)
                if _n_labels > 2:
                    _sizes = [(_np.sum(_labels == i), i) for i in range(1, _n_labels)]
                    _sizes.sort(reverse=True)
                    _main_size = _sizes[0][0]
                    for _sz, _lbl in _sizes[1:]:
                        if _sz < _main_size * 0.10:
                            _arr[_labels == _lbl, 3] = 0
            except Exception:
                pass
            _img = _PILImg.fromarray(_arr)

            # 1. Trim transparent edges
            _bbox = _img.split()[3].getbbox()
            if _bbox:
                _p = 3
                _bbox = (max(0, _bbox[0]-_p), max(0, _bbox[1]-_p),
                         min(_img.size[0], _bbox[2]+_p), min(_img.size[1], _bbox[3]+_p))
                _img = _img.crop(_bbox)

            # 1b. (removed — bottom trim handled by quality of bg removal)

            # 2. Portrait correction for all garments (flat-lay = vertical)
            _w, _h = _img.size
            _did_portrait_fix = False
            if slot_name in ("top", "bottom", "outerwear", "one_piece") and _w > _h * 1.2:
                _img = _img.rotate(90, expand=True, fillcolor=(0, 0, 0, 0))
                _did_portrait_fix = True
                _bbox = _img.split()[3].getbbox()
                if _bbox:
                    _p = 3
                    _bbox = (max(0, _bbox[0]-_p), max(0, _bbox[1]-_p),
                             min(_img.size[0], _bbox[2]+_p), min(_img.size[1], _bbox[3]+_p))
                    _img = _img.crop(_bbox)

            # 3. Apply flat_lay_rotation from Vision — only if no portrait fix was needed
            # (portrait fix already oriented the item correctly; Vision rotation
            #  was computed on the original photo orientation and conflicts)
            if not _did_portrait_fix:
                _bbox_data = s.get("bbox") or {}
                _rotation = s.get("flat_lay_rotation") or _bbox_data.get("flat_lay_rotation", 0)
                if _rotation and _rotation in (90, 180, 270):
                    _img = _img.rotate(-_rotation, expand=True, fillcolor=(0, 0, 0, 0))
                    _bbox = _img.split()[3].getbbox()
                    if _bbox:
                        _p = 3
                        _bbox = (max(0, _bbox[0]-_p), max(0, _bbox[1]-_p),
                                 min(_img.size[0], _bbox[2]+_p), min(_img.size[1], _bbox[3]+_p))
                        _img = _img.crop(_bbox)

            _buf = _io.BytesIO()
            _img.save(_buf, format="PNG")
            photo_b64 = base64.b64encode(_buf.getvalue()).decode()

            # Adjust slot dimensions to match photo aspect ratio
            _iw, _ih = _img.size
            if _iw > 0 and _ih > 0:
                _img_ratio = _iw / _ih
                _slot_ratio = width / max(height, 1)
                if _img_ratio < _slot_ratio * 0.5:
                    # Photo is much more portrait than slot — grow height, shrink width
                    _new_h = min(int(height * 1.8), 280)
                    width = max(int(_new_h * _img_ratio), 60)
                    height = _new_h
                    top = max(0, top + 20)  # shift down a bit
        except Exception:
            try:
                photo_b64 = base64.b64encode(s["_photo_bytes"]).decode()
            except Exception:
                continue

        items.append({
            "slot": s.get("slot", "top"),
            "label": s.get("item_type", ""),
            "photo_base64": photo_b64,
            "top": top,
            "left": left,
            "width": width,
            "height": height,
            "rotate": rotate,
            "z": z,
        })

    # ── Weather-aware placeholders ───────────────────────────────────────────
    # Show placeholders for:
    #   1. Slots with has_item=False (needed but missing from wardrobe)
    #   2. Slots with has_item=True but no _photo_bytes (item exists, no photo yet)
    # Only slots present in outfit_slots get placeholders (weather-aware).
    _SLOT_PH_EMOJI = {
        "outerwear": "🧥", "top": "👚", "bottom": "👖", "one_piece": "👗",
        "footwear": "👟", "bag": "👜", "hat": "🧢", "scarf": "🧣",
        "gloves": "🧤", "tights": "🧦", "accessory": "🕶",
    }
    # Override emoji based on placeholder label (weather-dependent)
    _LABEL_EMOJI_OVERRIDE = {
        "Комбинезон": "🧥", "Тёплый комбинезон": "🧥", "Тёплые ботинки": "👢",
        "Очки": "🕶", "Ремень": "📿", "Сумка": "👜",
    }
    _SLOT_PH_LABEL = {
        "outerwear": "куртку", "top": "верх", "bottom": "низ", "one_piece": "платье",
        "footwear": "обувь", "bag": "сумку", "hat": "шапку", "scarf": "шарф",
        "gloves": "перчатки", "tights": "колготки", "accessory": "аксессуар",
    }

    # Collect all occupied positions to avoid overlap
    _occupied = {(layout[k][0], layout[k][1]) for k in slot_items if k in layout}
    placeholders = []

    for s in outfit_slots:
        slot = s.get("slot", "")
        # Skip slots already rendered with real photos
        if s.get("has_item") and s.get("_photo_bytes"):
            continue
        if slot in ("underwear", "socks", "base_layer", "removable_layer"):
            continue

        # Map slot to layout key
        key = s.get("_layout_hint") or slot
        if slot == "footwear":
            key = "footwear_1"
        elif key not in layout:
            # Try numbered variants
            for suffix in ("_1", "_2"):
                if f"{slot}{suffix}" in layout:
                    key = f"{slot}{suffix}"
                    break

        if key not in layout or key in slot_items:
            continue

        top, left, width, height, _, _ = layout[key]
        # Skip if overlapping with a real item
        _overlaps = any(abs(top - ot) < 50 and abs(left - ol) < 50
                        for ot, ol in _occupied)
        if _overlaps:
            continue

        color = s.get("item_color") or ""
        raw_label = s.get("label") or _SLOT_PH_LABEL.get(slot, slot)

        # Items with photo → "📸 тип цвет", missing items → "+ label"
        if s.get("has_item"):
            item_type = s.get("item_type") or _SLOT_PH_LABEL.get(slot, slot)
            label = f"\U0001f4f8 {item_type}"
        else:
            label = f"+ {raw_label}"

        # Emoji: check label-based override first, then slot default
        emoji = _LABEL_EMOJI_OVERRIDE.get(raw_label) or _SLOT_PH_EMOJI.get(slot, "👕")

        placeholders.append({
            "emoji": emoji,
            "label": label,
            "top": top + 10,
            "left": left + 10,
            "width": max(60, width - 20),
            "height": max(60, height - 20),
            "color_class": get_color_bg(color) if color else "",
            "color_hex": get_color_hex(color) if color else "",
        })
        _occupied.add((top, left))

    # Progress
    filled = len(items)
    total = filled + len(placeholders)
    progress_pct = int(filled / max(total, 1) * 100) if placeholders else 100

    _missing_names = [p["label"].replace("+ ", "") for p in placeholders[:2]]
    if _missing_names:
        progress_text = f"{filled}/{total} · Сфоткай {', '.join(_missing_names)}"
    else:
        progress_text = ""

    return items, placeholders, progress_pct, progress_text


# ── Render function ──────────────────────────────────────────────────────────

async def render_html_to_png(html: str, width: int = 440) -> Optional[bytes]:
    """POST HTML to Playwright renderer → PNG bytes."""
    try:
        async with httpx.AsyncClient(timeout=RENDERER_TIMEOUT) as client:
            resp = await client.post(
                RENDERER_URL,
                json={"html": html, "width": width},
            )
            if resp.status_code == 200 and resp.content[:4] == b"\x89PNG":
                return resp.content
            logger.warning(
                "brief_renderer.http_error",
                status=resp.status_code,
                body=resp.text[:200],
            )
    except Exception as e:
        logger.warning("brief_renderer.unreachable", error=str(e))
    return None


def render_template(template_name: str, **kwargs) -> str:
    """Render a Jinja2 template to HTML string."""
    tpl = _jinja_env.get_template(template_name)
    return tpl.render(**kwargs)


async def render_style_passport(
    name: str,
    lang: str = "ru",
    sub_season: str = "",
    palette: list[str] | None = None,
    contrast_level: str = "",
    contrast_filled: int = 5,
    kibbe_primary: str = "",
    kibbe_secondary: str = "",
    kibbe_desc: str = "",
    essence_label: str = "",
    tonal_depth: str = "",
    chroma: str = "",
) -> Optional[bytes]:
    """Render style passport as 1080x1920 PNG for Stories."""
    html = render_template(
        "tpl_style_passport.html",
        name=name,
        lang=lang,
        sub_season=sub_season,
        palette=palette or [],
        contrast_level=contrast_level,
        contrast_filled=contrast_filled,
        kibbe_primary=kibbe_primary,
        kibbe_secondary=kibbe_secondary,
        kibbe_desc=kibbe_desc,
        essence_label=essence_label,
        tonal_depth=tonal_depth,
        chroma=chroma,
    )
    return await render_html_to_png(html, width=1080)
