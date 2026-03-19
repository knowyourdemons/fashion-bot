"""
6 Satori collage styles for outfit-of-the-day.

Each style function takes (slots, header_text, footer_text, palette_colors)
and returns (element_dict, width, height) for Satori rendering.

Shared helpers: _item_card, _row, _text, _circle built on top of
image_builder's _pastel_bg, _auto_trim, _img_to_data_uri, etc.
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

STYLES = [
    "magazine",
    "editorial",
    "story_card",
    "polaroid",
    "palette_first",
    "pro_stylist",
]

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
          ph_opacity: str = "0.4") -> dict:
    """Universal item card with photo/placeholder + label."""
    bg_color = bg or _pastel_bg(slot_data.get("item_color", ""))
    label = _get_slot_label(slot_data)
    img = _get_img_el(slot_data, img_w, img_h, ph_opacity)

    children: list = []
    if img:
        children.append(img)
    children.append({
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "fontFamily": "DejaVu",
                "fontSize": label_size,
                "color": "#8B7B8B",
                "marginTop": 4,
            },
            "children": label,
        },
    })

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
    if shadow:
        style["boxShadow"] = "0 2px 12px rgba(0,0,0,0.06)"

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


def _footer_with_palette(palette: list[str], text: str = "Касси -- твой личный стилист") -> dict:
    children: list = []
    if palette:
        children.append(_row(_circles(palette), gap=6, marginRight=12))
    children.append(_text(text, 13, "#AAA0B9"))
    return {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "justifyContent": "center",
                "alignItems": "center",
                "width": "100%",
                "padding": "14px 0",
                "fontFamily": "DejaVu",
            },
            "children": children,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 1: MAGAZINE — dark header, colored cards, palette footer
# ═══════════════════════════════════════════════════════════════════════════════

def build_magazine(slots: list, header_text: str, footer_text: str,
                   palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    pad = 24
    body_rows: list = []

    if hero:
        body_rows.append(_card(hero[0], "100%", "340px", img_w="80%", img_h="70%"))
    op = [s for s in main if s.get("slot") == "one_piece"]
    tops = [s for s in main if s.get("slot") in ("top", "removable_layer")]
    bots = [s for s in main if s.get("slot") == "bottom"]
    if op:
        body_rows.append(_card(op[0], "100%", "260px"))
    elif tops or bots:
        cards = []
        if tops:
            cards.append(_card(tops[0], "50%", "260px"))
        if bots:
            cards.append(_card(bots[0], "50%", "260px"))
        body_rows.append(_row(cards))
    if small:
        pct = f"{100 // max(len(small), 1)}%"
        body_rows.append(_row([_card(s, pct, "160px", label_size=12) for s in small]))

    header = {
        "type": "div",
        "props": {
            "style": {
                "display": "flex", "flexDirection": "column", "justifyContent": "center",
                "width": "100%", "padding": f"{pad}px {pad}px 16px",
                "backgroundColor": "#1a1a2e", "color": "#fff", "fontFamily": "DejaVu",
            },
            "children": [
                _text("LOOK OF THE DAY", 12, "#9090B0", letterSpacing=3),
                _text(header_text or "Образ дня", 22, "#fff", marginTop=4, fontWeight="bold"),
            ],
        },
    }

    h = 80 + 44 + 32
    if hero: h += 352
    if op or tops or bots: h += 272
    if small: h += 172
    h = max(h, 400)

    body = _col(body_rows, gap=12, padding=f"16px {pad}px")
    footer = _footer_with_palette(palette, footer_text)
    root = _col([header, body, footer], gap=0, backgroundColor="#FAF6FF", height="100%")
    return root, 800, h


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 2: EDITORIAL — clean white, hero large, quote description
# ═══════════════════════════════════════════════════════════════════════════════

def build_editorial(slots: list, header_text: str, footer_text: str,
                    palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    all_items = hero + main
    hero_slot = all_items[0] if all_items else (small[0] if small else None)
    rest = (all_items[1:] if hero_slot in all_items else all_items) + small

    rows: list = []
    # Minimal header
    rows.append(
        _row([
            _text("LOOK OF THE DAY", 11, "#BBB", letterSpacing=4),
        ], justifyContent="center", padding="28px 0 8px"),
    )
    # Hero card (55% of space)
    if hero_slot:
        rows.append(
            _card(hero_slot, "100%", "380px", radius=20, shadow=False,
                  bg="#FAFAFA", img_w="85%", img_h="72%", label_size=16),
        )
    # Description line
    rows.append(
        _text(header_text or "Образ дня", 16, "#555",
              padding="8px 32px", textAlign="center", lineHeight="1.5"),
    )
    # Strip of small items
    if rest:
        strip = [_card(s, f"{100 // max(len(rest[:4]), 1)}%", "140px",
                       radius=12, label_size=11, img_w="60%", img_h="55%")
                 for s in rest[:4]]
        rows.append(_row(strip, gap=8, padding="0 16px"))
    # Footer
    rows.append(
        _row([
            _text(footer_text, 12, "#BBB"),
        ], justifyContent="center", padding="16px 0 20px"),
    )

    h = 28 + 380 + 50 + (150 if rest else 0) + 56 + 40
    root = _col(rows, gap=8, backgroundColor="#FFFFFF", height="100%")
    return root, 800, max(h, 500)


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 3: STORY CARD — gradient bg, translucent cards, name prominent
# ═══════════════════════════════════════════════════════════════════════════════

def build_story_card(slots: list, header_text: str, footer_text: str,
                     palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    grad_from = palette[0] if palette else "#6C5B7B"
    grad_to = palette[1] if len(palette) > 1 else "#C06C84"

    rows: list = []
    # Name + subtitle
    rows.append(_col([
        _text(header_text or "Образ дня", 26, "#fff", fontWeight="bold"),
        _text("LOOK OF THE DAY", 11, "rgba(255,255,255,0.6)", letterSpacing=3, marginTop=4),
    ], padding="32px 28px 12px", gap=0))

    # Cards with translucent bg
    for s in (hero + main)[:3]:
        rows.append(
            _card(s, "100%", "200px", radius=20,
                  bg="rgba(255,255,255,0.25)", shadow=False,
                  img_w="70%", img_h="60%", label_size=14, ph_opacity="0.6"),
        )

    # Small strip
    if small:
        strip = [_card(s, f"{100 // max(len(small), 1)}%", "130px",
                       radius=16, bg="rgba(255,255,255,0.2)", shadow=False,
                       label_size=11, ph_opacity="0.5")
                 for s in small[:3]]
        rows.append(_row(strip, gap=8))

    # Footer
    rows.append(
        _text(footer_text, 12, "rgba(255,255,255,0.6)",
              padding="12px 0", textAlign="center"),
    )

    n_cards = min(len(hero + main), 3)
    h = 80 + n_cards * 212 + (142 if small else 0) + 50
    body = _col(rows, gap=10, padding="0 24px 20px")
    root = {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "flexDirection": "column",
                "width": "100%",
                "height": "100%",
                "backgroundImage": f"linear-gradient(135deg, {grad_from}, {grad_to})",
                "fontFamily": "DejaVu",
            },
            "children": [body],
        },
    }
    return root, 800, max(h, 500)


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 4: POLAROID — warm bg, white-framed cards with slight tilt feel
# ═══════════════════════════════════════════════════════════════════════════════

def build_polaroid(slots: list, header_text: str, footer_text: str,
                   palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    all_slots = hero + main + small

    rows: list = []
    rows.append(_text(header_text or "Образ дня", 20, "#5A4A3A",
                      fontWeight="bold", padding="28px 24px 8px"))

    # Each item as a "polaroid" — white border, shadow, label below
    pol_cards: list[dict] = []
    for s in all_slots[:5]:
        img = _get_img_el(s, "85%", "70%", "0.4")
        label = _get_slot_label(s)
        inner: list = []
        if img:
            inner.append(img)
        inner.append(_text(label, 12, "#7A6A5A", marginTop=8))
        pol_cards.append({
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "flexDirection": "column",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "backgroundColor": "#fff",
                    "borderRadius": 4,
                    "padding": "16px 12px 12px",
                    "boxShadow": "0 4px 16px rgba(0,0,0,0.1)",
                    "width": "45%",
                    "height": "220px",
                },
                "children": inner,
            },
        })

    # Layout: 2-col rows
    for i in range(0, len(pol_cards), 2):
        chunk = pol_cards[i:i+2]
        rows.append(_row(chunk, gap=16, justifyContent="center"))

    rows.append(_text(footer_text, 12, "#B0A090", padding="16px 0", textAlign="center"))

    n_rows = (len(pol_cards) + 1) // 2
    h = 60 + n_rows * 240 + 50
    root = _col(rows, gap=14, backgroundColor="#F5F0EB", height="100%",
                padding="0 20px 20px")
    return root, 800, max(h, 500)


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 5: PALETTE FIRST — color blocks prominent, items below
# ═══════════════════════════════════════════════════════════════════════════════

def build_palette_first(slots: list, header_text: str, footer_text: str,
                        palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)
    all_slots = hero + main + small

    rows: list = []
    rows.append(_text("ПАЛИТРА ДНЯ", 12, "#999", letterSpacing=4,
                      padding="28px 0 4px", textAlign="center"))
    rows.append(_text(header_text or "Образ дня", 18, "#333",
                      fontWeight="bold", textAlign="center"))

    # Large color blocks
    if palette:
        blocks = []
        for i, hx in enumerate(palette[:4]):
            matching = [s for s in all_slots if _color_hex(s.get("item_color", "")) == hx]
            slot = matching[0] if matching else None
            block_children: list = [
                {"type": "div", "props": {"style": {
                    "display": "flex", "width": 50, "height": 50,
                    "borderRadius": "50%", "backgroundColor": hx,
                    "border": "3px solid rgba(255,255,255,0.8)",
                    "boxShadow": "0 2px 8px rgba(0,0,0,0.1)",
                }}},
            ]
            if slot:
                img = _get_img_el(slot, "70%", "50%", "0.5")
                if img:
                    block_children.append(img)
                block_children.append(_text(_get_slot_label(slot), 11, "#666", marginTop=4))
            blocks.append(_col(block_children, gap=6, alignItems="center",
                               width=f"{100 // max(len(palette[:4]), 1)}%",
                               height="200px", justifyContent="center"))
        rows.append(_row(blocks, gap=8, padding="12px 16px"))

    # Remaining items not in palette
    shown_slots = set()
    for hx in palette[:4]:
        for s in all_slots:
            if _color_hex(s.get("item_color", "")) == hx and id(s) not in shown_slots:
                shown_slots.add(id(s))
                break
    remaining = [s for s in all_slots if id(s) not in shown_slots]
    if remaining:
        strip = [_card(s, f"{100 // max(len(remaining[:3]), 1)}%", "140px",
                       radius=12, label_size=11) for s in remaining[:3]]
        rows.append(_row(strip, gap=8, padding="0 16px"))

    rows.append(_footer_with_palette(palette, footer_text))

    h = 60 + 30 + (220 if palette else 0) + (152 if remaining else 0) + 50 + 40
    root = _col(rows, gap=8, backgroundColor="#FAFAF8", height="100%")
    return root, 800, max(h, 450)


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE 6: PRO STYLIST — clean flat lay, minimal decoration
# ═══════════════════════════════════════════════════════════════════════════════

def build_pro_stylist(slots: list, header_text: str, footer_text: str,
                      palette: list[str]) -> tuple[dict, int, int]:
    hero, main, small = _split_zones(slots)

    rows: list = []
    rows.append(_row([
        _text(header_text or "Образ дня", 16, "#555", fontWeight="bold"),
    ], padding="24px 28px 0", justifyContent="space-between"))
    # Thin divider
    rows.append({"type": "div", "props": {"style": {
        "display": "flex", "width": "100%", "height": 1,
        "backgroundColor": "#E8E4EC", "margin": "4px 0",
    }}})

    # Hero item — large, minimal border
    if hero:
        rows.append(
            _card(hero[0], "100%", "320px", radius=8, shadow=False,
                  bg="#F8F8F8", img_w="80%", img_h="72%", label_size=15),
        )

    # Main items — offset layout (first slightly larger)
    if main:
        op = [s for s in main if s.get("slot") == "one_piece"]
        tops = [s for s in main if s.get("slot") in ("top", "removable_layer")]
        bots = [s for s in main if s.get("slot") == "bottom"]
        if op:
            rows.append(_card(op[0], "100%", "240px", radius=8, shadow=False, bg="#F8F8F8"))
        else:
            cards = []
            if tops:
                cards.append(_card(tops[0], "55%", "240px", radius=8, shadow=False, bg="#F8F8F8"))
            if bots:
                cards.append(_card(bots[0], "45%", "240px", radius=8, shadow=False, bg="#F8F8F8"))
            if cards:
                rows.append(_row(cards, gap=10))

    # Small items — tight strip
    if small:
        strip = [_card(s, f"{100 // max(len(small), 1)}%", "130px",
                       radius=6, shadow=False, bg="#F8F8F8",
                       label_size=11, img_w="60%", img_h="55%")
                 for s in small]
        rows.append(_row(strip, gap=8))

    # Thin divider + footer
    rows.append({"type": "div", "props": {"style": {
        "display": "flex", "width": "100%", "height": 1,
        "backgroundColor": "#E8E4EC", "margin": "4px 0",
    }}})
    rows.append(_text(footer_text, 12, "#BBB", padding="4px 0 20px", textAlign="center"))

    h = 50 + 4
    if hero: h += 330
    if main: h += 250
    if small: h += 140
    h += 40
    root = _col(rows, gap=8, backgroundColor="#FFFFFF", height="100%", padding="0 24px")
    return root, 800, max(h, 450)


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

BUILDERS = {
    "magazine": build_magazine,
    "editorial": build_editorial,
    "story_card": build_story_card,
    "polaroid": build_polaroid,
    "palette_first": build_palette_first,
    "pro_stylist": build_pro_stylist,
}
