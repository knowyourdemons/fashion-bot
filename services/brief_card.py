"""
Brief card system — three card states + two color themes.

Card states:
  - Weather card (0 real photos): weather + advice + CTA
  - Hybrid card (1-7 real photos): weather strip + items grid + placeholders
  - Full card (8+ real photos): flat lay with all items

Color themes:
  - "mom" (mom_girl/mom_boy): warm pink palette
  - "woman" (no_kids/pregnant): cool blue palette

Main entry: build_brief_card(user, child, outfit, weather, outfit_slots) -> bytes
"""
from __future__ import annotations

import structlog

from services.image_builder import (
    _render_satori,
    _img_to_data_uri,
    _auto_trim,
    _load_silhouette_bytes,
)
from services.collage_styles import (
    collect_palette,
    format_collage_label,
    _get_placeholder_label,
)
from services.weather_card import season_palette, _sign

logger = structlog.get_logger()

# ── Color themes ─────────────────────────────────────────────────────────────

THEMES = {
    "mom": {
        "bg_start": "#F5EDE8",
        "bg_end": "#F0E8E4",
        "text": "#5B3A4A",
        "muted": "#B09888",
        "accent": "#D080A0",
    },
    "woman": {
        "bg_start": "#E8EDF5",
        "bg_end": "#E4E8F0",
        "text": "#3A4A5B",
        "muted": "#8898A8",
        "accent": "#7090C0",
    },
}

_DAY_NAMES = {
    0: "понедельник", 1: "вторник", 2: "среда",
    3: "четверг", 4: "пятница", 5: "суббота", 6: "воскресенье",
}

_MONTH_NAMES = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


# ── Segment detection ────────────────────────────────────────────────────────

def _get_segment(user) -> str:
    """Determine segment from user: 'mom' or 'woman'."""
    seg = getattr(user, "segment", None) or ""
    if seg in ("mom_girl", "mom_boy"):
        return "mom"
    return "woman"


def _get_theme(segment: str) -> dict:
    return THEMES.get(segment, THEMES["mom"])


# ── Count real photos ────────────────────────────────────────────────────────

def _count_real_photos(outfit_slots: list[dict]) -> int:
    """Count slots with actual photo data (photo_url or photo_id, not placeholders)."""
    count = 0
    for s in outfit_slots:
        if not s.get("has_item"):
            continue
        has_photo = (
            s.get("photo_url")
            or s.get("photo_id")
            or s.get("_photo_bytes")
        )
        if has_photo:
            count += 1
    return count


# ── Satori element helpers ───────────────────────────────────────────────────

def _div(children, **style):
    """Shorthand for a flex div."""
    s = {"display": "flex", **style}
    return {"type": "div", "props": {"style": s, "children": children}}


def _text(content: str, size: int = 14, color: str = "#333", **extra):
    style = {
        "display": "flex",
        "fontFamily": "Nunito, DejaVu",
        "fontSize": size,
        "color": color,
        **extra,
    }
    return {"type": "div", "props": {"style": style, "children": content}}


def _row(children, gap=8, **extra):
    return _div(children, flexDirection="row", gap=gap, width="100%", **extra)


def _col(children, gap=8, **extra):
    return _div(children, flexDirection="column", gap=gap, width="100%", **extra)


def _color_dot(hex_color: str, size: int = 10):
    return _div(
        [],
        width=size, height=size,
        borderRadius="50%",
        backgroundColor=hex_color,
        border="1px solid rgba(0,0,0,0.08)",
        flexShrink=0,
    )


def _progress_bar(current: int, total: int, accent: str, muted: str) -> dict:
    """Progress bar: filled portion + remaining."""
    pct = min(100, max(0, int(current / max(total, 1) * 100)))
    return _row(
        [
            _div([], height=6, borderRadius=3, backgroundColor=accent,
                 width=f"{pct}%"),
            _div([], height=6, borderRadius=3, backgroundColor=muted,
                 width=f"{100 - pct}%", opacity=0.3),
        ],
        gap=0,
    )


def _photo_card(slot: dict, w: int, h: int, theme: dict) -> dict:
    """Single item card with photo or placeholder."""
    is_real = slot.get("has_item") and slot.get("_photo_bytes")
    label = ""
    if slot.get("has_item"):
        label = format_collage_label(
            slot.get("slot", "top"),
            slot.get("item_type", ""),
            slot.get("item_color", ""),
        )
    else:
        label = slot.get("label") or _get_placeholder_label(
            slot.get("slot", "top"),
            slot.get("gender", "girl"),
        )

    children = []
    if is_real:
        photo = _auto_trim(slot["_photo_bytes"])
        children.append({
            "type": "img",
            "props": {
                "src": _img_to_data_uri(photo),
                "width": "80%",
                "height": "70%",
                "style": {"objectFit": "contain"},
            },
        })
        bg = "rgba(255,255,255,0.9)"
    else:
        # Placeholder: pastel background + silhouette
        _SLOT_PASTELS = {
            "outerwear": "#C8D8E8", "top": "#FFD0D8", "bottom": "#C8D0F0",
            "one_piece": "#E0D0F0", "footwear": "#D0E0F0", "hat": "#D0E8D0",
            "scarf": "#F0DCC8", "gloves": "#D0D8F0", "tights": "#E8D8E8",
            "socks": "#E8D8E8", "removable_layer": "#D8E0D0",
        }
        bg = _SLOT_PASTELS.get(slot.get("slot", "top"), "#E0D8D0")
        sil = _load_silhouette_bytes(
            slot.get("slot", "top"),
            slot.get("gender", "girl"),
            slot.get("adult", False),
        )
        if sil:
            children.append({
                "type": "img",
                "props": {
                    "src": _img_to_data_uri(sil),
                    "width": "50%", "height": "50%",
                    "style": {"objectFit": "contain", "opacity": "0.35"},
                },
            })

    # Label at bottom
    label_el = _text(
        label, 11,
        theme["text"] if is_real else theme["muted"],
        textAlign="center",
        width="100%",
        justifyContent="center",
    )

    return _div(
        [
            _div(children,
                 flexDirection="column",
                 alignItems="center",
                 justifyContent="center",
                 flex=1, width="100%"),
            label_el,
        ],
        flexDirection="column",
        alignItems="center",
        width=w, height=h,
        backgroundColor=bg,
        borderRadius=10,
        overflow="hidden",
        padding="6px 4px",
    )


# ══════════════════════════════════════════════════════════════════════════════
# WEATHER CARD (0 photos)
# ══════════════════════════════════════════════════════════════════════════════

def _build_weather_card(
    user, child, weather: dict, segment: str, theme: dict,
    advice_text: str = "",
) -> tuple[dict, int, int]:
    """Weather-only card: weather + palette + advice + CTA. 440x620."""
    from datetime import date as _date
    W, H = 440, 620

    today = _date.today()
    day_name = _DAY_NAMES.get(today.weekday(), "")
    month = _MONTH_NAMES.get(today.month, "")

    child_name = getattr(child, "name", "") if child else ""
    user_name = getattr(user, "name", "") if user else ""
    name = child_name or user_name or ""
    context = "садик" if child and today.weekday() < 5 else ("прогулка" if child else "офис")

    temp_m = weather.get("temp_morning", 10.0)
    temp_d = weather.get("temp_day")
    temp_e = weather.get("temp_evening", temp_m)
    precip = weather.get("precip_max", 0)

    # ── Header ──
    date_str = f"{day_name}, {today.day} {month}"
    header = _col(
        [
            _text("Доброе утро!", 22, theme["text"], fontWeight=700),
            _text(
                f"{name} . {context} . {date_str}",
                13, theme["muted"],
            ),
        ],
        gap=4, padding="24px 24px 12px",
    )

    # ── Weather box ──
    weather_rows = []
    for label, temp_val, key in [
        ("Утро", temp_m, "temp_morning"),
        ("День", temp_d, "temp_day"),
        ("Вечер", temp_e, "temp_evening"),
    ]:
        if temp_val is None:
            continue
        s = _sign(temp_val)
        # Red color for evening if cold/rain
        is_danger = (
            key == "temp_evening"
            and temp_m is not None
            and temp_val < temp_m - 3
        )
        temp_color = "#C05050" if is_danger else theme["text"]
        weather_rows.append(
            _row(
                [
                    _text(label, 14, theme["muted"], width=60),
                    _text(f"{s}{temp_val:.0f}°C", 16, temp_color, fontWeight=600),
                ],
                gap=12, alignItems="center",
            )
        )

    # Precipitation
    if precip >= 70:
        precip_label = "Dождь вероятен"
    elif precip >= 40:
        precip_label = "Возможен дождь"
    else:
        precip_label = "Без осадков"

    weather_box = _div(
        [
            _col(weather_rows, gap=6),
            _text(precip_label, 13, theme["muted"], marginTop=8),
        ],
        flexDirection="column",
        backgroundColor="rgba(255,255,255,0.6)",
        borderRadius=14,
        padding="16px 20px",
        margin="0 20px",
    )

    # ── Season palette ──
    palette = season_palette(temp_m or 10)
    palette_circles = []
    for p in palette:
        palette_circles.append(
            _col(
                [
                    _div([], width=44, height=44, borderRadius=8,
                         backgroundColor=p["hex"],
                         border="1px solid rgba(0,0,0,0.06)"),
                    _text(p["name"], 10, theme["muted"], textAlign="center",
                          justifyContent="center", width=44),
                ],
                gap=4, alignItems="center",
            )
        )
    palette_section = _col(
        [
            _text("Рекомендуемая палитра:", 13, theme["muted"]),
            _row(palette_circles, gap=14, justifyContent="center"),
        ],
        gap=8, padding="4px 24px",
    )

    # ── Advice (Kassi comment) ──
    advice = advice_text or "Хорошего дня!"
    advice_section = _div(
        [
            _text(advice, 13, theme["text"], lineHeight=1.5),
            _text("-- Касси", 11, theme["muted"], marginTop=4),
        ],
        flexDirection="column",
        backgroundColor="rgba(255,255,255,0.5)",
        borderRadius=12,
        padding="14px 18px",
        margin="0 20px",
    )

    # ── CTA ──
    items_count = 0  # 0 photos by definition
    cta_text = "Сфоткай вещи -- соберу образ!"
    cta = _div(
        [_text(cta_text, 13, theme["accent"], fontWeight=600, textAlign="center",
               justifyContent="center", width="100%")],
        flexDirection="row",
        justifyContent="center",
        padding="10px 20px",
    )

    # ── Footer ──
    footer = _text(
        "Касси . твой личный стилист",
        11, theme["muted"],
        padding="0 24px 16px", opacity=0.6,
    )

    root = _col(
        [header, weather_box, palette_section, advice_section, cta, footer],
        gap=12,
        backgroundImage=f"linear-gradient(to bottom, {theme['bg_start']}, {theme['bg_end']})",
        borderRadius=20,
        height="100%",
    )
    return root, W, H


# ══════════════════════════════════════════════════════════════════════════════
# HYBRID CARD (1-7 photos)
# ══════════════════════════════════════════════════════════════════════════════

def _missing_icon(slot_name: str, emoji: str, theme: dict) -> dict:
    """Small icon + label for missing item in 'ДОБАВЬ:' section."""
    _SLOT_ICON_PASTELS = {
        "outerwear": "#C8D8E8", "top": "#FFD0D8", "bottom": "#C8D0F0",
        "one_piece": "#E0D0F0", "footwear": "#D0E0F0", "hat": "#D0E8D0",
        "scarf": "#F0DCC8", "gloves": "#D0D8F0", "removable_layer": "#D8E0D0",
    }
    _SLOT_EMOJI = {
        "outerwear": "Куртка", "top": "Верх", "bottom": "Низ",
        "one_piece": "Платье", "footwear": "Обувь", "hat": "Шапка",
        "scarf": "Шарф", "gloves": "Перчатки", "removable_layer": "Кардиган",
    }
    bg = _SLOT_ICON_PASTELS.get(slot_name, "#E0D8D0")
    label = _SLOT_EMOJI.get(slot_name, slot_name)

    sil = _load_silhouette_bytes(slot_name, "girl", False)
    icon_children = []
    if sil:
        icon_children.append({
            "type": "img",
            "props": {
                "src": _img_to_data_uri(sil),
                "width": "60%", "height": "60%",
                "style": {"objectFit": "contain", "opacity": "0.5"},
            },
        })

    return _col(
        [
            _div(
                icon_children,
                width=52, height=44,
                backgroundColor=bg,
                borderRadius=8,
                alignItems="center",
                justifyContent="center",
            ),
            _text(label, 10, theme["muted"], textAlign="center",
                  justifyContent="center", width=52),
        ],
        gap=3, alignItems="center",
    )


def _build_hybrid_card(
    user, child, outfit: dict, weather: dict,
    outfit_slots: list[dict], segment: str, theme: dict,
    advice_text: str = "",
    real_photo_count: int = 0,
) -> tuple[dict, int, int]:
    """Hybrid card: real photos large + small icons for missing items. 440x auto."""
    W = 440
    from datetime import date as _date

    today = _date.today()
    day_name = _DAY_NAMES.get(today.weekday(), "")
    month = _MONTH_NAMES.get(today.month, "")

    child_name = getattr(child, "name", "") if child else ""
    user_name = getattr(user, "name", "") if user else ""
    name = child_name or user_name or ""
    context = "садик" if child and today.weekday() < 5 else ("прогулка" if child else "")

    # ── Header: date + context + compact weather ──
    temp_m = weather.get("temp_morning")
    temp_d = weather.get("temp_day")
    temp_e = weather.get("temp_evening")

    weather_parts = []
    for label, t in [("утро", temp_m), ("день", temp_d), ("вечер", temp_e)]:
        if t is not None:
            s = _sign(t)
            weather_parts.append(f"{s}{t:.0f}°")
    weather_str = " / ".join(weather_parts) if weather_parts else ""

    date_line = f"{day_name[:2].upper()}, {today.day} {_MONTH_NAMES.get(today.month, '')[:3].upper()}"
    header = _row(
        [
            _col(
                [
                    _text(date_line, 11, theme["muted"]),
                    _text(name, 20, theme["text"], fontWeight=700),
                ],
                gap=2,
            ),
            _text(weather_str, 13, theme["muted"], flexShrink=0) if weather_str else _div([]),
        ],
        justifyContent="space-between",
        alignItems="center",
        padding="18px 20px 8px",
    )

    # ── Real photo cards only (NO placeholders as cards) ──
    real_slots = [s for s in outfit_slots if s.get("has_item") and s.get("_photo_bytes")]
    placeholder_slots = [s for s in outfit_slots
                         if not s.get("has_item")
                         and s.get("slot") not in ("underwear", "tights", "socks", "base_layer")]

    card_rows = []
    n_real = len(real_slots)
    if n_real == 1:
        # Single large card
        card_rows.append(
            _row([_photo_card(real_slots[0], 380, 160, theme)], justifyContent="center")
        )
    elif n_real == 2:
        card_rows.append(
            _row(
                [_photo_card(s, 185, 140, theme) for s in real_slots],
                gap=8, justifyContent="center",
            )
        )
    else:
        # 3+ photos: first row 2 large, rest smaller
        for i in range(0, n_real, 2):
            pair = real_slots[i:i+2]
            h_card = 140 if i == 0 else 110
            w_card = 185 if len(pair) == 2 else 380
            row_cards = [_photo_card(s, w_card if len(pair) == 1 else 185, h_card, theme) for s in pair]
            card_rows.append(_row(row_cards, gap=8, justifyContent="center"))

    items_section = _col(card_rows, gap=8, padding="0 16px") if card_rows else _div([])

    # ── "ДОБАВЬ:" section with small icons (no placeholder cards) ──
    missing_section = None
    if placeholder_slots:
        icons = []
        for ps in placeholder_slots[:6]:
            slot_key = ps.get("slot", "top")
            icons.append(_missing_icon(slot_key, "", theme))

        missing_section = _col(
            [
                _text("ДОБАВЬ:", 11, theme["muted"], fontWeight=600),
                _row(icons, gap=10, justifyContent="center", flexWrap="wrap"),
            ],
            gap=6, padding="4px 20px",
        )

    # ── Underwear line (compact) ──
    underwear_line = None
    under_items = []
    if outfit:
        if outfit.get("underwear_text"):
            under_items.append(outfit["underwear_text"])
        for item in outfit.get("underwear_items", []):
            n = (getattr(item, "type", "") or "").split()[0].lower()
            if n:
                under_items.append(n)
        leg = outfit.get("tights") or outfit.get("socks")
        if leg and hasattr(leg, "type"):
            under_items.append(getattr(leg, "type", "колготки"))
    if under_items:
        underwear_line = _text(
            " . ".join(under_items),
            11, theme["muted"],
            textAlign="center", justifyContent="center", width="100%",
            padding="0 20px",
        )

    # ── Kassi comment ──
    comment = advice_text or ""
    comment_section = None
    if comment:
        comment_section = _div(
            [
                _text(comment, 12, theme["text"], lineHeight=1.4, fontStyle="italic"),
                _text("-- Касси", 10, theme["muted"]),
            ],
            flexDirection="column",
            gap=4,
            padding="8px 20px",
        )

    # ── Progress bar ──
    threshold = 8 if segment == "mom" else 12
    progress_section = None
    if real_photo_count > 0:
        remaining = max(0, threshold - real_photo_count)
        first_missing = ""
        for ps in placeholder_slots[:1]:
            first_missing = ps.get("label") or _get_placeholder_label(
                ps.get("slot", "top"), ps.get("gender", "girl"))

        progress_label = f"{real_photo_count}/{threshold}"
        if remaining > 0 and first_missing:
            progress_label += f" . Сфоткай {first_missing.lower()}!"
        elif remaining > 0:
            progress_label += f" . Ещё {remaining} -- полный образ!"

        progress_section = _col(
            [
                _progress_bar(real_photo_count, threshold, theme["accent"], theme["muted"]),
                _text(progress_label, 11, theme["muted"], textAlign="center",
                      justifyContent="center", width="100%"),
            ],
            gap=4, padding="4px 20px 12px",
        )

    # ── Assemble ──
    parts = [header]
    parts.append(items_section)
    if missing_section:
        parts.append(missing_section)
    if underwear_line:
        parts.append(underwear_line)
    if comment_section:
        parts.append(comment_section)
    if progress_section:
        parts.append(progress_section)

    # Height estimation
    h = 60  # header
    if n_real == 1:
        h += 172
    elif n_real == 2:
        h += 152
    else:
        n_photo_rows = (n_real + 1) // 2
        h += 152 + max(0, n_photo_rows - 1) * 122
    if missing_section:
        h += 75
    if underwear_line:
        h += 25
    if comment_section:
        h += max(40, len(comment) // 2)
    if progress_section:
        h += 40
    h += 20
    h = max(h, 350)

    root = _col(
        parts, gap=8,
        backgroundImage=f"linear-gradient(to bottom, {theme['bg_start']}, {theme['bg_end']})",
        borderRadius=20,
        height="100%",
    )
    return root, W, h


# ══════════════════════════════════════════════════════════════════════════════
# FULL CARD (8+ photos)
# ══════════════════════════════════════════════════════════════════════════════

def _build_full_card(
    user, child, outfit: dict, weather: dict,
    outfit_slots: list[dict], segment: str, theme: dict,
    advice_text: str = "",
) -> tuple[dict, int, int]:
    """Full flat lay card: all items with photos. 440x auto."""
    W = 440
    from datetime import date as _date

    today = _date.today()
    day_name = _DAY_NAMES.get(today.weekday(), "")
    month = _MONTH_NAMES.get(today.month, "")

    child_name = getattr(child, "name", "") if child else ""
    user_name = getattr(user, "name", "") if user else ""
    name = child_name or user_name or ""
    context = "садик" if child and today.weekday() < 5 else ("прогулка" if child else "")

    # ── Header with compact weather ──
    temp_m = weather.get("temp_morning")
    temp_d = weather.get("temp_day")
    temp_e = weather.get("temp_evening")

    weather_parts = []
    for label, t in [("утро", temp_m), ("день", temp_d), ("вечер", temp_e)]:
        if t is not None:
            s = _sign(t)
            weather_parts.append(f"{s}{t:.0f}°")
    weather_str = " / ".join(weather_parts) if weather_parts else ""

    # Palette from outfit colors
    palette_colors = collect_palette(
        outfit_slots,
        colortype=getattr(child, "colortype", "") if child else
                  getattr(user, "colortype", "") or "",
    )

    header = _row(
        [
            _col(
                [
                    _text(f"{name}, {context}" if context else name,
                          16, theme["text"], fontWeight=700),
                    _text(f"{day_name}, {today.day} {month}",
                          11, theme["muted"]),
                ],
                gap=2,
            ),
            _col(
                [
                    _text(weather_str, 12, theme["muted"]) if weather_str else _div([]),
                    _row(
                        [_color_dot(c, 10) for c in palette_colors[:3]],
                        gap=4, justifyContent="flex-end",
                    ) if palette_colors else _div([]),
                ],
                gap=4, alignItems="flex-end", flexShrink=0,
            ),
        ],
        justifyContent="space-between",
        alignItems="flex-start",
        padding="18px 20px 8px",
    )

    # ── Items layout: hierarchy by category ──
    # Outerwear large, top/bottom medium, accessories small
    outer_slots = [s for s in outfit_slots if s.get("slot") == "outerwear" and s.get("has_item")]
    main_slots = [s for s in outfit_slots
                  if s.get("slot") in ("top", "removable_layer", "bottom", "one_piece")
                  and s.get("has_item")]
    small_slots = [s for s in outfit_slots
                   if s.get("slot") in ("footwear", "hat", "scarf", "gloves")
                   and s.get("has_item")]

    card_rows = []

    # Outerwear: large, centered
    if outer_slots:
        for s in outer_slots:
            card_rows.append(
                _row(
                    [_photo_card(s, 380, 150, theme)],
                    justifyContent="center",
                )
            )

    # Top + bottom: 2-column
    if main_slots:
        for i in range(0, len(main_slots), 2):
            pair = main_slots[i:i+2]
            row_cards = [_photo_card(s, 185, 130, theme) for s in pair]
            card_rows.append(_row(row_cards, gap=8, justifyContent="center"))

    # Small items: compact row
    if small_slots:
        sm_cards = [_photo_card(s, 90, 80, theme) for s in small_slots]
        card_rows.append(_row(sm_cards, gap=6, justifyContent="center"))

    items_section = _col(card_rows, gap=8, padding="0 16px")

    # ── Underwear line ──
    underwear_line = None
    under_items = []
    if outfit:
        if outfit.get("underwear_text"):
            under_items.append(outfit["underwear_text"])
        for item in outfit.get("underwear_items", []):
            n = (getattr(item, "type", "") or "").split()[0].lower()
            if n:
                under_items.append(n)
        leg = outfit.get("tights") or outfit.get("socks")
        if leg and hasattr(leg, "type"):
            under_items.append(getattr(leg, "type", "колготки"))
    if under_items:
        underwear_line = _text(
            " . ".join(under_items),
            11, theme["muted"],
            textAlign="center", justifyContent="center", width="100%",
            padding="0 20px",
        )

    # ── Kassi comment (stylistic) ──
    comment_section = None
    if advice_text:
        comment_section = _div(
            [
                _text(advice_text, 13, theme["text"], lineHeight=1.4, fontStyle="italic"),
                _text("-- Касси", 10, theme["muted"]),
            ],
            flexDirection="column",
            gap=4,
            padding="8px 20px",
        )

    # ── Assemble ──
    parts = [header, items_section]
    if underwear_line:
        parts.append(underwear_line)
    if comment_section:
        parts.append(comment_section)

    # Footer
    parts.append(
        _text("Касси . твой личный стилист", 10, theme["muted"],
              padding="0 20px 14px", opacity=0.5)
    )

    # Height estimation
    h = 60  # header
    if outer_slots:
        h += 160
    n_main_rows = (len(main_slots) + 1) // 2
    h += n_main_rows * 142
    if small_slots:
        h += 92
    if underwear_line:
        h += 25
    if comment_section:
        h += max(40, len(advice_text) // 2)
    h += 30
    h = max(h, 400)

    root = _col(
        parts, gap=8,
        backgroundImage=f"linear-gradient(to bottom, {theme['bg_start']}, {theme['bg_end']})",
        borderRadius=20,
        height="100%",
    )
    return root, W, h


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def build_brief_card(
    user,
    child,
    outfit: dict,
    weather: dict,
    outfit_slots: list[dict],
    advice_text: str = "",
) -> bytes | None:
    """
    Build morning brief card as PNG bytes.

    Chooses card type based on real photo count:
      0 photos  -> weather card
      1-7       -> hybrid card
      8+        -> full card

    Returns PNG bytes or None on failure.
    Falls back to None (caller should use PIL fallback).
    """
    segment = _get_segment(user)
    theme = _get_theme(segment)
    real_photos = _count_real_photos(outfit_slots)

    logger.info(
        "brief_card.build",
        segment=segment,
        real_photos=real_photos,
        total_slots=len(outfit_slots),
    )

    try:
        if real_photos == 0:
            element, w, h = _build_weather_card(
                user, child, weather, segment, theme,
                advice_text=advice_text,
            )
        elif real_photos < 8:
            element, w, h = _build_hybrid_card(
                user, child, outfit, weather, outfit_slots,
                segment, theme,
                advice_text=advice_text,
                real_photo_count=real_photos,
            )
        else:
            element, w, h = _build_full_card(
                user, child, outfit, weather, outfit_slots,
                segment, theme,
                advice_text=advice_text,
            )

        # Render via Satori
        png_bytes = await _render_satori(element, w, h)
        if png_bytes:
            logger.info("brief_card.rendered", size=len(png_bytes), card_type=(
                "weather" if real_photos == 0 else
                "hybrid" if real_photos < 8 else "full"
            ))
            return png_bytes

        logger.warning("brief_card.satori_failed")
        return None

    except Exception as e:
        logger.warning("brief_card.build_failed", error=str(e), exc_info=True)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# BUTTON LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def get_brief_buttons(
    segment: str,
    real_photo_count: int,
    brief_id: str,
    first_missing_slot: str = "",
) -> dict:
    """
    Return inline_keyboard dict for the brief card.

    Rules:
      0 photos:           [Сфоткать] [Потом]
      1-7 photos mom:     [Надели] [Переодень] + specific missing item CTA
      8+ photos mom:      [Надели] [Переодень] [Переслать]
      woman with outfit:  [Нравится] [Другой вариант] [Stories]
      woman advice only:  [Спасибо] [Ещё совет]
    """
    if real_photo_count == 0:
        return {
            "inline_keyboard": [[
                {"text": "Сфоткать", "callback_data": "add_items_hint"},
                {"text": "Потом", "callback_data": f"brief_feedback:later:{brief_id}"},
            ]]
        }

    if segment == "mom":
        if real_photo_count >= 8:
            return {
                "inline_keyboard": [
                    [
                        {"text": "Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
                        {"text": "Переодень", "callback_data": f"reroll:{brief_id}"},
                    ],
                    [
                        {"text": "Переслать", "callback_data": f"share:{brief_id}"},
                    ],
                ]
            }
        else:
            # 1-7 photos mom
            rows = [[
                {"text": "Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "Переодень", "callback_data": f"reroll:{brief_id}"},
            ]]
            if first_missing_slot:
                rows[0].append(
                    {"text": f"Сфоткай {first_missing_slot}",
                     "callback_data": "add_items_hint"},
                )
            return {"inline_keyboard": rows}

    # segment == "woman"
    if real_photo_count >= 8:
        return {
            "inline_keyboard": [
                [
                    {"text": "Нравится", "callback_data": f"brief_feedback:up:{brief_id}"},
                    {"text": "Другой вариант", "callback_data": f"reroll:{brief_id}"},
                ],
                [
                    {"text": "Stories", "callback_data": f"share:{brief_id}"},
                ],
            ]
        }
    elif real_photo_count > 0:
        return {
            "inline_keyboard": [[
                {"text": "Нравится", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "Другой вариант", "callback_data": f"reroll:{brief_id}"},
            ]]
        }
    else:
        return {
            "inline_keyboard": [[
                {"text": "Спасибо", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "Ещё совет", "callback_data": "reroll_advice"},
            ]]
        }
