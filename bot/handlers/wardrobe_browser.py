"""
Wardrobe browser — visual navigation with Satori 3x3 grid.

Callbacks:
  w:ov              — overview (category counts + season filter)
  w:sz:{season}     — filter by season
  w:cat:{cat}:{p}   — category grid page (Satori 3x3)
  w:it:{short_id}   — item detail card
  w:del:{short_id}  — delete confirmation
  w:dly:{short_id}  — delete confirmed (soft-delete)
"""
import asyncio
import base64
import io
import math
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional

import httpx
import sentry_sdk
import structlog
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import settings
from db.base import AsyncReadSession, AsyncWriteSession
from db.crud.wardrobe import get_owner_items, get_by_id, soft_delete

logger = structlog.get_logger()

_GRID_SIZE = 9  # 3x3

_CAT_EMOJI = {
    "outerwear": "🧥", "top": "👚", "bottom": "👖",
    "one_piece": "👗", "footwear": "👟", "base_layer": "🧦",
    "accessory": "🎀", "underwear": "👙", "sportswear": "🏃",
    "special": "✨", "home_beach": "🏠", "pregnant_specific": "🤰",
}
_CAT_NAME = {
    "outerwear": "Верхняя", "top": "Верх", "bottom": "Низ",
    "one_piece": "Платья", "footwear": "Обувь", "base_layer": "Базовый",
    "accessory": "Аксы", "underwear": "Бельё", "sportswear": "Спорт",
    "special": "Особый", "home_beach": "Дом", "pregnant_specific": "Берем.",
}
_CAT_ORDER = [
    "top", "bottom", "one_piece", "outerwear", "footwear",
    "accessory", "base_layer", "sportswear", "special",
    "home_beach", "underwear", "pregnant_specific",
]
_SEASON_EMOJI = {"winter": "❄️", "spring": "🌸", "summer": "☀️", "autumn": "🍂"}
_SEASON_NAME = {"winter": "Зима", "spring": "Весна", "summer": "Лето", "autumn": "Осень"}


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

async def _get_owner(user, context) -> tuple:
    """Get active owner (child or user)."""
    from bot.handlers.wardrobe import _get_owner as _wo
    return await _wo(user, context)


def _short_id(item_id) -> str:
    """First 8 chars of UUID — unique enough within user's items."""
    return str(item_id)[:8]


def _short_color(color: str, max_len: int = 12) -> str:
    """Truncate color name smartly."""
    c = (color or "").strip()
    if len(c) <= max_len:
        return c
    cut = c[:max_len - 1]
    last = max(cut.rfind(" "), cut.rfind("-"))
    if last > 3:
        return cut[:last] + "."
    return cut + "."


def _filter_items(items: list, season: str = None, category: str = None) -> list:
    result = items
    if season:
        result = [i for i in result if season in (i.season or [])]
    if category:
        result = [i for i in result if i.category_group == category]
    return result


def _format_season(seasons: list) -> str:
    """Format season list for display."""
    if not seasons:
        return "все сезоны"
    labels = [_SEASON_NAME.get(s, s) for s in seasons if s in _SEASON_NAME]
    return ", ".join(labels) if labels else "все сезоны"


def _format_date(dt) -> str:
    """Format datetime for display."""
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        months = ["", "янв", "фев", "мар", "апр", "мая", "июн",
                  "июл", "авг", "сен", "окт", "ноя", "дек"]
        return f"{dt.day} {months[dt.month]} {dt.year}"
    return str(dt)


async def _get_owner_name(user, owner_id, owner_type) -> str:
    """Get display name for owner."""
    if owner_type == "user":
        return user.name or "Мой"
    from db.crud.children import get_children
    async with AsyncReadSession() as s:
        children = await get_children(s, user.id)
    child = next((c for c in children if c.id == owner_id), None)
    return child.name if child else "Ребёнок"


async def _get_children_info(user):
    """Return (has_children, child_name, child_id, child_gender)."""
    from db.crud.children import get_children
    async with AsyncReadSession() as s:
        children = await get_children(s, user.id)
    if children:
        child = children[0]
        return True, child.name, str(child.id), child.gender or "girl"
    return False, "", "", "girl"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 1-2: Overview + Season filter
# ══════════════════════════════════════════════════════════════════════════════

def _build_overview_text(items: list, owner_name: str, season: str = None) -> str:
    """Build overview text with category counts."""
    filtered = _filter_items(items, season=season)
    groups = defaultdict(int)
    for i in filtered:
        groups[i.category_group] += 1

    lines = [f"👗 Гардероб {owner_name}"]
    if season:
        lines[0] += f" · {_SEASON_EMOJI.get(season, '')} {_SEASON_NAME.get(season, season)}"
    lines.append(f"{len(filtered)} вещей")
    lines.append("")

    # Category breakdown in compact format
    cat_parts = []
    for cat in _CAT_ORDER:
        count = groups.get(cat, 0)
        if count > 0 or not season:
            if count > 0:
                name = _CAT_NAME.get(cat, cat)
                cat_parts.append(f"{name}: {count}")
    if cat_parts:
        for i in range(0, len(cat_parts), 4):
            lines.append(" | ".join(cat_parts[i:i + 4]))

    return "\n".join(lines)


def _build_overview_buttons(
    items: list,
    season: str = None,
    owner_type: str = "child",
    has_children: bool = False,
    child_name: str = "",
    child_id: str = "",
    child_gender: str = "girl",
) -> InlineKeyboardMarkup:
    """Build category + season filter buttons."""
    filtered = _filter_items(items, season=season)
    groups = defaultdict(int)
    for i in filtered:
        groups[i.category_group] += 1

    rows = []

    # Owner tabs (if mom with child)
    if has_children:
        owner_row = []
        if owner_type == "child":
            _icon = "👧" if child_gender == "girl" else "👦"
            owner_row.append(InlineKeyboardButton(
                f"{_icon} {child_name} ✓", callback_data="noop",
            ))
            owner_row.append(InlineKeyboardButton(
                "👩 Мои", callback_data="switch_owner:user",
            ))
        else:
            _icon = "👧" if child_gender == "girl" else "👦"
            owner_row.append(InlineKeyboardButton(
                f"{_icon} {child_name}", callback_data=f"switch_owner:child:{child_id}",
            ))
            owner_row.append(InlineKeyboardButton(
                "👩 Мои ✓", callback_data="noop",
            ))
        rows.append(owner_row)

    # Category buttons — 3 per row, only non-zero
    cat_row = []
    for cat in _CAT_ORDER:
        count = groups.get(cat, 0)
        if count == 0:
            continue
        name = _CAT_NAME.get(cat, cat)
        cb = f"w:cat:{cat}:0"
        if season:
            cb += f":{season}"
        cat_row.append(InlineKeyboardButton(f"{name} {count}", callback_data=cb))
        if len(cat_row) == 3:
            rows.append(cat_row)
            cat_row = []
    # "Все" button
    if len(filtered) > 0:
        cb_all = "w:cat:all:0"
        if season:
            cb_all += f":{season}"
        cat_row.append(InlineKeyboardButton(f"Все {len(filtered)}", callback_data=cb_all))
    if cat_row:
        rows.append(cat_row)

    # Season buttons — one row
    season_row = []
    for s_key in ["winter", "spring", "summer", "autumn"]:
        s_emoji = _SEASON_EMOJI[s_key]
        s_name = _SEASON_NAME[s_key]
        if s_key == season:
            label = f"[{s_emoji}{s_name}]"
        else:
            label = f"{s_emoji}{s_name}"
        season_row.append(InlineKeyboardButton(label, callback_data=f"w:sz:{s_key}"))
    rows.append(season_row)

    # Reset season
    if season:
        rows.append([InlineKeyboardButton("Все сезоны", callback_data="w:ov")])

    # Add item
    rows.append([InlineKeyboardButton("📸 Добавить вещь", callback_data="add_items_hint")])

    return InlineKeyboardMarkup(rows)


async def handle_overview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Screen 1: Wardrobe overview. Callback: w:ov"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    owner_name = await _get_owner_name(user, owner_id, owner_type)
    has_children, child_name, child_id, child_gender = await _get_children_info(user)

    text = _build_overview_text(items, owner_name)
    markup = _build_overview_buttons(
        items,
        owner_type=owner_type,
        has_children=has_children,
        child_name=child_name,
        child_id=child_id,
        child_gender=child_gender,
    )

    try:
        await query.edit_message_text(text, reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup)


async def handle_season_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Screen 2: Season filter. Callback: w:sz:{season}"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    season = query.data.split(":")[2]
    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    owner_name = await _get_owner_name(user, owner_id, owner_type)
    has_children, child_name, child_id, child_gender = await _get_children_info(user)

    text = _build_overview_text(items, owner_name, season=season)
    markup = _build_overview_buttons(
        items,
        season=season,
        owner_type=owner_type,
        has_children=has_children,
        child_name=child_name,
        child_id=child_id,
        child_gender=child_gender,
    )

    try:
        await query.edit_message_text(text, reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup)


# ══════════════════════════════════════════════════════════════════════════════
# Screen 3: Category grid (Satori 3x3)
# ══════════════════════════════════════════════════════════════════════════════

async def _download_photo_bytes(file_id: str, photo_url: str = None) -> Optional[bytes]:
    """Download photo by file_id or photo_url."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        if photo_url:
            if photo_url.startswith("http"):
                try:
                    r = await client.get(photo_url, timeout=10.0)
                    r.raise_for_status()
                    return r.content
                except Exception:
                    pass
            else:
                try:
                    from services.storage.r2_storage import get_r2_storage
                    r2 = get_r2_storage()
                    return await r2.get_photo(photo_url)
                except Exception:
                    pass
        if file_id:
            try:
                r = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                    params={"file_id": file_id}, timeout=10.0,
                )
                r.raise_for_status()
                fp = r.json()["result"]["file_path"]
                r2 = await client.get(
                    f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{fp}",
                    timeout=15.0,
                )
                r2.raise_for_status()
                return r2.content
            except Exception as e:
                logger.warning("wardrobe_browser.download_failed",
                               file_id=file_id[:20], error=str(e))
    return None


def _make_thumbnail(photo_bytes: bytes, size: int = 130) -> bytes:
    """Resize photo to square thumbnail."""
    img = Image.open(io.BytesIO(photo_bytes))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _photo_to_data_uri(photo_bytes: bytes) -> str:
    b64 = base64.b64encode(photo_bytes).decode()
    return f"data:image/jpeg;base64,{b64}"


def _placeholder_cell(w: int, h: int) -> dict:
    """Gray placeholder square."""
    return {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "width": f"{w}px",
                "height": f"{h}px",
                "backgroundColor": "#E8E4EE",
                "borderRadius": "8px",
                "alignItems": "center",
                "justifyContent": "center",
                "fontSize": "28px",
                "color": "#C0B8C8",
            },
            "children": ["?"],
        },
    }


async def render_wardrobe_grid(items: list, page: int, total_pages: int) -> Optional[bytes]:
    """Render 3x3 grid of wardrobe items via Satori.

    440px wide, 3 columns, each cell ~130x170px with photo + text below.
    Returns PNG bytes or None on error.
    """
    from services.image_builder import _render_satori

    GRID_W = 440
    COLS = 3
    CELL_W = 130
    PHOTO_H = 120
    GAP = 10
    PAD = 14

    # Download photos in parallel
    tasks = [
        _download_photo_bytes(
            getattr(item, "photo_id", ""),
            getattr(item, "photo_url", None),
        )
        for item in items
    ]
    photo_results = await asyncio.gather(*tasks)

    # Build cells
    cells = []
    for idx, item in enumerate(items):
        photo_bytes = photo_results[idx]

        if photo_bytes:
            try:
                thumb = _make_thumbnail(photo_bytes, PHOTO_H)
                data_uri = _photo_to_data_uri(thumb)
                photo_el = {
                    "type": "img",
                    "props": {
                        "src": data_uri,
                        "width": CELL_W,
                        "height": PHOTO_H,
                        "style": {
                            "objectFit": "cover",
                            "borderRadius": "8px",
                        },
                    },
                }
            except Exception:
                photo_el = _placeholder_cell(CELL_W, PHOTO_H)
        else:
            photo_el = _placeholder_cell(CELL_W, PHOTO_H)

        # Label: "тип цвет"
        item_type = ""
        raw_type = getattr(item, "type", "") or ""
        if raw_type:
            item_type = raw_type.split()[0].capitalize()
        item_color = _short_color(getattr(item, "color", "") or "", 10)
        label = f"{item_type} {item_color}".strip() or "Вещь"

        label_el = {
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "fontSize": "11px",
                    "color": "#666",
                    "textAlign": "center",
                    "justifyContent": "center",
                    "width": f"{CELL_W}px",
                    "marginTop": "4px",
                    "overflow": "hidden",
                },
                "children": [label],
            },
        }

        cell = {
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "flexDirection": "column",
                    "alignItems": "center",
                    "width": f"{CELL_W}px",
                },
                "children": [photo_el, label_el],
            },
        }
        cells.append(cell)

    # Pad empty cells for consistent grid
    while len(cells) < _GRID_SIZE:
        cells.append({
            "type": "div",
            "props": {
                "style": {"display": "flex", "width": f"{CELL_W}px", "height": "1px"},
                "children": [],
            },
        })

    # Build rows of 3
    grid_rows = []
    for r in range(0, min(len(cells), _GRID_SIZE), COLS):
        row = {
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "flexDirection": "row",
                    "gap": f"{GAP}px",
                    "justifyContent": "center",
                },
                "children": cells[r:r + COLS],
            },
        }
        grid_rows.append(row)

    # Footer: page indicator
    footer = {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "justifyContent": "center",
                "fontSize": "12px",
                "color": "#999",
                "marginTop": "4px",
            },
            "children": [f"стр {page + 1}/{total_pages}"],
        },
    }

    # Calculate height based on actual rows
    actual_rows = math.ceil(len(items) / COLS)
    total_h = PAD * 2 + actual_rows * (PHOTO_H + 24 + GAP) + 24

    root = {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "flexDirection": "column",
                "width": f"{GRID_W}px",
                "backgroundColor": "#FAFAFC",
                "padding": f"{PAD}px",
                "gap": f"{GAP}px",
                "borderRadius": "12px",
            },
            "children": grid_rows + [footer],
        },
    }

    png = await _render_satori(root, GRID_W, total_h)
    if png:
        logger.info("wardrobe_browser.grid_ok", items=len(items),
                     page=page, size=len(png))
    return png


async def _build_grid_image_pil(items: list, category: str) -> bytes:
    """Fallback: PIL grid when Satori unavailable."""
    from PIL import ImageDraw, ImageFont

    _CELL = 160
    _GAP = 8
    _GRID_W = _CELL * 3 + _GAP * 4

    _PASTEL = {
        "outerwear": (200, 216, 232), "top": (255, 208, 216), "bottom": (200, 208, 240),
        "one_piece": (224, 208, 240), "footwear": (208, 224, 240), "base_layer": (232, 216, 232),
        "accessory": (240, 224, 208), "underwear": (240, 232, 232),
    }

    n = min(len(items), _GRID_SIZE)
    rows = (n + 2) // 3
    h = _GAP + rows * (_CELL + _GAP)
    img = Image.new("RGB", (_GRID_W, max(h, 100)), (250, 248, 252))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    pastel = _PASTEL.get(category, (240, 235, 230))

    for idx in range(n):
        col = idx % 3
        row_i = idx // 3
        x = _GAP + col * (_CELL + _GAP)
        y = _GAP + row_i * (_CELL + _GAP)

        item = items[idx]

        # Try to load thumbnail
        thumb = None
        if item.photo_url and item.photo_url.startswith("http"):
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(item.photo_url)
                    if r.status_code == 200:
                        thumb = Image.open(io.BytesIO(r.content)).convert("RGBA")
            except Exception:
                pass

        if thumb:
            ratio = min(_CELL / thumb.width, _CELL / thumb.height)
            tw = max(1, int(thumb.width * ratio))
            th = max(1, int(thumb.height * ratio))
            thumb = thumb.resize((tw, th), Image.LANCZOS)
            cell = Image.new("RGB", (_CELL, _CELL), (255, 255, 255))
            ox = (_CELL - tw) // 2
            oy = (_CELL - th) // 2
            cell.paste(thumb, (ox, oy), thumb.split()[3] if thumb.mode == "RGBA" else None)
            img.paste(cell, (x, y))
        else:
            draw.rounded_rectangle([(x, y), (x + _CELL, y + _CELL)], radius=8, fill=pastel)

        # Label at bottom
        color = _short_color(item.color or "", 14)
        if color:
            label_h = 22
            ly = y + _CELL - label_h
            draw.rectangle([(x, ly), (x + _CELL, y + _CELL)], fill=pastel)
            try:
                tw_px = font.getbbox(color)[2]
            except Exception:
                tw_px = len(color) * 7
            tx = x + max(2, (_CELL - tw_px) // 2)
            draw.text((tx, ly + 3), color, fill=(100, 80, 100), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


async def handle_category_grid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Screen 3: Category grid. Callback: w:cat:{category}:{page}[:season]"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    parts = query.data.split(":")
    category = parts[2]
    page = int(parts[3])
    season = parts[4] if len(parts) > 4 else None

    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        all_items = await get_owner_items(session, owner_id, owner_type)

    if category == "all":
        filtered = _filter_items(all_items, season=season)
    else:
        filtered = _filter_items(all_items, season=season, category=category)

    total = len(filtered)
    total_pages = max(1, math.ceil(total / _GRID_SIZE))
    page = min(page, total_pages - 1)

    # Sort: most recent first
    filtered.sort(key=lambda i: getattr(i, "added_at", None) or datetime.min, reverse=True)
    paged = filtered[page * _GRID_SIZE: (page + 1) * _GRID_SIZE]

    if not paged:
        cat_name = _CAT_NAME.get(category, "Все")
        await query.message.reply_text(
            f"В категории \"{cat_name}\" пока нет вещей.\n📸 Пришли фото чтобы добавить!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← Назад", callback_data="w:ov")],
            ]),
        )
        return

    # Store item mapping for detail view
    context.user_data["wrd_items"] = {
        _short_id(item.id): str(item.id) for item in paged
    }

    # Caption
    owner_name = await _get_owner_name(user, owner_id, owner_type)
    cat_emoji = _CAT_EMOJI.get(category, "👗")
    cat_name = _CAT_NAME.get(category, "Все вещи")
    season_tag = f" · {_SEASON_NAME.get(season, '')}" if season else ""
    caption = f"{cat_emoji} {cat_name} · {owner_name} · {total} шт.{season_tag}"

    # Try Satori grid first, fallback to PIL
    grid_bytes = await render_wardrobe_grid(paged, page, total_pages)
    if not grid_bytes:
        grid_bytes = await _build_grid_image_pil(paged, category or "top")

    # Item buttons — 3 per row, numbered
    item_buttons = []
    row = []
    for idx, item in enumerate(paged):
        num = page * _GRID_SIZE + idx + 1
        item_type = ""
        raw = getattr(item, "type", "") or ""
        if raw:
            item_type = raw.split()[0].capitalize()
        color = _short_color(item.color or "", 8)
        label = f"{num}. {item_type} {color}".strip()
        row.append(InlineKeyboardButton(label, callback_data=f"w:it:{_short_id(item.id)}"))
        if len(row) == 3:
            item_buttons.append(row)
            row = []
    if row:
        item_buttons.append(row)

    # Pagination nav
    nav_row = []
    s_suffix = f":{season}" if season else ""
    if total_pages > 1:
        if page > 0:
            nav_row.append(InlineKeyboardButton("←", callback_data=f"w:cat:{category}:{page - 1}{s_suffix}"))
        nav_row.append(InlineKeyboardButton(f"стр {page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("→", callback_data=f"w:cat:{category}:{page + 1}{s_suffix}"))
    if nav_row:
        item_buttons.append(nav_row)

    item_buttons.append([InlineKeyboardButton("← Назад", callback_data="w:ov")])
    markup = InlineKeyboardMarkup(item_buttons)

    # Delete old message, send new photo
    try:
        await query.message.delete()
    except Exception:
        pass

    try:
        await query.message.chat.send_photo(
            photo=grid_bytes, caption=caption, reply_markup=markup,
        )
    except Exception as e:
        logger.warning("wardrobe_browser.send_grid_failed", error=str(e))
        sentry_sdk.capture_exception(e)
        # Text fallback
        lines = [caption, ""]
        for idx, item in enumerate(paged):
            lines.append(f"{page * _GRID_SIZE + idx + 1}. {item.type} {item.color}")
        await query.message.chat.send_message(
            text="\n".join(lines), reply_markup=markup,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Screen 4: Item card
# ══════════════════════════════════════════════════════════════════════════════

async def handle_item_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Screen 4: Item detail. Callback: w:it:{short_id}"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    short = query.data.split(":")[2]

    # Resolve from context cache first
    item_map = context.user_data.get("wrd_items", {})
    full_id_str = item_map.get(short)

    # Fallback: scan owner items
    owner_id, owner_type = await _get_owner(user, context)
    if not full_id_str:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, owner_id, owner_type)
        item = next((i for i in items if str(i.id).startswith(short)), None)
    else:
        try:
            item_id = uuid.UUID(full_id_str)
        except ValueError:
            await query.message.reply_text("Вещь не найдена.")
            return
        async with AsyncReadSession() as session:
            item = await get_by_id(session, item_id)

    if not item:
        await query.message.reply_text("Вещь не найдена.")
        return

    # Caption
    emoji = _CAT_EMOJI.get(item.category_group, "👚")
    item_type = (item.type or "Вещь").capitalize()
    item_color = (item.color or "")
    season_str = _format_season(item.season or [])
    _dt = getattr(item, "added_at", None) or getattr(item, "created_at", None)
    date_str = _format_date(_dt)
    wc = getattr(item, "wear_count", 0) or 0

    caption_lines = [
        f"{emoji} {item_type} {item_color}",
        f"Сезон: {season_str}",
        f"Добавлена: {date_str}",
    ]
    if wc > 0:
        caption_lines.append(f"Носили: {wc} раз")

    caption = "\n".join(caption_lines)
    cat = item.category_group or "top"

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Удалить", callback_data=f"w:del:{_short_id(item.id)}"),
            InlineKeyboardButton("← Назад", callback_data=f"w:cat:{cat}:0"),
        ],
    ])

    # Delete old message, send photo
    try:
        await query.message.delete()
    except Exception:
        pass

    if item.photo_id:
        try:
            await query.message.chat.send_photo(
                photo=item.photo_id, caption=caption, reply_markup=buttons,
            )
            return
        except Exception as e:
            logger.warning("wardrobe_browser.photo_failed",
                           error=str(e), photo_id=item.photo_id[:20])

    await query.message.chat.send_message(
        text=caption, reply_markup=buttons,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Delete handlers
# ══════════════════════════════════════════════════════════════════════════════

async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete confirmation. Callback: w:del:{short_id}"""
    query = update.callback_query
    await query.answer()

    short = query.data.split(":")[2]

    # Try to get item name for better UX
    item_label = "эту вещь"
    item_map = context.user_data.get("wrd_items", {})
    full_id_str = item_map.get(short)
    if full_id_str:
        try:
            item_id = uuid.UUID(full_id_str)
            async with AsyncReadSession() as session:
                item = await get_by_id(session, item_id)
            if item:
                item_label = f"{item.type} {item.color}"
        except Exception:
            pass

    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("Да, удалить", callback_data=f"w:dly:{short}"),
        InlineKeyboardButton("Отмена", callback_data=f"w:it:{short}"),
    ]])

    try:
        await query.edit_message_caption(
            caption=f"🗑 Удалить {item_label}?",
            reply_markup=buttons,
        )
    except Exception:
        await query.message.reply_text(
            f"🗑 Удалить {item_label}?",
            reply_markup=buttons,
        )


async def handle_delete_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirmed delete. Callback: w:dly:{short_id}"""
    query = update.callback_query
    await query.answer("Удалено")
    user = context.user_data.get("db_user")
    if not user:
        return

    short = query.data.split(":")[2]
    owner_id, owner_type = await _get_owner(user, context)

    # Resolve item
    item_map = context.user_data.get("wrd_items", {})
    full_id_str = item_map.get(short)

    if full_id_str:
        try:
            item_id = uuid.UUID(full_id_str)
        except ValueError:
            full_id_str = None

    if not full_id_str:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, owner_id, owner_type)
        item = next((i for i in items if str(i.id).startswith(short)), None)
        if item:
            item_id = item.id
            full_id_str = str(item.id)

    if not full_id_str:
        await query.message.reply_text("Вещь не найдена.")
        return

    # Get item name before deleting
    item_name = "Вещь"
    async with AsyncReadSession() as session:
        item = await get_by_id(session, item_id)
        if item:
            item_name = f"{item.type} {item.color}"

    # Soft delete
    async with AsyncWriteSession() as session:
        await soft_delete(session, item_id)
        await session.commit()

    logger.info("wardrobe_browser.deleted", item_id=full_id_str, user_id=str(user.id))

    # Refresh: show updated overview
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    owner_name = await _get_owner_name(user, owner_id, owner_type)
    has_children, child_name, child_id, child_gender = await _get_children_info(user)

    text = f"✅ {item_name} удалена\n\n{_build_overview_text(items, owner_name)}"
    markup = _build_overview_buttons(
        items,
        owner_type=owner_type,
        has_children=has_children,
        child_name=child_name,
        child_id=child_id,
        child_gender=child_gender,
    )

    try:
        await query.edit_message_text(text, reply_markup=markup)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup)
        except Exception:
            pass
