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
    "белый": "#F0F0F0", "чёрный": "#333333", "серый": "#999999",
    "розовый": "#F4A0B0", "красный": "#D94040", "бордовый": "#8B2252",
    "оранжевый": "#F0A030", "жёлтый": "#F0D030", "бежевый": "#E8D0B0",
    "зелёный": "#60B060", "голубой": "#70B0D8", "синий": "#4060C0",
    "фиолетовый": "#9060C0", "коричневый": "#8B6040", "лавандовый": "#B090D0",
    "пыльно-розовый": "#D0A0A8", "серо-зелёный": "#80A888",
}.items(), key=lambda x: len(x[0]), reverse=True)


def _color_hex(color_name: str) -> str:
    c = (color_name or "").lower()
    for key, val in _COLOR_HEX_SORTED:
        if key in c:
            return val
    return "#C0B8C8"


def collect_palette(slots: list, colortype: str = "") -> list[str]:
    """Color palette: from actual items + colortype recommendations."""
    # Colors from actual items
    seen: set[str] = set()
    result: list[str] = []
    for s in slots:
        c = (s.get("item_color") or "").lower()
        if c and c not in seen:
            seen.add(c)
            result.append(_color_hex(c))

    # Add colortype-based colors for variety
    _CT_PALETTE = {
        "Весна": ["#F4A0B0", "#F0D030", "#60B060", "#E8D0B0"],
        "Лето": ["#70B0D8", "#B090D0", "#D0A0A8", "#999999"],
        "Осень": ["#8B6040", "#F0A030", "#60B060", "#8B2252"],
        "Зима": ["#D94040", "#4060C0", "#333333", "#F0F0F0"],
    }
    if colortype and colortype in _CT_PALETTE:
        for c in _CT_PALETTE[colortype]:
            if c not in result:
                result.append(c)

    return result[:6]


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
        children.append(_text(f"{sign}{temp:.0f}°", 14, "#555", fontWeight="bold"))
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
        header_children.append(_text(name_part, 18, "#333", fontWeight="bold"))
    if date_part:
        # Date + palette dots on same line
        header_children.append(
            _row([
                _text(date_part, 12, "#999"),
                _row(_circles(palette[:3], 8), gap=3, marginLeft="auto"),
            ], alignItems="center"),
        )

    ws = _weather_strip_element(weather_data) if weather_data else None
    if ws:
        header_children.append(ws)
    elif temp_part:
        header_children.append(_text(temp_part, 13, "#888"))

    header_el = _col(header_children, gap=3, padding="20px 24px 10px")

    body_rows: list = []

    # Hero: outerwear — LARGE (clear hierarchy)
    if hero:
        body_rows.append(_card(hero[0], "100%", "220px", radius=20, img_w="80%", img_h="70%"))

    # Main: top + bottom side by side (or one_piece full width)
    op = [s for s in main if s.get("slot") == "one_piece"]
    tops = [s for s in main if s.get("slot") in ("top", "removable_layer")]
    bots = [s for s in main if s.get("slot") == "bottom"]
    if op:
        body_rows.append(_card(op[0], "100%", "170px", radius=16))
    elif tops or bots:
        cards = []
        if tops:
            cards.append(_card(tops[0], "48%", "170px", radius=16))
        if bots:
            cards.append(_card(bots[0], "48%", "170px", radius=16))
        body_rows.append(_row(cards, justifyContent="space-between"))

    # Small: footwear + accessories — noticeably smaller
    if small:
        sm_cards = [_card(s, f"{90 // max(len(small), 1)}%", "90px",
                          radius=12, label_size=11, img_w="65%", img_h="55%") for s in small]
        body_rows.append(_row(sm_cards, gap=8, justifyContent="center"))

    body = _col(body_rows, gap=10, padding="0 20px")

    # Footer: weather comment + palette + Касси
    footer_el = _footer_comment(footer_text, palette)

    h = 60 + 16  # header
    if hero: h += 232
    if op or tops or bots: h += 182
    if small: h += 102
    h += 56  # footer
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
        header_children.append(_text(name_part, 16, "#222", fontWeight="bold"))
    if date_part:
        header_children.append(
            _row([
                _text(date_part, 11, "#999"),
                _row(_circles(palette[:3], 8), gap=3, marginLeft="auto"),
            ], alignItems="center"),
        )
    ws = _weather_strip_element(weather_data) if weather_data else None
    if ws:
        header_children.append(ws)
    elif temp_part:
        header_children.append(_text(temp_part, 12, "#888"))
    header_el = _col(header_children, gap=3, padding="20px 24px 14px")

    body_rows: list = []

    if hero:
        body_rows.append(_card(hero[0], "100%", "190px", radius=12, shadow=False, img_w="75%", img_h="68%"))

    op = [s for s in main if s.get("slot") == "one_piece"]
    tops = [s for s in main if s.get("slot") in ("top", "removable_layer")]
    bots = [s for s in main if s.get("slot") == "bottom"]
    if op:
        body_rows.append(_card(op[0], "100%", "160px", radius=12, shadow=False))
    elif tops or bots:
        cards = []
        if tops:
            cards.append(_card(tops[0], "48%", "160px", radius=12, shadow=False))
        if bots:
            cards.append(_card(bots[0], "48%", "160px", radius=12, shadow=False))
        body_rows.append(_row(cards, justifyContent="space-between"))

    if small:
        sm_cards = [_card(s, f"{90 // max(len(small), 1)}%", "85px",
                          radius=10, label_size=11, shadow=False,
                          img_w="60%", img_h="50%") for s in small]
        body_rows.append(_row(sm_cards, gap=8, justifyContent="center"))

    body = _col(body_rows, gap=10, padding="0 20px")
    footer_el = _footer_comment(footer_text, palette)

    h = 60
    if hero: h += 202
    if op or tops or bots: h += 172
    if small: h += 97
    h += 56
    h = max(h, 440)

    root = _col([header_el, body, footer_el], gap=0, backgroundColor="#FFFFFF", height="100%")
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

    header_children: list = [
        _text(name_part, 22, "#333", fontWeight="bold", textAlign="center"),
    ]
    if date_part and name_part != date_part:
        header_children.append(
            _row([
                _text(date_part.upper(), 10, "#666", letterSpacing=1),
                _row(_circles(palette[:4], 8), gap=3, marginLeft=8),
            ], justifyContent="center", alignItems="center"),
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

def _color_dot(color_name: str) -> dict:
    """Small color dot for item list."""
    hex_c = _color_hex(color_name)
    return {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "width": 10, "height": 10,
                "borderRadius": "50%",
                "backgroundColor": hex_c,
                "marginTop": 4,
                "marginRight": 6,
                "flexShrink": 0,
            },
        },
    }


def build_brief_card(slots: list, header_text: str, footer_text: str,
                     palette: list[str], *, weather_data: dict = None,
                     outfit: dict = None) -> tuple[dict, int, int]:
    """Morning brief card: items in dressing order + weather."""
    W = 420
    weather_data = weather_data or {}
    outfit = outfit or {}

    date_part, temp_part, name_part = _parse_header(header_text)

    # Header
    header_children = []
    if date_part:
        header_children.append(_text(date_part.upper(), 11, "#B08060", letterSpacing=1))
    if name_part:
        header_children.append(_text(name_part, 18, "#333", fontWeight="bold"))

    # Weather strip
    ws = _weather_strip_element(weather_data)
    if ws:
        header_children.append(ws)

    header_el = _col(header_children, gap=3, padding="20px 24px 12px")

    # Items list in dressing order
    item_rows: list = []

    # ОДЕЖДА group (main visible items)
    clothes_items: list = []
    for s in slots:
        slot_key = s.get("slot", "")
        if slot_key in ("top", "removable_layer", "bottom", "one_piece"):
            if s.get("has_item"):
                color = s.get("item_color", "")
                label = f"{s.get('item_type', '')} {color}".strip()
                clothes_items.append(
                    _row([_color_dot(color), _text(label, 14, "#333")], gap=0, alignItems="center")
                )
            else:
                ph_label = s.get("label") or _get_placeholder_label(slot_key, s.get("gender", "girl"))
                clothes_items.append(
                    _row([
                        _color_dot("серый"),
                        _text(ph_label, 14, "#999"),
                        _text("добавь", 11, "#CC8855", marginLeft="auto"),
                    ], gap=0, alignItems="center")
                )

    # OUTERWEAR + accessories (НА ВЫХОД)
    exit_items: list = []
    for s in slots:
        slot_key = s.get("slot", "")
        if slot_key in ("outerwear", "hat", "scarf", "gloves"):
            if s.get("has_item"):
                color = s.get("item_color", "")
                label = f"{s.get('item_type', '')} {color}".strip()
                exit_items.append(
                    _row([_color_dot(color), _text(label, 14, "#333")], gap=0, alignItems="center")
                )
            else:
                ph_label = s.get("label") or _get_placeholder_label(slot_key, s.get("gender", "girl"))
                exit_items.append(
                    _row([
                        _color_dot("серый"),
                        _text(ph_label, 14, "#999"),
                        _text("добавь", 11, "#CC8855", marginLeft="auto"),
                    ], gap=0, alignItems="center")
                )

    # FOOTWEAR
    foot_items: list = []
    for s in slots:
        if s.get("slot") == "footwear":
            if s.get("has_item"):
                color = s.get("item_color", "")
                label = f"{s.get('item_type', '')} {color}".strip()
                foot_items.append(
                    _row([_color_dot(color), _text(label, 14, "#333")], gap=0, alignItems="center")
                )
            else:
                foot_items.append(
                    _row([
                        _color_dot("серый"),
                        _text("Обувь", 14, "#999"),
                        _text("добавь", 11, "#CC8855", marginLeft="auto"),
                    ], gap=0, alignItems="center")
                )

    # Build sections
    all_list_items = clothes_items + foot_items + exit_items
    if all_list_items:
        list_section = _col(all_list_items, gap=6, padding="12px 20px",
                           backgroundColor="#FFFFFF", borderRadius=12)
        item_rows.append(list_section)

    # ПОД ОДЕЖДУ
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

    if under_parts:
        under_el = _col([
            _text("ПОД ОДЕЖДУ", 10, "#AAA", letterSpacing=1),
            _text(", ".join(under_parts), 13, "#888"),
        ], gap=2, padding="10px 20px", backgroundColor="#F8F6FA", borderRadius=10)
        item_rows.append(under_el)

    body = _col(item_rows, gap=8, padding="0 16px")

    # Footer: weather advice
    footer_el = _footer_comment(footer_text, palette)

    h = 70  # header
    h += len(all_list_items) * 28 + 36  # items list
    if under_parts: h += 50
    h += 56  # footer
    if ws: h += 60  # weather strip
    h = max(h, 350)

    root = _col([header_el, body, footer_el], gap=8,
                backgroundColor="#FFF5F0", borderRadius=20, height="100%")
    return root, W, h


# ── Builder registry ─────────────────────────────────────────────────────────

BUILDERS = {
    "flat_lay": build_flat_lay,
    "moodboard": build_moodboard,
    "story": build_story,
}
