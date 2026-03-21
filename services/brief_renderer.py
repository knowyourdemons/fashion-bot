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
    "розовый": "bg-pink",
    "красный": "bg-red",
    "синий": "bg-blue",
    "голубой": "bg-blue",
    "бежевый": "bg-beige",
    "серый": "bg-grey",
    "зелёный": "bg-green",
    "зеленый": "bg-green",
    "белый": "bg-white",
    "чёрный": "bg-black",
    "черный": "bg-black",
    "коричневый": "bg-brown",
    "фиолетовый": "bg-purple",
    "тёмно-синий": "bg-navy",
    "темно-синий": "bg-navy",
    "лавандовый": "bg-lavender",
}

COLOR_HEX: dict[str, str] = {
    "розовый": "#E0A0B0",
    "красный": "#D06060",
    "синий": "#4060C0",
    "голубой": "#70A0D0",
    "бежевый": "#C8B8A0",
    "серый": "#A0A0A0",
    "зелёный": "#60A060",
    "зеленый": "#60A060",
    "белый": "#E8E8E8",
    "чёрный": "#303030",
    "черный": "#303030",
    "коричневый": "#8A6A4A",
    "фиолетовый": "#9070B0",
    "тёмно-синий": "#304080",
    "темно-синий": "#304080",
    "лавандовый": "#B8A0D0",
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

    temp_m = weather.get("temp_morning")
    temp_d = weather.get("temp_day")
    temp_e = weather.get("temp_evening")
    wmo_m = weather.get("wmo_morning", 0)
    wmo_d = weather.get("wmo_day", wmo_m)
    wmo_e = weather.get("wmo_evening", wmo_m)

    evening_warn = (
        temp_m is not None
        and temp_e is not None
        and temp_e < temp_m - 3
    )

    return {
        "temp_morning": temp_m,
        "temp_day": temp_d,
        "temp_evening": temp_e,
        "temp_morning_str": format_temp(temp_m),
        "temp_day_str": format_temp(temp_d),
        "temp_evening_str": format_temp(temp_e),
        "icon_morning": wmo_to_emoji(wmo_m),
        "icon_day": wmo_to_emoji(wmo_d),
        "icon_evening": wmo_to_emoji(wmo_e),
        "evening_warn": evening_warn,
    }


def prepare_items_hybrid(outfit_slots: list[dict]) -> tuple[list[dict], list[dict]]:
    """Prepare items and missing lists for hybrid template.

    Returns (items, missing).
    """
    from services.image_builder import format_collage_label, _auto_trim, _img_to_data_uri

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

            items.append({
                "label": label,
                "bg_class": get_color_bg(color),
                "emoji": TYPE_EMOJI.get(slot, "👕"),
                "color_hex": get_color_hex(color),
                "photo_base64": photo_b64,
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
    from services.image_builder import format_collage_label, _auto_trim

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

        items.append({
            "label": label,
            "bg_class": get_color_bg(color),
            "emoji": TYPE_EMOJI.get(slot, "👕"),
            "fi_class": _FI_CLASS.get(slot, "top"),
            "emoji_size": _FI_EMOJI_SIZE.get(slot),
            "photo_base64": photo_b64,
            "extra_style": "",
            "color_hex": get_color_hex(color),
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


def collect_palette(items: list[dict], max_colors: int = 5) -> list[str]:
    """Collect unique palette hex colors from items."""
    palette = []
    seen: set[str] = set()
    for item in items:
        hx = item.get("color_hex", "#C0C0C0")
        if hx not in seen and len(palette) < max_colors:
            palette.append(hx)
            seen.add(hx)
    return palette


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
