"""
3 Satori collage styles: flat_lay, moodboard, story.

Each style function takes (slots, header_text, footer_text, palette_colors)
and returns (element_dict, width, height) for Satori rendering.
"""
from typing import Optional

from services.image_builder import (
    _pastel_bg,
    _auto_trim,
    _img_to_data_uri,
    _load_silhouette_bytes,
    format_collage_label,
    _get_placeholder_label,
)

STYLES = ["flat_lay", "moodboard", "story"]

_style_counter = 0


def next_style() -> str:
    """Round-robin style selection."""
    global _style_counter
    style = STYLES[_style_counter % len(STYLES)]
    _style_counter += 1
    return style


# ── Color helpers ────────────────────────────────────────────────────────────

_COLOR_HEX_SORTED = sorted({
    "белый": "#F0F0F0", "бел": "#F0F0F0",
    "чёрный": "#333333", "чёрн": "#333333",
    "серый": "#999999", "сер": "#999999",
    "розов": "#F4A0B0",
    "красн": "#D94040",
    "бордо": "#8B2252",
    "оранж": "#F0A030",
    "жёлт": "#F0D030",
    "бежев": "#E8D0B0",
    "зелён": "#60B060", "зелен": "#60B060",
    "голуб": "#70B0D8",
    "синий": "#4060C0", "синя": "#4060C0", "синев": "#4060C0",
    "фиолет": "#9060C0",
    "коричнев": "#8B6040",
    "лаванд": "#B090D0",
    "пыльно": "#D0A0A8", "пудр": "#D0A0A8",
    "серо-зел": "#80A888",
    "серо-голуб": "#90B0C0",
    "мятн": "#80C8A0",
    "персик": "#F0A878",
    "коралл": "#E07060",
    "горчич": "#C8A830",
    "оливк": "#808040",
    "терракот": "#C07050",
    "ржав": "#A06030",
    "золотист": "#D0B040",
    "кремов": "#F0E8D0",
    "молочн": "#F5F0E8",
    "телесн": "#E8D0B8",
    "фукси": "#D04080",
    "ярко-синя": "#2060E0", "ярко-синий": "#2060E0",
    "ярко-красн": "#E02020",
    "серебрист": "#C0C0C8",
    "светло-зел": "#90D090",
    "светло-кор": "#C0A080",
    "тёмно-синий": "#203060", "тёмно-син": "#203060",
    "тёмно-зел": "#305030",
    "нейтральн": "#B0B0B0",
}.items(), key=lambda x: len(x[0]), reverse=True)


def _color_hex(color_name: str) -> str:
    c = (color_name or "").lower()
    for key, val in _COLOR_HEX_SORTED:
        if key in c:
            return val
    return "#C0B8C8"


def collect_palette(slots: list, colortype: str = "") -> list[str]:
    """Color palette: from actual items + placeholder recommended colors + colortype."""
    seen: set[str] = set()
    result: list[str] = []

    # 1. Colors from actual items (real wardrobe)
    for s in slots:
        if s.get("has_item"):
            c = (s.get("item_color") or "").lower()
            if c:
                h = _color_hex(c)
                if h not in seen:
                    seen.add(h)
                    result.append(h)

    # 2. Recommended colors from placeholders (what to buy)
    for s in slots:
        if not s.get("has_item"):
            slot_key = s.get("slot", "top")
            h = _recommended_color_hex(slot_key, colortype)
            if h and h not in seen:
                seen.add(h)
                result.append(h)

    # 3. Fill with colortype base palette if still short
    _CT_PALETTE = {
        "Весна": ["#F0A878", "#E07060", "#60B060", "#E8D0B0"],
        "Лето": ["#B090D0", "#80C8A0", "#D0A0A8", "#90B0C0"],
        "Осень": ["#C8A830", "#C07050", "#808040", "#8B6040"],
        "Зима": ["#D94040", "#4060C0", "#333333", "#F0F0F0"],
    }
    if colortype and colortype in _CT_PALETTE:
        for c in _CT_PALETTE[colortype]:
            if c not in seen:
                seen.add(c)
                result.append(c)

    return result[:5]


# ── Zone splitting ───────────────────────────────────────────────────────────

def _split_zones(slots: list) -> tuple[list, list, list]:
    """Split slots into hero/main/small zones."""
    hero = [s for s in slots if s.get("slot") == "outerwear"]
    main = [s for s in slots if s.get("slot") in ("top", "removable_layer", "bottom", "one_piece")]
    small = [s for s in slots if s.get("slot") in ("footwear", "hat", "scarf", "gloves", "tights", "socks")]
    return hero, main, small[:4]


# ── Shared element builders ─────────────────────────────────────────────────

def _get_slot_label(slot_data: dict) -> str:
    if slot_data.get("has_item"):
        return format_collage_label(
            slot_data.get("slot", "top"),
            slot_data.get("item_type", ""),
            slot_data.get("item_color", ""),
        )
    return slot_data.get("label") or _get_placeholder_label(
        slot_data.get("slot", "top"),
        slot_data.get("gender", "girl"),
    )


def _get_img_el(slot_data: dict, w_pct: str = "75%", h_pct: str = "65%",
                opacity: str = "1") -> Optional[dict]:
    """Build img element for slot: real photo or silhouette placeholder."""
    if slot_data.get("has_item") and slot_data.get("_photo_bytes"):
        photo = _auto_trim(slot_data["_photo_bytes"])
        return {
            "type": "img",
            "props": {
                "src": _img_to_data_uri(photo),
                "width": w_pct, "height": h_pct,
                "style": {"objectFit": "contain"},
            },
        }
    sil = _load_silhouette_bytes(
        slot_data.get("slot", "top"),
        slot_data.get("gender", "girl"),
        slot_data.get("adult", False),
    )
    if sil:
        return {
            "type": "img",
            "props": {
                "src": _img_to_data_uri(sil),
                "width": w_pct, "height": h_pct,
                "style": {"objectFit": "contain", "opacity": opacity},
            },
        }
    return None


def _card(slot_data: dict, width: str, height: str, *,
          radius: int = 16, bg: str = None, shadow: bool = True,
          label_size: int = 14, img_w: str = "75%", img_h: str = "65%",
          ph_opacity: str = "0.4", show_label: bool = True) -> dict:
    """Universal item card with photo/placeholder + optional label."""
    is_placeholder = not slot_data.get("has_item")

    # Distinct saturated pastel per slot (matching Miro references)
    _SLOT_PASTELS = {
        "outerwear": "#C8D8E8", "top": "#FFD0D8", "bottom": "#C8D0F0",
        "one_piece": "#E0D0F0", "footwear": "#D0E0F0", "hat": "#D0E8D0",
        "scarf": "#F0DCC8", "gloves": "#D0D8F0", "tights": "#E8D8E8",
        "socks": "#E8D8E8",
    }
    if is_placeholder:
        slot_key = slot_data.get("slot", "top")
        bg_color = bg or _SLOT_PASTELS.get(slot_key, "#E0D8D0")
    else:
        # Real photo: transparent bg (no white card)
        bg_color = bg or "transparent"

    children: list = []

    if is_placeholder:
        # Clean pastel fill + text label only (no silhouette icons)
        label = _get_slot_label(slot_data)
        children.append({
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "fontFamily": "DejaVu",
                    "fontSize": label_size + 1,
                    "color": "#9A8A9A",
                },
                "children": label,
            },
        })
    else:
        # Real photo — no bg card
        img = _get_img_el(slot_data, img_w, img_h, ph_opacity)
        if img:
            children.append(img)

    style: dict = {
        "display": "flex",
        "flexDirection": "column",
        "alignItems": "center",
        "justifyContent": "center",
        "width": width,
        "height": height,
        "backgroundColor": bg_color,
        "borderRadius": radius,
        "overflow": "hidden",
    }

    return {"type": "div", "props": {"style": style, "children": children}}


def _row(children: list, gap: int = 12, **extra_style) -> dict:
    style = {
        "display": "flex",
        "flexDirection": "row",
        "gap": gap,
        "width": "100%",
        **extra_style,
    }
    return {"type": "div", "props": {"style": style, "children": children}}


def _col(children: list, gap: int = 12, **extra_style) -> dict:
    style = {
        "display": "flex",
        "flexDirection": "column",
        "gap": gap,
        "width": "100%",
        **extra_style,
    }
    return {"type": "div", "props": {"style": style, "children": children}}


def _text(text: str, size: int = 14, color: str = "#333", **extra) -> dict:
    style = {"display": "flex", "fontFamily": "DejaVu", "fontSize": size, "color": color, **extra}
    return {"type": "div", "props": {"style": style, "children": text}}


def _circles(palette: list[str], size: int = 18) -> list[dict]:
    return [
        {
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "width": size, "height": size,
                    "borderRadius": "50%",
                    "backgroundColor": c,
                    "border": "2px solid rgba(0,0,0,0.08)",
                },
            },
        }
        for c in palette
    ]


def _wmo_to_icon_name(code: int) -> str:
    """WMO weather code → icon filename (9 icons for all conditions)."""
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "partly_cloudy"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55):  # drizzle
        return "drizzle"
    if code in (56, 57, 66, 67):  # freezing drizzle/rain → sleet
        return "sleet"
    if code in (61, 63, 65, 80, 81, 82):  # rain / showers
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):  # snow
        return "snow"
    if code in (95, 96, 99):  # thunderstorm
        return "thunder"
    return "partly_cloudy"


_weather_icon_cache: dict[str, str] = {}


def _weather_icon_uri(name: str) -> Optional[str]:
    """Load weather PNG icon as data URI. Cached."""
    if name in _weather_icon_cache:
        return _weather_icon_cache[name]
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "weather", f"{name}.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        uri = _img_to_data_uri(data)
        _weather_icon_cache[name] = uri
        return uri
    return None


def _weather_strip_element(weather_data: dict) -> Optional[dict]:
    """Build weather strip with PNG icons: ☀+4° → 🌤+7° → 🌧+2°."""
    temp_m = weather_data.get("temp_morning")
    temp_e = weather_data.get("temp_evening")
    is_evening_cold = (temp_m is not None and temp_e is not None and temp_m - temp_e >= 3)
    is_evening_rain = weather_data.get("wmo_evening", 0) in (61, 63, 65, 80, 81, 82, 95, 96, 99)

    parts = []
    for key, label in [("temp_morning", "утро"), ("temp_day", "день"), ("temp_evening", "вечер")]:
        temp = weather_data.get(key)
        if temp is None:
            continue
        wmo_key = key.replace("temp_", "wmo_")
        wmo = weather_data.get(wmo_key, 2)
        icon_name = _wmo_to_icon_name(wmo)
        icon_uri = _weather_icon_uri(icon_name)
        sign = "+" if temp >= 0 else ""

        # Accent evening if cold drop or rain
        is_accent = (key == "temp_evening" and (is_evening_cold or is_evening_rain))
        temp_color = "#C05050" if is_accent else "#555"

        children: list = []
        if icon_uri:
            children.append({
                "type": "img",
                "props": {
                    "src": icon_uri,
                    "width": 24, "height": 24,
                    "style": {"objectFit": "contain"},
                },
            })
        children.append(_text(f"{sign}{temp:.0f}°", 14, temp_color, fontWeight="bold"))
        children.append(_text(label, 10, "#999"))

        parts.append({
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "flexDirection": "column",
                    "alignItems": "center",
                    "gap": 2,
                },
                "children": children,
            },
        })

    if not parts:
        return None

    # Add arrows between parts
    elements: list = []
    for i, p in enumerate(parts):
        elements.append(p)
        if i < len(parts) - 1:
            elements.append(_text("→", 12, "#CCC"))

    return _row(elements, gap=8, justifyContent="center", alignItems="center",
                padding="8px 0")


def _weather_strip(header_text: str) -> Optional[dict]:
    """Fallback: text-only weather strip from header."""
    h_parts = (header_text or "").split(" · ")
    temp_part = h_parts[1] if len(h_parts) > 1 else ""
    if not temp_part or "°" not in temp_part:
        return None
    return _text(temp_part, 13, "#777", marginTop=2)


def _footer_comment(footer_text: str, palette: list[str]) -> dict:
    """Footer: weather advice centered + palette dots + Касси."""
    children: list = []
    # Weather/outfit advice (italic, centered)
    if footer_text and "Касси" not in footer_text:
        children.append(_text(footer_text, 12, "#777", fontStyle="italic", textAlign="center"))
    # Касси — small, centered
    children.append(_text("Касси", 10, "#B0A8B8", textAlign="center"))

    return _col(children, gap=4, padding="10px 24px 16px", alignItems="center")


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 1: FLAT LAY — items "laid out on bed", warm pastel, free layout
# Instagram-friendly, cozy aesthetic
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_header(header_text: str) -> tuple[str, str, str]:
    """Parse 'Пт, 20 мар · +4°/+6°/+6° · Алиса, садик' → (date, temp, name)."""
    h_parts = (header_text or "Образ дня").split(" · ")
    date_part = h_parts[0] if h_parts else ""
    temp_part = h_parts[1] if len(h_parts) > 1 else ""
    name_part = h_parts[2] if len(h_parts) > 2 else ""
    return date_part, temp_part, name_part


def build_flat_lay(slots: list, header_text: str, footer_text: str,
                   palette: list[str], *, weather_data: dict = None) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    W = 440
    bg = "#FFF8F2"
    weather_data = weather_data or {}

    date_part, temp_part, name_part = _parse_header(header_text)

    header_children: list = []
    if name_part:
        name_row = [_text(name_part, 16, "#333", fontWeight="bold")]
        if palette:
            name_row.append(_row(_circles(palette[:3], 10), gap=4, marginLeft="auto"))
        header_children.append(_row(name_row, alignItems="center"))

    ws = _weather_strip_element(weather_data) if weather_data else None
    if ws:
        header_children.append(ws)
    elif temp_part:
        header_children.append(_text(temp_part, 13, "#888"))

    header_el = _col(header_children, gap=3, padding="20px 24px 10px")

    # Divider
    _fl_divider = {
        "type": "div",
        "props": {"style": {"display": "flex", "width": "100%", "height": 1, "backgroundColor": "#E8DCD0", "marginBottom": 4}},
    }

    body_rows: list = [_fl_divider]

    # Hero: outerwear — compact
    if hero:
        body_rows.append(_card(hero[0], "100%", "120px", radius=16, img_w="70%", img_h="60%"))

    # Main: top + bottom side by side (or one_piece full width)
    op = [s for s in main if s.get("slot") == "one_piece"]
    tops = [s for s in main if s.get("slot") in ("top", "removable_layer")]
    bots = [s for s in main if s.get("slot") == "bottom"]
    if op:
        body_rows.append(_card(op[0], "100%", "150px", radius=14))
    elif tops or bots:
        cards = []
        if tops:
            cards.append(_card(tops[0], "48%", "150px", radius=14))
        if bots:
            cards.append(_card(bots[0], "48%", "150px", radius=14))
        body_rows.append(_row(cards, justifyContent="space-between"))

    # Small: footwear + accessories — bigger for real photos to show
    if small:
        sm_cards = [_card(s, f"{90 // max(len(small), 1)}%", "110px",
                          radius=12, label_size=11, img_w="80%", img_h="70%") for s in small]
        body_rows.append(_row(sm_cards, gap=8, justifyContent="center"))

    body = _col(body_rows, gap=10, padding="0 20px")

    # Footer with divider + advice (same as moodboard)
    _fl_footer_div = {
        "type": "div",
        "props": {"style": {"display": "flex", "width": "100%", "height": 1, "backgroundColor": "#E8DCD0"}},
    }
    footer_parts = [_fl_footer_div]
    if footer_text:
        if "дожд" in footer_text.lower() or "зонт" in footer_text.lower():
            _e = "🌧"
        elif "холод" in footer_text.lower() or "теплее" in footer_text.lower():
            _e = "🧣"
        else:
            _e = "✨"
        footer_parts.append(_text(f"{_e} {footer_text}", 12, "#777", fontStyle="italic"))
    footer_parts.append(_text("Касси", 10, "#B0A8B8"))
    footer_el = _col(footer_parts, gap=4, padding="8px 24px 16px")

    h = 65  # header
    if ws: h += 65
    if hero: h += 132
    if op or tops or bots: h += 162
    if small: h += 122
    h += 55  # footer
    _fl = max(1, (len(footer_text) // 35 + 1)) if footer_text else 0
    h += _fl * 16
    h = max(h, 480)

    root = _col([header_el, body, footer_el], gap=0, backgroundColor=bg, height="100%")
    return root, W, h


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 2: MOODBOARD — clean white, Vogue/Pinterest aesthetic
# ═══════════════════════════════════════════════════════════════════════════════

def build_moodboard(slots: list, header_text: str, footer_text: str,
                    palette: list[str], *, weather_data: dict = None) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    W = 440
    weather_data = weather_data or {}

    date_part, temp_part, name_part = _parse_header(header_text)

    header_children: list = []
    if name_part:
        name_row = [_text(name_part, 16, "#222", fontWeight="bold")]
        if palette:
            name_row.append(_row(_circles(palette[:3], 10), gap=4, marginLeft="auto"))
        header_children.append(_row(name_row, alignItems="center"))

    ws = _weather_strip_element(weather_data) if weather_data else None
    if ws:
        header_children.append(ws)
    elif temp_part:
        header_children.append(_text(temp_part, 12, "#888"))
    header_el = _col(header_children, gap=4, padding="22px 24px 14px")

    # Divider after header/weather
    _divider = {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "width": "100%",
                "height": 1,
                "backgroundColor": "#E8E0E8",
                "marginBottom": 4,
            },
        },
    }

    body_rows: list = [_divider]

    if hero:
        body_rows.append(_card(hero[0], "100%", "120px", radius=12, shadow=False, img_w="70%", img_h="60%"))

    op = [s for s in main if s.get("slot") == "one_piece"]
    tops = [s for s in main if s.get("slot") in ("top", "removable_layer")]
    bots = [s for s in main if s.get("slot") == "bottom"]
    if op:
        body_rows.append(_card(op[0], "100%", "150px", radius=12, shadow=False))
    elif tops or bots:
        cards = []
        if tops:
            cards.append(_card(tops[0], "48%", "150px", radius=12, shadow=False))
        if bots:
            cards.append(_card(bots[0], "48%", "150px", radius=12, shadow=False))
        body_rows.append(_row(cards, justifyContent="space-between"))

    if small:
        sm_cards = [_card(s, f"{90 // max(len(small), 1)}%", "110px",
                          radius=10, label_size=11, shadow=False,
                          img_w="80%", img_h="70%") for s in small]
        body_rows.append(_row(sm_cards, gap=8, justifyContent="center"))

    body = _col(body_rows, gap=10, padding="0 20px")

    # Footer with divider + advice
    _footer_divider = {
        "type": "div",
        "props": {"style": {"display": "flex", "width": "100%", "height": 1, "backgroundColor": "#E8E0E8"}},
    }
    footer_children = [_footer_divider]
    if footer_text:
        # Pick emoji
        if "дожд" in footer_text.lower() or "зонт" in footer_text.lower():
            _e = "🌧"
        elif "холод" in footer_text.lower() or "теплее" in footer_text.lower():
            _e = "🧣"
        else:
            _e = "✨"
        footer_children.append(_text(f"{_e} {footer_text}", 12, "#777", fontStyle="italic"))
    footer_children.append(_text("Касси", 10, "#B0A8B8", textAlign="right"))
    footer_el = _col(footer_children, gap=4, padding="8px 24px 18px")

    h = 75  # header + weather
    if ws: h += 65
    if hero: h += 132
    if op or tops or bots: h += 162
    if small: h += 122
    h += 60  # footer with divider
    _footer_lines = max(1, (len(footer_text) // 35 + 1)) if footer_text else 0
    h += _footer_lines * 16
    h = max(h, 500)

    root = _col([header_el, body, footer_el], gap=0, backgroundColor="#FFF8F2", height="100%")
    return root, W, h


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 3: STORY — gradient bg from palette, bold name, for sharing/stories
# ═══════════════════════════════════════════════════════════════════════════════

def build_story(slots: list, header_text: str, footer_text: str,
                palette: list[str], *, weather_data: dict = None) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    W = 440
    weather_data = weather_data or {}

    # Gradient-like bg: blend first two palette colors
    if len(palette) >= 2:
        bg = _lighten(palette[0])
    elif palette:
        bg = _lighten(palette[0])
    else:
        bg = "#E8E0F0"

    date_part, temp_part, name_part = _parse_header(header_text)
    if not name_part:
        name_part = date_part

    name_row = [_text(name_part, 22, "#333", fontWeight="bold")]
    if palette:
        name_row.append(_row(_circles(palette[:3], 10), gap=4, marginLeft="auto"))
    header_children: list = [
        _row(name_row, alignItems="center", justifyContent="center"),
    ]
    if date_part and name_part != date_part:
        header_children.append(
            _text(date_part.upper(), 10, "#666", letterSpacing=1, textAlign="center"),
        )
    ws = _weather_strip_element(weather_data) if weather_data else None
    if ws:
        header_children.append(ws)
    elif temp_part:
        header_children.append(_text(temp_part, 12, "#777", textAlign="center"))

    header_el = _col(header_children, gap=4, padding="24px 24px 8px", alignItems="center")

    body_rows: list = []

    # Hero: outerwear — no bg override, use _SLOT_PASTELS
    if hero:
        body_rows.append(_card(hero[0], "100%", "180px", radius=20, img_w="78%", img_h="72%"))

    op = [s for s in main if s.get("slot") == "one_piece"]
    tops = [s for s in main if s.get("slot") in ("top", "removable_layer")]
    bots = [s for s in main if s.get("slot") == "bottom"]
    if op:
        body_rows.append(_card(op[0], "100%", "150px", radius=16))
    elif tops or bots:
        cards = []
        if tops:
            cards.append(_card(tops[0], "48%", "150px", radius=16))
        if bots:
            cards.append(_card(bots[0], "48%", "150px", radius=16))
        body_rows.append(_row(cards, justifyContent="space-between"))

    if small:
        sm_cards = [_card(s, f"{90 // max(len(small), 1)}%", "90px",
                          radius=14, label_size=11, img_w="65%", img_h="55%") for s in small]
        body_rows.append(_row(sm_cards, gap=8, justifyContent="center"))

    body = _col(body_rows, gap=10, padding="0 20px")

    footer_el = _footer_comment(footer_text, palette)

    h = 70
    if hero: h += 192
    if op or tops or bots: h += 162
    if small: h += 102
    h += 56
    h = max(h, 460)

    root = _col([header_el, body, footer_el], gap=0, backgroundColor=bg, height="100%")
    return root, W, h


def _lighten(hex_color: str) -> str:
    """Lighten a hex color for background use."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # Mix with white (85%)
        r = int(r + (255 - r) * 0.85)
        g = int(g + (255 - g) * 0.85)
        b = int(b + (255 - b) * 0.85)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return "#E8E0F0"


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE: BRIEF CARD — morning brief as dressing-order list with weather
# ═══════════════════════════════════════════════════════════════════════════════

def _color_dot(hex_color: str) -> dict:
    """Small color dot (CSS div, not emoji)."""
    return {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "width": 10, "height": 10,
                "borderRadius": "50%",
                "backgroundColor": hex_color,
                "marginTop": 3,
                "marginRight": 8,
                "flexShrink": 0,
            },
        },
    }


def _recommended_color_hex(slot: str, colortype: str = "default") -> str:
    """Get recommended color HEX for a placeholder slot based on colortype palette."""
    try:
        from worker.tasks.style_config import COLORTYPE_PALETTES
        palette = COLORTYPE_PALETTES.get(colortype, COLORTYPE_PALETTES.get("default", {}))
        colors = palette.get(slot, palette.get("outerwear", ["нейтральный"]))
        if colors:
            return _color_hex(colors[0])
    except Exception:
        pass
    return "#B0B8C0"  # neutral gray-blue fallback


def _section_label(text_str: str) -> dict:
    """Section header with line: "ОДЕЖДА ————————————"."""
    return _row([
        _text(text_str, 9, "#B0A0B0", letterSpacing=1, flexShrink=0),
        {
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "flex": 1,
                    "height": 1,
                    "backgroundColor": "#E0D8E0",
                    "marginLeft": 8,
                    "marginTop": 5,
                },
            },
        },
    ], alignItems="center", marginTop=4)


def _item_row(slot: str, color_name: str, label: str,
              is_placeholder: bool = False, colortype: str = "default") -> dict:
    """Single item row with color dot.
    Real item: dot = actual item color.
    Placeholder: dot = recommended color from colortype palette.
    """
    if is_placeholder:
        dot_hex = _recommended_color_hex(slot, colortype)
        children = [
            _color_dot(dot_hex),
            _text(label, 14, "#AAA"),
            _text("добавь", 11, "#C8A0B0", marginLeft="auto"),
        ]
    else:
        dot_hex = _color_hex(color_name)
        children = [
            _color_dot(dot_hex),
            _text(label, 14, "#333", fontWeight="500"),
        ]
    return _row(children, gap=0, alignItems="center")


def _white_card(children: list, **extra) -> dict:
    """White card with rounded corners."""
    style = {
        "display": "flex", "flexDirection": "column",
        "backgroundColor": "#FFFFFF", "borderRadius": 14,
        "padding": "14px 16px", "gap": 7, "width": "100%",
        **extra,
    }
    return {"type": "div", "props": {"style": style, "children": children}}


def build_brief_card(slots: list, header_text: str, footer_text: str,
                     palette: list[str], *, weather_data: dict = None,
                     outfit: dict = None, colortype: str = "default") -> tuple[dict, int, int]:
    """Morning brief card: items in dressing order + weather."""
    W = 420
    weather_data = weather_data or {}
    outfit = outfit or {}

    date_part, temp_part, name_part = _parse_header(header_text)

    # ── Header ──
    header_children = []
    if date_part:
        header_children.append(_text(date_part.upper(), 10, "#B08060", letterSpacing=1))
    if name_part:
        header_children.append(_text(name_part, 20, "#333", fontWeight="bold"))

    header_el = _col(header_children, gap=2, padding="20px 20px 8px")

    # ── Weather strip ──
    ws = _weather_strip_element(weather_data)
    weather_card = None
    if ws:
        weather_card = _white_card([ws])

    # ── ПОД ОДЕЖДУ (first — dressing order!) ──
    under_parts = []
    if outfit.get("underwear_text"):
        under_parts.append(outfit["underwear_text"])
    for item in outfit.get("underwear_items", []):
        name = (getattr(item, "type", "") or "").split()[0].lower()
        if name:
            under_parts.append(name)
    leg = outfit.get("tights") or outfit.get("socks")
    if leg and hasattr(leg, "type"):
        under_parts.append(getattr(leg, "type", "колготки"))

    under_card = None
    if under_parts:
        under_rows = [_section_label("ПОД ОДЕЖДУ")]
        for up in under_parts:
            under_rows.append(
                _row([_color_dot("#C0B8C0"), _text(up, 13, "#888")], gap=0, alignItems="center")
            )
        under_card = _white_card(under_rows, backgroundColor="#F8F6FA")

    # ── ОДЕЖДА ──
    clothes_rows: list = []
    for s in slots:
        sk = s.get("slot", "")
        if sk in ("top", "removable_layer", "bottom", "one_piece"):
            if s.get("has_item"):
                color = s.get("item_color", "")
                label = f"{s.get('item_type', '')} {color}".strip()
                clothes_rows.append(_item_row(sk, color, label))
            else:
                ph = s.get("label") or _get_placeholder_label(sk, s.get("gender", "girl"))
                clothes_rows.append(_item_row(sk, "", ph, is_placeholder=True, colortype=colortype))

    # ── ОБУВЬ ──
    foot_rows: list = []
    for s in slots:
        if s.get("slot") == "footwear":
            if s.get("has_item"):
                color = s.get("item_color", "")
                label = f"{s.get('item_type', '')} {color}".strip()
                foot_rows.append(_item_row("footwear", color, label))
            else:
                foot_rows.append(_item_row("footwear", "", "Обувь", is_placeholder=True, colortype=colortype))

    # ── НА ВЫХОД ──
    exit_rows: list = []
    for s in slots:
        sk = s.get("slot", "")
        if sk in ("outerwear", "hat", "scarf", "gloves"):
            if s.get("has_item"):
                color = s.get("item_color", "")
                label = f"{s.get('item_type', '')} {color}".strip()
                exit_rows.append(_item_row(sk, color, label))
            else:
                ph = s.get("label") or _get_placeholder_label(sk, s.get("gender", "girl"))
                exit_rows.append(_item_row(sk, "", ph, is_placeholder=True, colortype=colortype))

    # ── Build items card with section labels ──
    items_content: list = []
    if clothes_rows:
        items_content.append(_section_label("ОДЕЖДА"))
        items_content.extend(clothes_rows)
    if foot_rows:
        items_content.append(_section_label("ОБУВЬ"))
        items_content.extend(foot_rows)
    if exit_rows:
        items_content.append(_section_label("НА ВЫХОД"))
        items_content.extend(exit_rows)

    items_card = _white_card(items_content) if items_content else None

    # ── Footer: weather advice ──
    footer_children = []
    if footer_text:
        # Pick emoji based on content
        if "дожд" in footer_text.lower() or "зонт" in footer_text.lower():
            _emoji = "🌧"
        elif "холод" in footer_text.lower() or "теплее" in footer_text.lower():
            _emoji = "🧣"
        elif "прохлад" in footer_text.lower() or "куртк" in footer_text.lower():
            _emoji = "🧥"
        else:
            _emoji = "✨"
        footer_children.append(_text(f"{_emoji} {footer_text}", 12, "#777", fontStyle="italic"))
        footer_children.append(_text("— Касси", 10, "#B0A8B8"))
    else:
        footer_children.append(_text("— Касси", 10, "#B0A8B8"))
    footer_el = _col(footer_children, gap=3, padding="8px 20px 16px", alignItems="flex-start")

    # ── Assemble (dressing order: under → clothes → shoes → exit) ──
    body_parts = []
    if weather_card:
        body_parts.append(weather_card)
    if under_card:
        body_parts.append(under_card)
    if items_card:
        body_parts.append(items_card)

    body = _col(body_parts, gap=8, padding="0 16px")

    # Height calc
    h = 60  # header
    if weather_card: h += 80
    n_under = len(under_parts) if under_parts else 0
    if under_card: h += n_under * 24 + 40
    n_items = len(clothes_rows) + len(foot_rows) + len(exit_rows)
    n_sections = (1 if clothes_rows else 0) + (1 if foot_rows else 0) + (1 if exit_rows else 0)
    h += n_items * 28 + n_sections * 22 + 44  # items card
    # Footer: estimate lines (40 chars per line)
    _footer_lines = max(1, (len(footer_text) // 35 + 1)) if footer_text else 0
    h += _footer_lines * 18 + 40  # footer
    h = max(h, 400)

    root = _col([header_el, body, footer_el], gap=6,
                backgroundColor="#F7F0F4", borderRadius=20, height="100%")
    return root, W, h


# ── Builder registry ─────────────────────────────────────────────────────────

BUILDERS = {
    "flat_lay": build_flat_lay,
    "moodboard": build_moodboard,
    "story": build_story,
}
