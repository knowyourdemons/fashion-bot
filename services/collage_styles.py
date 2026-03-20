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


def collect_palette(slots: list) -> list[str]:
    """Unique color HEX values from slots."""
    seen: set[str] = set()
    result: list[str] = []
    for s in slots:
        c = (s.get("item_color") or "").lower()
        if c and c not in seen:
            seen.add(c)
            result.append(_color_hex(c))
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
        bg_color = bg or "#FFFFFF"

    children: list = []

    if is_placeholder:
        # Silhouette on pastel background + label below (like Miro refs)
        img = _get_img_el(slot_data, img_w, img_h, "0.35")
        if img:
            children.append(img)
        label = _get_slot_label(slot_data)
        children.append({
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "fontFamily": "DejaVu",
                    "fontSize": label_size,
                    "color": "#8A7A8A",
                    "marginTop": 4,
                },
                "children": label,
            },
        })
    else:
        # Real photo
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


def _weather_strip(header_text: str) -> Optional[dict]:
    """Build weather strip: +4° утро → +7° день → +2° вечер.
    Satori can't render emoji, so we use text labels."""
    # Parse temp from header: "Пт, 20 мар · сейчас +5°C · Алиса, садик"
    h_parts = (header_text or "").split(" · ")
    temp_part = h_parts[1] if len(h_parts) > 1 else ""
    if not temp_part or "°" not in temp_part:
        return None

    # Simple display of the temperature string
    return _text(temp_part, 13, "#777", marginTop=2)


def _footer_comment(footer_text: str, palette: list[str]) -> dict:
    """Footer with weather comment + palette dots + Касси."""
    children: list = []
    # Weather/outfit comment if present and not just "Касси..."
    if footer_text and "Касси" not in footer_text:
        children.append(_text(footer_text, 12, "#888", fontStyle="italic"))
    # Palette + Касси
    footer_row: list = []
    if palette:
        footer_row.append(_row(_circles(palette[:4], 12), gap=4))
    footer_row.append(_text("Касси", 11, "#AAA0B0"))
    children.append(_row(footer_row, gap=8, justifyContent="center", alignItems="center"))

    return _col(children, gap=6, padding="10px 24px 16px", alignItems="center")


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 1: FLAT LAY — items "laid out on bed", warm pastel, free layout
# Instagram-friendly, cozy aesthetic
# ═══════════════════════════════════════════════════════════════════════════════

def build_flat_lay(slots: list, header_text: str, footer_text: str,
                   palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    W = 440
    bg = "#FFF8F2"

    # Parse header: "Пт, 20 мар · +5°C · Алиса, садик" → parts
    h_parts = (header_text or "Образ дня").split(" · ")
    date_part = h_parts[0] if h_parts else ""
    temp_part = h_parts[1] if len(h_parts) > 1 else ""
    name_part = h_parts[2] if len(h_parts) > 2 else ""

    header_children: list = []
    if name_part:
        header_children.append(
            _row([
                _text(name_part, 18, "#333", fontWeight="bold"),
                _row(_circles(palette[:3], 14), gap=4, marginLeft="auto"),
            ], justifyContent="space-between", alignItems="center"),
        )
    if date_part or temp_part:
        sub = " · ".join(p for p in [date_part, temp_part] if p)
        header_children.append(_text(sub, 13, "#888"))

    header_el = _col(header_children, gap=4, padding="20px 24px 12px")

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
                    palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    W = 440

    # Parse header parts
    h_parts = (header_text or "Образ дня").split(" · ")
    date_part = h_parts[0] if h_parts else ""
    temp_part = h_parts[1] if len(h_parts) > 1 else ""
    name_part = h_parts[2] if len(h_parts) > 2 else ""

    header_children: list = []
    if name_part:
        header_children.append(
            _row([
                _text(name_part, 16, "#222", fontWeight="bold"),
                _row(_circles(palette[:4], 14), gap=4, marginLeft="auto"),
            ], justifyContent="space-between", alignItems="center"),
        )
    sub = " · ".join(p for p in [date_part, temp_part] if p)
    if sub:
        header_children.append(_text(sub, 12, "#888"))
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
                palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    W = 440

    # Gradient-like bg using palette colors (Satori doesn't support CSS gradients
    # so we use a solid light purple — matches the story ref)
    bg = "#E8E0F0" if not palette else _lighten(palette[0])

    # Parse header parts
    h_parts = (header_text or "Образ дня").split(" · ")
    date_part = h_parts[0] if h_parts else ""
    temp_part = h_parts[1] if len(h_parts) > 1 else ""
    name_part = h_parts[2] if len(h_parts) > 2 else h_parts[0]

    header_children: list = [
        _text(name_part, 22, "#333", fontWeight="bold", textAlign="center"),
    ]
    sub = " · ".join(p for p in [date_part, temp_part] if p)
    if sub:
        header_children.append(_text(sub.upper(), 11, "#666", letterSpacing=1, textAlign="center"))

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


# ── Builder registry ─────────────────────────────────────────────────────────

BUILDERS = {
    "flat_lay": build_flat_lay,
    "moodboard": build_moodboard,
    "story": build_story,
}
