"""
Wardrobe browser — visual navigation with 4 screens:
1. Overview: category counts + filter buttons (text, edit_message)
2. Season filter: same message, filtered counts (edit_message)
3. Category grid: 3x3 photo grid (sendPhoto + PIL)
4. Item card: real photo + actions (sendPhoto)
"""
import io
import uuid
from collections import defaultdict
from datetime import date
from typing import Optional

import structlog
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db.base import AsyncReadSession, AsyncWriteSession
from db.crud.wardrobe import get_owner_items, get_by_id, soft_delete

logger = structlog.get_logger()

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_GRID_SIZE = 9  # 3x3
_CELL = 160
_GAP = 8
_GRID_W = _CELL * 3 + _GAP * 4  # 512

_CAT_EMOJI = {
    "outerwear": "🧥", "top": "👚", "bottom": "👖",
    "one_piece": "👗", "footwear": "👟", "base_layer": "🧦",
    "accessory": "🎀", "underwear": "👙",
}
_CAT_NAME = {
    "outerwear": "Верхняя", "top": "Верх", "bottom": "Низ",
    "one_piece": "Платья", "footwear": "Обувь", "base_layer": "Базовый",
    "accessory": "Аксессуары", "underwear": "Бельё",
}
_CAT_ORDER = ["outerwear", "top", "bottom", "one_piece", "footwear", "base_layer", "accessory", "underwear"]
_SEASON_EMOJI = {"winter": "❄", "spring": "🌸", "summer": "☀", "autumn": "🍂"}
_SEASON_NAME = {"winter": "Зима", "spring": "Весна", "summer": "Лето", "autumn": "Осень"}

_PASTEL = {
    "outerwear": (200, 216, 232), "top": (255, 208, 216), "bottom": (200, 208, 240),
    "one_piece": (224, 208, 240), "footwear": (208, 224, 240), "base_layer": (232, 216, 232),
    "accessory": (240, 224, 208), "underwear": (240, 232, 232),
}


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
    # Cut at word boundary
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


# ══════════════════════════════════════════════════════════════════════════════
# Screen 1-2: Overview + Season filter
# ══════════════════════════════════════════════════════════════════════════════

def _build_overview_text(items: list, owner_name: str, season: str = None) -> str:
    """Build overview text with category counts."""
    filtered = _filter_items(items, season=season)
    groups = defaultdict(int)
    for i in filtered:
        groups[i.category_group] += 1

    lines = [f"👗 <b>Гардероб {owner_name}</b>"]
    if season:
        lines.append(f"{_SEASON_EMOJI.get(season, '')} {_SEASON_NAME.get(season, season)} · {len(filtered)} вещей")
    else:
        lines.append(f"{len(items)} вещей")
    lines.append("")

    for cat in _CAT_ORDER:
        count = groups.get(cat, 0)
        if count == 0 and season:
            continue  # hide empty categories in season filter
        emoji = _CAT_EMOJI.get(cat, "📦")
        name = _CAT_NAME.get(cat, cat)
        lines.append(f"{emoji} {name} — {count}")

    return "\n".join(lines)


def _build_overview_buttons(items: list, season: str = None) -> InlineKeyboardMarkup:
    """Build category + season filter buttons."""
    filtered = _filter_items(items, season=season)
    groups = defaultdict(int)
    for i in filtered:
        groups[i.category_group] += 1

    # Category buttons — 3 per row
    cat_buttons = []
    row = []
    for cat in _CAT_ORDER:
        count = groups.get(cat, 0)
        if count == 0:
            continue
        emoji = _CAT_EMOJI.get(cat, "📦")
        name = _CAT_NAME.get(cat, cat)
        cb = f"w:cat:{cat}:0"
        if season:
            cb = f"w:cat:{cat}:0:{season}"
        row.append(InlineKeyboardButton(f"{emoji} {name}", callback_data=cb))
        if len(row) == 3:
            cat_buttons.append(row)
            row = []
    if row:
        cat_buttons.append(row)

    # Season buttons — one row
    season_row = []
    for s_key, s_emoji in _SEASON_EMOJI.items():
        s_name = _SEASON_NAME[s_key]
        if s_key == season:
            label = f"[{s_emoji} {s_name}]"  # highlighted
        else:
            label = f"{s_emoji} {s_name}"
        season_row.append(InlineKeyboardButton(label, callback_data=f"w:sz:{s_key}"))

    all_buttons = cat_buttons + [season_row]

    # Reset season button
    if season:
        all_buttons.append([InlineKeyboardButton("Все сезоны", callback_data="w:ov")])

    return InlineKeyboardMarkup(all_buttons)


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

    # Owner name
    if owner_type == "child":
        from db.crud.children import get_children
        async with AsyncReadSession() as s:
            children = await get_children(s, user.id)
        child = next((c for c in children if c.id == owner_id), None)
        owner_name = child.name if child else "ребёнок"
    else:
        owner_name = user.name or "Мой"

    text = _build_overview_text(items, owner_name)
    markup = _build_overview_buttons(items)

    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


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

    if owner_type == "child":
        from db.crud.children import get_children
        async with AsyncReadSession() as s:
            children = await get_children(s, user.id)
        child = next((c for c in children if c.id == owner_id), None)
        owner_name = child.name if child else "ребёнок"
    else:
        owner_name = user.name or "Мой"

    text = _build_overview_text(items, owner_name, season=season)
    markup = _build_overview_buttons(items, season=season)

    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


# ══════════════════════════════════════════════════════════════════════════════
# Screen 3: Category grid (PIL image)
# ══════════════════════════════════════════════════════════════════════════════

async def _build_grid_image(items: list, category: str) -> bytes:
    """Build 3x3 grid PIL image with thumbnails or pastel fills."""
    n = min(len(items), _GRID_SIZE)
    rows = (n + 2) // 3
    h = _GAP + rows * (_CELL + _GAP)
    img = Image.new("RGB", (_GRID_W, max(h, 100)), (250, 248, 252))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(_FONT_PATH, 13)
    except Exception:
        font = ImageFont.load_default()

    pastel = _PASTEL.get(category, (240, 235, 230))

    for idx in range(n):
        col = idx % 3
        row = idx // 3
        x = _GAP + col * (_CELL + _GAP)
        y = _GAP + row * (_CELL + _GAP)

        item = items[idx]

        # Try to load thumbnail from photo_url or file_id
        thumb = None
        if item.photo_url and item.photo_url.startswith("http"):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(item.photo_url)
                    if r.status_code == 200:
                        thumb = Image.open(io.BytesIO(r.content)).convert("RGBA")
            except Exception:
                pass

        if thumb:
            # Fit photo into cell
            ratio = min(_CELL / thumb.width, _CELL / thumb.height)
            tw = max(1, int(thumb.width * ratio))
            th = max(1, int(thumb.height * ratio))
            thumb = thumb.resize((tw, th), Image.LANCZOS)
            # White bg cell
            cell = Image.new("RGB", (_CELL, _CELL), (255, 255, 255))
            ox = (_CELL - tw) // 2
            oy = (_CELL - th) // 2
            cell.paste(thumb, (ox, oy), thumb.split()[3] if thumb.mode == "RGBA" else None)
            img.paste(cell, (x, y))
        else:
            # Pastel fill
            draw.rounded_rectangle([(x, y), (x + _CELL, y + _CELL)], radius=8, fill=pastel)

        # Color label overlay at bottom
        color = _short_color(item.color or "", 14)
        if color:
            label_h = 22
            ly = y + _CELL - label_h
            draw.rectangle([(x, ly), (x + _CELL, y + _CELL)], fill=(*pastel[:3],))
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

    filtered = _filter_items(all_items, season=season, category=category)
    total = len(filtered)
    total_pages = max(1, (total + _GRID_SIZE - 1) // _GRID_SIZE)
    page = min(page, total_pages - 1)
    paged = filtered[page * _GRID_SIZE: (page + 1) * _GRID_SIZE]

    if not paged:
        await query.message.reply_text("В этой категории пока нет вещей.")
        return

    # Owner name for header
    if owner_type == "child":
        from db.crud.children import get_children
        async with AsyncReadSession() as s:
            children = await get_children(s, user.id)
        child = next((c for c in children if c.id == owner_id), None)
        owner_name = child.name if child else ""
    else:
        owner_name = user.name or ""

    cat_emoji = _CAT_EMOJI.get(category, "📦")
    cat_name = _CAT_NAME.get(category, category)
    caption = f"{cat_emoji} {cat_name} · {owner_name} · {total} вещей"

    # Generate grid image
    grid_bytes = await _build_grid_image(paged, category)

    # Item buttons — 3 per row, numbered
    item_buttons = []
    row = []
    for idx, item in enumerate(paged):
        num = page * _GRID_SIZE + idx + 1
        label = f"{num} {_short_color(item.color or item.type, 10)}"
        row.append(InlineKeyboardButton(label, callback_data=f"w:it:{_short_id(item.id)}"))
        if len(row) == 3:
            item_buttons.append(row)
            row = []
    if row:
        item_buttons.append(row)

    # Pagination
    nav_row = [InlineKeyboardButton("← Гардероб", callback_data="w:ov")]
    if total_pages > 1:
        if page > 0:
            prev_cb = f"w:cat:{category}:{page - 1}"
            if season:
                prev_cb += f":{season}"
            nav_row.insert(0, InlineKeyboardButton("←", callback_data=prev_cb))
        if page < total_pages - 1:
            next_cb = f"w:cat:{category}:{page + 1}"
            if season:
                next_cb += f":{season}"
            nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages} →", callback_data=next_cb))
    item_buttons.append(nav_row)

    markup = InlineKeyboardMarkup(item_buttons)

    # Delete old grid message, send new one
    try:
        await query.message.delete()
    except Exception:
        pass

    await query.message.chat.send_photo(
        photo=grid_bytes, caption=caption, reply_markup=markup,
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

    # Find item by short ID prefix
    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    item = next((i for i in items if str(i.id).startswith(short)), None)
    if not item:
        await query.message.reply_text("Вещь не найдена.")
        return

    # Caption
    cat_name = _CAT_NAME.get(item.category_group, item.category_group or "")
    seasons = ", ".join(_SEASON_NAME.get(s, s) for s in (item.season or []))
    color_dot = f"● {item.color}" if item.color else ""

    lines = [f"<b>{item.type or 'Вещь'} {item.color or ''}</b>"]
    tags = []
    if cat_name:
        tags.append(cat_name)
    if seasons:
        tags.append(seasons)
    if color_dot:
        tags.append(color_dot)
    if tags:
        lines.append("  ".join(tags))
    _created = getattr(item, "created_at", None)
    if _created:
        lines.append(f"Добавлена {_created.strftime('%d.%m.%y')}")
    wc = getattr(item, "wear_count", 0) or 0
    if wc > 0:
        lines.append(f"Надевали {wc} раз")

    caption = "\n".join(lines)
    cat = item.category_group or "top"

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Удалить", callback_data=f"w:del:{_short_id(item.id)}"),
            InlineKeyboardButton(f"← {_CAT_NAME.get(cat, 'Назад')}", callback_data=f"w:cat:{cat}:0"),
        ],
    ])

    # Send real photo
    try:
        await query.message.delete()
    except Exception:
        pass

    if item.photo_id:
        await query.message.chat.send_photo(
            photo=item.photo_id, caption=caption, parse_mode="HTML", reply_markup=buttons,
        )
    else:
        await query.message.chat.send_message(
            text=caption, parse_mode="HTML", reply_markup=buttons,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Delete handlers
# ══════════════════════════════════════════════════════════════════════════════

async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete confirmation. Callback: w:del:{short_id}"""
    query = update.callback_query
    await query.answer()

    short = query.data.split(":")[2]
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("Да, удалить", callback_data=f"w:dly:{short}"),
        InlineKeyboardButton("Отмена", callback_data=f"w:it:{short}"),
    ]])
    await query.message.reply_text("Точно удалить вещь?", reply_markup=buttons)


async def handle_delete_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirmed delete. Callback: w:dly:{short_id}"""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    short = query.data.split(":")[2]
    owner_id, owner_type = await _get_owner(user, context)

    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)
    item = next((i for i in items if str(i.id).startswith(short)), None)

    if item:
        async with AsyncWriteSession() as session:
            await soft_delete(session, item.id)
            await session.commit()
        await query.message.reply_text(f"✅ {item.type} удалена")
        logger.info("wardrobe.item.deleted", item_id=str(item.id), user_id=str(user.id))
    else:
        await query.message.reply_text("Вещь не найдена.")
