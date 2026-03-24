"""
Wardrobe browser — visual navigation with Satori 3x3 grid.

Three screens:
  1. Overview (text + inline buttons) — category counts, season filter, owner tabs
  2. Category grid (photo image) — Satori 3x3 grid with thumbnails
  3. Item detail — photo + caption + delete/season buttons

Callbacks:
  w:ov                     — overview
  w:ow:{owner_short}       — switch owner (first 8 chars of UUID)
  w:sz:{season}             — season filter (winter/spring/summer/autumn/all)
  w:cat:{category}:{page}   — category grid page
  w:it:{index}              — item detail (1-9 page index)
  w:del:{short_id}          — delete confirmation
  w:dly:{short_id}          — confirm delete
  w:szed:{short_id}:{season} — toggle season on item
  w:noop                    — inactive button
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
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import settings
from core.redis import get_redis
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
    "outerwear", "top", "bottom", "footwear", "one_piece", "base_layer",
    "accessory", "sportswear", "special", "home_beach", "underwear",
    "pregnant_specific",
]
_SEASON_EMOJI = {"winter": "❄", "spring": "🌸", "summer": "☀", "autumn": "🍂"}
_SEASON_NAME = {"winter": "Зима", "spring": "Весна", "summer": "Лето", "autumn": "Осень"}

# Pastel colors for placeholder cells
_PASTEL = {
    "outerwear": "#C8D8E8", "top": "#FFD0D8", "bottom": "#C8D0F0",
    "one_piece": "#E0D0F0", "footwear": "#D0E0F0", "base_layer": "#E8D8E8",
    "accessory": "#F0E0D0", "underwear": "#F0E8E8", "sportswear": "#D0E8D8",
    "special": "#F0F0D0", "home_beach": "#E0F0E8", "pregnant_specific": "#F0E0F0",
}

# Thumbnail cache TTL
_THUMB_TTL = 86400  # 24h


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

async def _get_owner(user, context) -> tuple:
    """Get active owner (child or user)."""
    from bot.handlers.wardrobe import _get_owner as _wo
    return await _wo(user, context)


def _short_id(item_id) -> str:
    """First 8 chars of UUID."""
    return str(item_id)[:8]


def _short_color(color: str, max_len: int = 14) -> str:
    """Truncate color name smartly."""
    c = (color or "").strip()
    if len(c) <= max_len:
        return c
    cut = c[:max_len - 2]
    last = max(cut.rfind(" "), cut.rfind("-"))
    if last > 3:
        return cut[:last] + " пр."
    return cut + "."


def _filter_items(items: list, season: str = None, category: str = None) -> list:
    result = items
    if season and season != "all":
        result = [i for i in result if season in (i.season or [])]
    if category and category != "all":
        result = [i for i in result if i.category_group == category]
    return result


def _format_season(seasons: list) -> str:
    if not seasons:
        return "все сезоны"
    labels = [_SEASON_NAME.get(s, s) for s in seasons if s in _SEASON_NAME]
    return ", ".join(labels) if labels else "все сезоны"


def _format_date(dt) -> str:
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        months = ["", "янв", "фев", "мар", "апр", "мая", "июн",
                  "июл", "авг", "сен", "окт", "ноя", "дек"]
        return f"{dt.day} {months[dt.month]}"
    return str(dt)


async def _get_owner_name(user, owner_id, owner_type) -> str:
    if owner_type == "user":
        return user.name or "Мой"
    from db.crud.children import get_children
    async with AsyncReadSession() as s:
        children = await get_children(s, user.id)
    child = next((c for c in children if c.id == owner_id), None)
    return child.name if child else "Ребёнок"


async def _get_children_info(user):
    """Return (has_children, child_name, child_id, child_gender)."""
    if user.segment not in ("mom_girl", "mom_boy"):
        return False, "", "", "girl"
    from db.crud.children import get_children
    async with AsyncReadSession() as s:
        children = await get_children(s, user.id)
    if children:
        child = children[0]
        return True, child.name, str(child.id), child.gender or "girl"
    return False, "", "", "girl"


def _item_label(item, max_len: int = 14) -> str:
    """Short label for item: color name or type+color."""
    color = _short_color(item.color or "", max_len)
    return color if color else (item.type or "Вещь")[:max_len]


# ══════════════════════════════════════════════════════════════════════════════
# Thumbnail caching
# ══════════════════════════════════════════════════════════════════════════════

async def _get_cached_thumb(file_id: str) -> Optional[bytes]:
    """Get thumbnail from Redis cache."""
    try:
        redis = get_redis()
        data = await redis.get(f"thumb:{file_id}")
        if data:
            return base64.b64decode(data)
    except Exception:
        pass
    return None


async def _set_cached_thumb(file_id: str, png_bytes: bytes) -> None:
    """Cache thumbnail in Redis."""
    try:
        redis = get_redis()
        b64 = base64.b64encode(png_bytes).decode()
        await redis.set(f"thumb:{file_id}", b64, ex=_THUMB_TTL)
    except Exception:
        pass


async def _download_photo_bytes(file_id: str, photo_url: str = None) -> Optional[bytes]:
    """Download photo by file_id via Telegram getFile API."""
    async with httpx.AsyncClient(timeout=15.0) as client:
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
                logger.warning("wb.download_file_id_failed",
                               file_id=file_id[:20], error=str(e))
        if photo_url and photo_url.startswith("http"):
            try:
                r = await client.get(photo_url, timeout=10.0)
                r.raise_for_status()
                return r.content
            except Exception:
                pass
    return None


def _make_thumbnail(photo_bytes: bytes, size: int = 140) -> bytes:
    """Resize photo to square thumbnail, return PNG bytes."""
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
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _get_thumbnail(item, size: int = 140) -> Optional[bytes]:
    """Get thumbnail for item: from cache or download + cache."""
    file_id = getattr(item, "photo_id", "") or ""
    if not file_id:
        return None

    # Check cache
    cached = await _get_cached_thumb(file_id)
    if cached:
        return cached

    # Download
    photo_url = getattr(item, "photo_url", None)
    raw = await _download_photo_bytes(file_id, photo_url)
    if not raw:
        return None

    try:
        thumb = _make_thumbnail(raw, size)
        await _set_cached_thumb(file_id, thumb)
        return thumb
    except Exception as e:
        logger.warning("wb.thumbnail_failed", error=str(e))
        return None


def _photo_to_data_uri(photo_bytes: bytes) -> str:
    b64 = base64.b64encode(photo_bytes).decode()
    return f"data:image/png;base64,{b64}"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 1: Overview
# ══════════════════════════════════════════════════════════════════════════════

def _build_overview_text(items: list, owner_name: str, season: str = None) -> str:
    """Build overview text with category counts and emoji."""
    filtered = _filter_items(items, season=season)
    groups = defaultdict(int)
    for i in filtered:
        groups[i.category_group] += 1

    total = len(filtered)
    title = f"👗 Гардероб {owner_name} · {total} вещей"
    if season and season != "all":
        title += f" · {_SEASON_EMOJI.get(season, '')} {_SEASON_NAME.get(season, season)}"

    lines = [title, ""]

    # Category breakdown with emoji
    for cat in _CAT_ORDER:
        count = groups.get(cat, 0)
        if count > 0:
            emoji = _CAT_EMOJI.get(cat, "")
            name = _CAT_NAME.get(cat, cat)
            lines.append(f"{emoji} {name} — {count}")

    if not any(groups.values()):
        lines.append("Пока пусто. Пришли фото одежды!")
    else:
        lines.append("")
        lines.append("📷 Чтобы добавить — просто пришли фото")

    return "\n".join(lines)


def _build_overview_buttons(
    items: list,
    season: str = None,
    owner_type: str = "child",
    has_children: bool = False,
    child_name: str = "",
    child_id: str = "",
    child_gender: str = "girl",
    current_owner_id: str = "",
    user_id: str = "",
) -> InlineKeyboardMarkup:
    """Build category + season filter + owner buttons."""
    filtered = _filter_items(items, season=season)
    groups = defaultdict(int)
    for i in filtered:
        groups[i.category_group] += 1

    rows = []

    # Category buttons — 3 per row, only non-zero
    cat_row = []
    for cat in _CAT_ORDER:
        count = groups.get(cat, 0)
        if count == 0:
            continue
        emoji = _CAT_EMOJI.get(cat, "")
        name = _CAT_NAME.get(cat, cat)
        cb = f"w:cat:{cat}:0"
        cat_row.append(InlineKeyboardButton(f"{emoji} {name}", callback_data=cb))
        if len(cat_row) == 3:
            rows.append(cat_row)
            cat_row = []
    if cat_row:
        rows.append(cat_row)

    # Season buttons — one row
    season_row = []
    for s_key in ["winter", "spring", "summer", "autumn"]:
        s_emoji = _SEASON_EMOJI[s_key]
        if s_key == season:
            label = f"[{s_emoji} {_SEASON_NAME[s_key]}]"
        else:
            label = f"{s_emoji} {_SEASON_NAME[s_key]}"
        season_row.append(InlineKeyboardButton(label, callback_data=f"w:sz:{s_key}"))
    rows.append(season_row)

    # Reset season button (only if season is active)
    if season and season != "all":
        rows.append([InlineKeyboardButton("Все сезоны", callback_data="w:sz:all")])

    # Owner tab — only for mom with child
    if has_children:
        _icon = "👧" if child_gender == "girl" else "👦"
        if owner_type == "child":
            rows.append([InlineKeyboardButton(
                f"👩 Показать свои",
                callback_data=f"w:ow:{str(user_id)[:8]}",
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{_icon} Показать {child_name}",
                callback_data=f"w:ow:{child_id[:8]}",
            )])

    return InlineKeyboardMarkup(rows)


async def _send_overview(query_or_message, user, context, season: str = None, is_callback: bool = True):
    """Render and send/edit overview screen."""
    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    owner_name = await _get_owner_name(user, owner_id, owner_type)
    has_children, child_name, child_id, child_gender = await _get_children_info(user)

    # Store season in user_data for category grid back-nav
    context.user_data["wb_season"] = season

    text = _build_overview_text(items, owner_name, season=season)
    markup = _build_overview_buttons(
        items,
        season=season,
        owner_type=owner_type,
        has_children=has_children,
        child_name=child_name,
        child_id=child_id,
        child_gender=child_gender,
        current_owner_id=str(user.id) if owner_type == "user" else child_id,
        user_id=str(user.id),
    )

    if is_callback:
        try:
            await query_or_message.edit_message_text(text, reply_markup=markup)
            return
        except Exception:
            pass
        try:
            await query_or_message.message.reply_text(text, reply_markup=markup)
        except Exception:
            pass
    else:
        await query_or_message.reply_text(text, reply_markup=markup)


async def handle_overview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Screen 1: Wardrobe overview. Callback: w:ov"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    await _send_overview(query, user, context)


async def handle_season_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Season filter. Callback: w:sz:{season}"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    season = query.data.split(":")[2]
    if season == "all":
        season = None
    await _send_overview(query, user, context, season=season)


async def handle_owner_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch owner. Callback: w:ow:{owner_short}"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    owner_short = query.data.split(":")[2]

    # Determine if switching to user or child
    user_short = str(user.id)[:8]
    redis = context.bot_data.get("redis")

    if owner_short == user_short:
        # Switch to user's own wardrobe
        if redis:
            try:
                await redis.set(f"owner_mode:{user.id}", "user", ex=86400)
            except Exception:
                pass
        context.user_data["active_owner_type"] = "user"
    else:
        # Switch to child — find child by short ID
        from db.crud.children import get_children
        async with AsyncReadSession() as s:
            children = await get_children(s, user.id)
        child = next((c for c in children if str(c.id)[:8] == owner_short), None)
        if child:
            if redis:
                try:
                    await redis.set(f"owner_mode:{user.id}", f"child:{child.id}", ex=86400)
                except Exception:
                    pass
            context.user_data["active_owner_type"] = "child"
            context.user_data["active_child_id"] = str(child.id)

    await _send_overview(query, user, context)


# ══════════════════════════════════════════════════════════════════════════════
# Screen 2: Category grid (Satori 3x3 with thumbnails)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_grid_satori(
    items: list,
    header: str,
    page: int,
    total_pages: int,
) -> Optional[bytes]:
    """Render 3x3 grid via Satori with thumbnail photos."""
    from services.image_builder import _render_satori

    GRID_W = 440
    COLS = 3
    CELL_W = 130
    PHOTO_H = 130
    GAP = 10
    PAD = 14
    HEADER_H = 36

    # Download thumbnails in parallel
    thumb_tasks = [_get_thumbnail(item, 140) for item in items]
    thumbs = await asyncio.gather(*thumb_tasks)

    # Build cells
    cells = []
    for idx, item in enumerate(items):
        thumb_bytes = thumbs[idx]
        color = _short_color(item.color or "", 14)
        cat = item.category_group or "top"
        pastel = _PASTEL.get(cat, "#E8E4EE")

        if thumb_bytes:
            try:
                data_uri = _photo_to_data_uri(thumb_bytes)
                photo_el = {
                    "type": "div",
                    "props": {
                        "style": {
                            "display": "flex",
                            "width": f"{CELL_W}px",
                            "height": f"{PHOTO_H}px",
                            "borderRadius": "10px",
                            "overflow": "hidden",
                            "position": "relative",
                        },
                        "children": [
                            {
                                "type": "img",
                                "props": {
                                    "src": data_uri,
                                    "width": CELL_W,
                                    "height": PHOTO_H,
                                    "style": {
                                        "objectFit": "cover",
                                        "width": f"{CELL_W}px",
                                        "height": f"{PHOTO_H}px",
                                    },
                                },
                            },
                            # Color label overlay at bottom
                            {
                                "type": "div",
                                "props": {
                                    "style": {
                                        "display": "flex",
                                        "position": "absolute",
                                        "bottom": "0",
                                        "left": "0",
                                        "right": "0",
                                        "backgroundColor": "rgba(255,255,255,0.85)",
                                        "padding": "3px 6px",
                                        "fontSize": "11px",
                                        "color": "#555",
                                        "justifyContent": "center",
                                    },
                                    "children": [color or ""],
                                },
                            },
                        ],
                    },
                }
            except Exception:
                photo_el = _placeholder_satori(CELL_W, PHOTO_H, color, pastel)
        else:
            photo_el = _placeholder_satori(CELL_W, PHOTO_H, color, pastel)

        cell = {
            "type": "div",
            "props": {
                "style": {
                    "display": "flex",
                    "flexDirection": "column",
                    "alignItems": "center",
                    "width": f"{CELL_W}px",
                },
                "children": [photo_el],
            },
        }
        cells.append(cell)

    # Pad to fill grid
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

    # Header
    header_el = {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "justifyContent": "center",
                "fontSize": "14px",
                "fontWeight": "600",
                "color": "#444",
                "marginBottom": "4px",
            },
            "children": [header],
        },
    }

    actual_rows = math.ceil(len(items) / COLS)
    total_h = PAD * 2 + HEADER_H + actual_rows * (PHOTO_H + GAP) + 10

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
            "children": [header_el] + grid_rows,
        },
    }

    png = await _render_satori(root, GRID_W, total_h)
    if png:
        logger.info("wb.grid_satori_ok", items=len(items), page=page, size=len(png))
    return png


def _placeholder_satori(w: int, h: int, label: str, bg_color: str) -> dict:
    """Pastel rectangle with color name text."""
    return {
        "type": "div",
        "props": {
            "style": {
                "display": "flex",
                "width": f"{w}px",
                "height": f"{h}px",
                "backgroundColor": bg_color,
                "borderRadius": "10px",
                "alignItems": "center",
                "justifyContent": "center",
                "fontSize": "13px",
                "color": "#888",
            },
            "children": [label or "?"],
        },
    }


async def _build_grid_pil(items: list, category: str, header: str) -> bytes:
    """PIL fallback: 3x3 grid with thumbnails."""
    CELL = 140
    GAP = 8
    GRID_W = CELL * 3 + GAP * 4
    HEADER_H = 30

    pastel_rgb = {
        "outerwear": (200, 216, 232), "top": (255, 208, 216), "bottom": (200, 208, 240),
        "one_piece": (224, 208, 240), "footwear": (208, 224, 240), "base_layer": (232, 216, 232),
        "accessory": (240, 224, 208), "underwear": (240, 232, 232), "sportswear": (208, 232, 216),
    }

    n = min(len(items), _GRID_SIZE)
    rows_count = max(1, (n + 2) // 3)
    h = HEADER_H + GAP + rows_count * (CELL + GAP)
    img = Image.new("RGB", (GRID_W, max(h, 100)), (250, 248, 252))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        header_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
        header_font = font

    # Header
    # Strip emoji for PIL (PIL can't render unicode emoji)
    header_clean = header
    for emoji in ["🧥", "👚", "👖", "👗", "👟", "🧦", "🎀", "👙", "🏃", "✨", "🏠", "🤰", "·"]:
        header_clean = header_clean.replace(emoji, "")
    header_clean = header_clean.strip()
    draw.text((GAP, 8), header_clean, fill=(80, 70, 90), font=header_font)

    pastel = pastel_rgb.get(category, (240, 235, 230))

    # Download thumbnails
    thumb_tasks = [_get_thumbnail(item, CELL) for item in items[:n]]
    thumbs = asyncio.get_event_loop().run_until_complete(asyncio.gather(*thumb_tasks)) if False else []
    # PIL fallback runs in async context, use gathered thumbs
    # We'll download synchronously-ish via the event loop
    try:
        thumbs = asyncio.get_event_loop().run_until_complete(asyncio.gather(*thumb_tasks))
    except RuntimeError:
        thumbs = [None] * n

    for idx in range(n):
        col = idx % 3
        row_i = idx // 3
        x = GAP + col * (CELL + GAP)
        y = HEADER_H + GAP + row_i * (CELL + GAP)
        item = items[idx]

        thumb_bytes = thumbs[idx] if idx < len(thumbs) else None
        if thumb_bytes:
            try:
                thumb_img = Image.open(io.BytesIO(thumb_bytes)).convert("RGBA")
                ratio = min(CELL / thumb_img.width, CELL / thumb_img.height)
                tw = max(1, int(thumb_img.width * ratio))
                th = max(1, int(thumb_img.height * ratio))
                thumb_img = thumb_img.resize((tw, th), Image.LANCZOS)
                cell_img = Image.new("RGB", (CELL, CELL), (255, 255, 255))
                ox = (CELL - tw) // 2
                oy = (CELL - th) // 2
                cell_img.paste(thumb_img, (ox, oy),
                               thumb_img.split()[3] if thumb_img.mode == "RGBA" else None)
                img.paste(cell_img, (x, y))
            except Exception:
                draw.rounded_rectangle([(x, y), (x + CELL, y + CELL)], radius=8, fill=pastel)
        else:
            draw.rounded_rectangle([(x, y), (x + CELL, y + CELL)], radius=8, fill=pastel)

        # Label at bottom
        color = _short_color(item.color or "", 14)
        if color:
            label_h = 20
            ly = y + CELL - label_h
            draw.rectangle([(x, ly), (x + CELL, y + CELL)], fill=(*pastel[:3],))
            try:
                tw_px = font.getbbox(color)[2]
            except Exception:
                tw_px = len(color) * 7
            tx = x + max(2, (CELL - tw_px) // 2)
            draw.text((tx, ly + 3), color, fill=(100, 80, 100), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


async def _build_grid_pil_async(items: list, category: str, header: str) -> bytes:
    """Async PIL fallback: 3x3 grid with thumbnails."""
    CELL = 140
    GAP = 8
    GRID_W = CELL * 3 + GAP * 4
    HEADER_H = 30

    pastel_rgb = {
        "outerwear": (200, 216, 232), "top": (255, 208, 216), "bottom": (200, 208, 240),
        "one_piece": (224, 208, 240), "footwear": (208, 224, 240), "base_layer": (232, 216, 232),
        "accessory": (240, 224, 208), "underwear": (240, 232, 232), "sportswear": (208, 232, 216),
    }

    n = min(len(items), _GRID_SIZE)
    rows_count = max(1, (n + 2) // 3)
    h = HEADER_H + GAP + rows_count * (CELL + GAP)
    img = Image.new("RGB", (GRID_W, max(h, 100)), (250, 248, 252))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        header_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
        header_font = font

    # Header (strip emoji for PIL)
    header_clean = header
    for emoji in ["🧥", "👚", "👖", "👗", "👟", "🧦", "🎀", "👙", "🏃", "✨", "🏠", "🤰", "·"]:
        header_clean = header_clean.replace(emoji, "")
    header_clean = header_clean.strip()
    draw.text((GAP, 8), header_clean, fill=(80, 70, 90), font=header_font)

    pastel = pastel_rgb.get(category, (240, 235, 230))

    # Download thumbnails in parallel
    thumb_tasks = [_get_thumbnail(item, CELL) for item in items[:n]]
    thumbs = await asyncio.gather(*thumb_tasks)

    for idx in range(n):
        col = idx % 3
        row_i = idx // 3
        x = GAP + col * (CELL + GAP)
        y = HEADER_H + GAP + row_i * (CELL + GAP)
        item = items[idx]

        thumb_bytes = thumbs[idx] if idx < len(thumbs) else None
        if thumb_bytes:
            try:
                thumb_img = Image.open(io.BytesIO(thumb_bytes)).convert("RGBA")
                ratio = min(CELL / thumb_img.width, CELL / thumb_img.height)
                tw = max(1, int(thumb_img.width * ratio))
                th = max(1, int(thumb_img.height * ratio))
                thumb_img = thumb_img.resize((tw, th), Image.LANCZOS)
                cell_img = Image.new("RGB", (CELL, CELL), (255, 255, 255))
                ox = (CELL - tw) // 2
                oy = (CELL - th) // 2
                cell_img.paste(thumb_img, (ox, oy),
                               thumb_img.split()[3] if thumb_img.mode == "RGBA" else None)
                img.paste(cell_img, (x, y))
            except Exception:
                draw.rounded_rectangle([(x, y), (x + CELL, y + CELL)], radius=8, fill=pastel)
        else:
            draw.rounded_rectangle([(x, y), (x + CELL, y + CELL)], radius=8, fill=pastel)

        # Color label at bottom of cell
        color = _short_color(item.color or "", 14)
        if color:
            label_h = 20
            ly = y + CELL - label_h
            draw.rectangle([(x, ly), (x + CELL, y + CELL)], fill=pastel)
            try:
                tw_px = font.getbbox(color)[2]
            except Exception:
                tw_px = len(color) * 7
            tx = x + max(2, (CELL - tw_px) // 2)
            draw.text((tx, ly + 3), color, fill=(100, 80, 100), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


async def handle_category_grid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Screen 2: Category grid. Callback: w:cat:{category}:{page}"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    parts = query.data.split(":")
    category = parts[2]
    page = int(parts[3])

    # Get season from user_data (set by overview)
    season = context.user_data.get("wb_season")

    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        all_items = await get_owner_items(session, owner_id, owner_type)

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
                [InlineKeyboardButton("← Гардероб", callback_data="w:ov")],
            ]),
        )
        return

    # Store page items mapping: index (1-9) → UUID
    page_items = {}
    for idx, item in enumerate(paged):
        page_items[str(idx + 1)] = str(item.id)
    context.user_data["wardrobe_page_items"] = page_items
    # Also store short_id mapping for delete
    context.user_data["wrd_items"] = {
        _short_id(item.id): str(item.id) for item in paged
    }
    # Store current category + page for back navigation
    context.user_data["wb_cat"] = category
    context.user_data["wb_page"] = page

    # Header text
    owner_name = await _get_owner_name(user, owner_id, owner_type)
    cat_emoji = _CAT_EMOJI.get(category, "👗")
    cat_name = _CAT_NAME.get(category, "Все вещи")
    header = f"{cat_emoji} {cat_name} · {owner_name} · {total} вещей"

    # Try Satori grid first, fallback to PIL
    grid_bytes = await _render_grid_satori(paged, header, page, total_pages)
    if not grid_bytes:
        grid_bytes = await _build_grid_pil_async(paged, category or "top", header)

    # Item buttons — 3 per row, numbered
    item_buttons = []
    row = []
    for idx, item in enumerate(paged):
        num = idx + 1
        label = f"{num} {_item_label(item, 14)}"
        row.append(InlineKeyboardButton(label, callback_data=f"w:it:{num}"))
        if len(row) == 3:
            item_buttons.append(row)
            row = []
    if row:
        item_buttons.append(row)

    # Navigation row
    nav_row = [InlineKeyboardButton("← Гардероб", callback_data="w:ov")]
    if total_pages > 1:
        if page > 0:
            nav_row.insert(0, InlineKeyboardButton("◀", callback_data=f"w:cat:{category}:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"стр {page + 1}/{total_pages}", callback_data="w:noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("▶", callback_data=f"w:cat:{category}:{page + 1}"))
    item_buttons.append(nav_row)
    markup = InlineKeyboardMarkup(item_buttons)

    # Delete old message, send new photo
    try:
        await query.message.delete()
    except Exception:
        pass

    try:
        await query.message.chat.send_photo(
            photo=grid_bytes, caption=header, reply_markup=markup,
        )
    except Exception as e:
        logger.warning("wb.send_grid_failed", error=str(e))
        sentry_sdk.capture_exception(e)
        # Text fallback
        lines = [header, ""]
        for idx, item in enumerate(paged):
            lines.append(f"{idx + 1}. {item.type} {item.color}")
        await query.message.chat.send_message(
            text="\n".join(lines), reply_markup=markup,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Screen 3: Item detail
# ══════════════════════════════════════════════════════════════════════════════

async def handle_item_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Screen 3: Item detail. Callback: w:it:{index}"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    index = query.data.split(":")[2]  # 1-9

    # Resolve from page items mapping
    page_items = context.user_data.get("wardrobe_page_items", {})
    full_id_str = page_items.get(index)

    if not full_id_str:
        # Fallback: try wrd_items (old format)
        item_map = context.user_data.get("wrd_items", {})
        full_id_str = item_map.get(index)

    if not full_id_str:
        await query.message.reply_text("Вещь не найдена.")
        return

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
    item_type = (item.type or "Вещь").capitalize()
    item_color = (item.color or "")
    cat_name = _CAT_NAME.get(item.category_group, "")
    season_str = _format_season(item.season or [])
    _dt = getattr(item, "added_at", None) or getattr(item, "created_at", None)
    date_str = _format_date(_dt)

    caption_lines = [
        f"{item_type} {item_color}",
        f"{cat_name} · {season_str} · {item_color.split()[0] if item_color else ''}",
        f"Добавлена {date_str}",
    ]
    caption = "\n".join(caption_lines)

    short = _short_id(item.id)
    cat = item.category_group or "top"
    cat_page = context.user_data.get("wb_page", 0)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Удалить", callback_data=f"w:del:{short}"),
            InlineKeyboardButton("Сезон", callback_data=f"w:szed:{short}:pick"),
            InlineKeyboardButton(f"← {_CAT_NAME.get(cat, 'Назад')}", callback_data=f"w:cat:{cat}:{cat_page}"),
        ],
    ])

    # Store item for season editing
    context.user_data["wb_detail_item"] = full_id_str

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
            logger.warning("wb.photo_failed", error=str(e), photo_id=item.photo_id[:20])

    await query.message.chat.send_message(text=caption, reply_markup=buttons)


# ══════════════════════════════════════════════════════════════════════════════
# Season editing on item
# ══════════════════════════════════════════════════════════════════════════════

async def handle_season_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle season on item. Callback: w:szed:{short_id}:{season}"""
    query = update.callback_query
    user = context.user_data.get("db_user")
    if not user:
        await query.answer()
        return

    parts = query.data.split(":")
    short = parts[2]
    action = parts[3] if len(parts) > 3 else "pick"

    # Resolve item
    item_map = context.user_data.get("wrd_items", {})
    full_id_str = item_map.get(short)
    if not full_id_str:
        full_id_str = context.user_data.get("wb_detail_item")

    if not full_id_str:
        await query.answer("Вещь не найдена")
        return

    try:
        item_id = uuid.UUID(full_id_str)
    except ValueError:
        await query.answer("Вещь не найдена")
        return

    if action == "pick":
        # Show season picker
        await query.answer()
        async with AsyncReadSession() as session:
            item = await get_by_id(session, item_id)
        if not item:
            return

        current_seasons = set(item.season or [])
        season_buttons = []
        for s_key in ["winter", "spring", "summer", "autumn"]:
            s_emoji = _SEASON_EMOJI[s_key]
            check = " ✓" if s_key in current_seasons else ""
            season_buttons.append(InlineKeyboardButton(
                f"{s_emoji}{check}", callback_data=f"w:szed:{short}:{s_key}",
            ))

        cat = item.category_group or "top"
        cat_page = context.user_data.get("wb_page", 0)

        markup = InlineKeyboardMarkup([
            season_buttons,
            [InlineKeyboardButton("← Назад", callback_data=f"w:cat:{cat}:{cat_page}")],
        ])

        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:
            pass
        return

    # Toggle season
    season_key = action
    if season_key not in _SEASON_NAME:
        await query.answer("Неизвестный сезон")
        return

    async with AsyncWriteSession() as session:
        item = await get_by_id(session, item_id)
        if not item:
            await query.answer("Вещь не найдена")
            return

        current = set(item.season or [])
        if season_key in current:
            current.discard(season_key)
        else:
            current.add(season_key)

        from sqlalchemy import update as sa_update
        from db.models.wardrobe import WardrobeItem
        await session.execute(
            sa_update(WardrobeItem)
            .where(WardrobeItem.id == item_id)
            .values(season=list(current))
        )
        await session.commit()

    await query.answer(f"{'+'  if season_key in current else '-'}{_SEASON_NAME[season_key]}")

    # Refresh season picker buttons
    season_buttons = []
    for s_key in ["winter", "spring", "summer", "autumn"]:
        s_emoji = _SEASON_EMOJI[s_key]
        check = " ✓" if s_key in current else ""
        season_buttons.append(InlineKeyboardButton(
            f"{s_emoji}{check}", callback_data=f"w:szed:{short}:{s_key}",
        ))

    cat = item.category_group or "top"
    cat_page = context.user_data.get("wb_page", 0)

    markup = InlineKeyboardMarkup([
        season_buttons,
        [InlineKeyboardButton("← Назад", callback_data=f"w:cat:{cat}:{cat_page}")],
    ])

    try:
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Delete handlers
# ══════════════════════════════════════════════════════════════════════════════

async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete confirmation. Callback: w:del:{short_id}"""
    query = update.callback_query
    await query.answer()

    short = query.data.split(":")[2]

    # Try to get item name
    item_label = "эту вещь"
    item_map = context.user_data.get("wrd_items", {})
    full_id_str = item_map.get(short)
    if not full_id_str:
        full_id_str = context.user_data.get("wb_detail_item")
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
        InlineKeyboardButton("Отмена", callback_data=f"w:it:{context.user_data.get('_last_item_idx', '1')}"),
    ]])

    try:
        await query.edit_message_caption(
            caption=f"🗑 Удалить {item_label}?",
            reply_markup=buttons,
        )
    except Exception:
        try:
            await query.edit_message_text(
                text=f"🗑 Удалить {item_label}?",
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
    if not full_id_str:
        full_id_str = context.user_data.get("wb_detail_item")

    if not full_id_str:
        # Fallback: scan
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, owner_id, owner_type)
        item = next((i for i in items if str(i.id).startswith(short)), None)
        if item:
            full_id_str = str(item.id)

    if not full_id_str:
        await query.message.reply_text("Вещь не найдена.")
        return

    try:
        item_id = uuid.UUID(full_id_str)
    except ValueError:
        await query.message.reply_text("Вещь не найдена.")
        return

    # Get item name before deleting
    item_name = "Вещь"
    async with AsyncReadSession() as session:
        item = await get_by_id(session, item_id)
        if item:
            item_name = f"{item.type} {item.color}"

    # Check if item is in today's brief (warn user)
    try:
        from datetime import date as _date_del
        from sqlalchemy import select as _sel_del, cast, String
        from db.models.brief_log import BriefLog as _BL
        async with AsyncReadSession() as _s_check:
            _today_brief = await _s_check.scalar(
                _sel_del(_BL.id).where(
                    _BL.user_id == user.id,
                    _BL.date == _date_del.today(),
                )
            )
    except Exception:
        _today_brief = None

    # Soft delete (with owner check to prevent cross-user deletion)
    async with AsyncWriteSession() as session:
        await soft_delete(session, item_id, owner_id=owner_id, owner_type=owner_type)
        await session.commit()

    logger.info("wb.deleted", item_id=full_id_str, user_id=str(user.id),
                in_today_brief=bool(_today_brief))

    # Delete detail message, show refreshed overview
    try:
        await query.message.delete()
    except Exception:
        pass

    # Send fresh overview
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
        current_owner_id=str(user.id) if owner_type == "user" else child_id,
        user_id=str(user.id),
    )

    try:
        await query.message.chat.send_message(text, reply_markup=markup)
    except Exception:
        pass


async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inactive button. Callback: w:noop"""
    await update.callback_query.answer()
