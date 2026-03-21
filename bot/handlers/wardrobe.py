"""Wardrobe handlers."""
import asyncio
import base64
import io
import json
import time
import uuid

import sentry_sdk
import structlog
import sqlalchemy as sa
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import settings

# ── Tracked background tasks ────────────────────────────────────────────────
_background_tasks: set[asyncio.Task] = set()


def _track_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create a tracked asyncio.Task that auto-removes itself when done."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
from core.anthropic_client import get_anthropic_pool
from db.base import AsyncWriteSession, AsyncReadSession
from db.crud.wardrobe import create, get_owner_items
from db.models.user import User
from exceptions import FashionBotError, RateLimitError
from services.i18n.ru import t
from bot.handlers.menu import get_main_menu
from services.scoring import ScoringService, matrix_name_for_owner, calc_item_score
from services.usage import get_limit_exceeded_msg, get_usage_str
from core.permissions import get_effective_plan, get_limit
from services.vision import (
    _build_rate_prompt,
    _dedup_key,
    _item_label,
    _fix_bbox,
    _default_score,
    _crop_bbox,
    _check_crop_quality,
    _call_vision,
    _call_rate_vision,
    _color_similar,
    _RATE_SYSTEM_CHILD,
    _RATE_SYSTEM_ADULT,
)
from services.outfit_builder import (
    select_outfit,
    get_temp_regime,
    get_collage_params,
    build_outfit_slots,
    score_to_text,
    outfit_score_to_text,
    color_circle,
    warm_outfit_comment as _warm_outfit_comment,
    SEASONS,
)

logger = structlog.get_logger()


_VALID_CATEGORY_GROUPS = {
    "outerwear", "top", "bottom", "one_piece", "footwear",
    "accessory", "base_layer", "sportswear", "special",
    "home_beach", "pregnant_specific", "underwear",
}

_CATEGORY_LABELS = {
    "outerwear": "Верхняя одежда",
    "top": "Верх",
    "bottom": "Низ",
    "one_piece": "Комбинезон/платье",
    "footwear": "Обувь",
    "accessory": "Аксессуары",
    "base_layer": "Базовый слой",
    "sportswear": "Спортивная",
    "special": "Особый повод",
    "home_beach": "Дом/пляж",
    "pregnant_specific": "Для беременных",
    "underwear": "Нижнее бельё",
}


PAGE_SIZE = 20
OUTFIT_DAY_LIMIT_FREE = 2
OUTFIT_DAY_LIMIT_PREMIUM = 5

# ── Next item suggestion based on missing wardrobe slots ──────────────────
_CORE_SLOTS = ["outerwear", "top", "bottom", "footwear"]
_SLOT_SUGGEST_NAMES = {
    "outerwear": "куртку",
    "top": "кофту или рубашку",
    "bottom": "штаны или юбку",
    "footwear": "обувь",
    "one_piece": "платье",
}


def _suggest_next_item(items: list, total_count: int) -> str:
    """Suggest next item to photograph based on missing wardrobe slots."""
    existing_groups = {getattr(i, "category_group", "") for i in items}

    if total_count == 1:
        return "🎉 Первая вещь! Ещё 2 — и покажу мини-образ."
    if total_count == 3:
        return "🎉 Уже можно собрать мини-образ!"
    if total_count == 8:
        return "🎉 Полный гардероб! Образы будут разнообразнее."

    for slot in _CORE_SLOTS:
        if slot not in existing_groups:
            name = _SLOT_SUGGEST_NAMES.get(slot, "вещь")
            return f"📸 Сфоткай {name}!"
    return ""


async def _safe_edit_text(message, text: str, **kwargs) -> None:
    """Edit message text with try/except, fallback to reply_text."""
    try:
        await message.edit_text(text, **kwargs)
    except Exception:
        try:
            await message.reply_text(text, **kwargs)
        except Exception:
            pass


# ── Owner helpers ──────────────────────────────────────────────────────────

async def _get_owner(user, context) -> tuple:
    """Получить текущего владельца гардероба. Приоритет: Redis owner_mode → segment."""
    redis = context.bot_data.get("redis")
    if redis:
        try:
            mode = await redis.get(f"owner_mode:{user.id}")
            if mode:
                mode = mode if isinstance(mode, str) else mode.decode()
                if mode == "user":
                    context.user_data["active_owner_type"] = "user"
                    return (user.id, "user")
                elif mode.startswith("child:"):
                    import uuid as _uuid
                    child_id = _uuid.UUID(mode[6:])
                    # Store child gender for menu icon
                    try:
                        async with AsyncReadSession() as _s:
                            from db.crud.children import get_children as _gc
                            _ch = await _gc(_s, user.id)
                            _c = next((c for c in _ch if c.id == child_id), None)
                            if _c:
                                context.user_data["active_owner_gender"] = _c.gender
                    except Exception:
                        pass
                    context.user_data["active_owner_type"] = "child"
                    return (child_id, "child")
        except Exception:
            pass

    async with AsyncReadSession() as session:
        from db.crud.children import get_children
        children = await get_children(session, user.id)

    if user.segment in ("mom_girl", "mom_boy") and children:
        context.user_data["active_owner_type"] = "child"
        context.user_data["active_owner_gender"] = children[0].gender
        return (children[0].id, "child")
    context.user_data["active_owner_type"] = "user"
    return (user.id, "user")


async def _get_scoring_matrix(redis, user, owner_id: uuid.UUID, owner_type: str):
    """Возвращает ScoringMatrix для owner или None если Redis недоступен."""
    if not redis:
        return None
    try:
        child = None
        if owner_type == "child":
            from db.models.child import Child
            from sqlalchemy import select as _sel
            async with AsyncReadSession() as session:
                result = await session.execute(_sel(Child).where(Child.id == owner_id))
                child = result.scalar_one_or_none()
        name = matrix_name_for_owner(user, child)
        async with AsyncReadSession() as session:
            svc = ScoringService(session, redis)
            return await svc.get_matrix(name)
    except Exception as e:
        logger.warning("scoring_matrix.load_failed", error=str(e))
        return None


async def _load_existing_set(owner_id: uuid.UUID, owner_type: str = "user") -> set:
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)
    return {
        (
            (i.type or "").lower().strip(),
            (i.color or "").lower().strip(),
            i.category_group or "top",
        )
        for i in items
    }


# ── Guided first 5 minutes (hints after each photo) ───────────────────────

_GUIDED_HINTS = {
    1: "🎉 Первая! Ещё 2 — покажу мини-образ.\n\n💡 Совет: расправь вещь на светлом фоне — образы будут красивее!",
    2: "Супер! Штаны или юбку? 👖",
    # 3 handled by milestone (mini_outfit)
}


async def _send_guided_hint(item_count: int, message) -> None:
    """Send appropriate hint based on item count (guided first 5 minutes)."""
    hint = _GUIDED_HINTS.get(item_count)
    if hint:
        try:
            await message.reply_text(hint)
        except Exception:
            pass


# ── Milestone rewards ─────────────────────────────────────────────────────

async def check_milestones(user, item_count: int, message, owner_id, owner_type, context) -> None:
    """Check and fire milestone rewards after adding items to wardrobe."""
    reached = list(user.milestones_reached or [])
    new_milestones = []

    # 3 items: mini outfit unlocked
    if item_count >= 3 and "mini_outfit" not in reached:
        new_milestones.append("mini_outfit")
        await message.reply_text("🎉 Мини-образ разблокирован!")
        # Generate mini card
        try:
            _redis = context.bot_data.get("redis") if context else None
            if _redis:
                from core.queue import RedisQueue, QueuePriority
                queue = RedisQueue(_redis)
                await queue.push(
                    "generate_brief",
                    {"user_id": str(user.id)},
                    priority=QueuePriority.HIGH,
                )
        except Exception as e:
            logger.warning("milestone.mini_outfit.failed", error=str(e))

    # 5 items: colortype prompt (only if colortype not already set)
    _has_colortype = getattr(user, "colortype", None)
    if item_count >= 5 and "colortype_prompt" not in reached and not _has_colortype:
        new_milestones.append("colortype_prompt")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Отправить селфи", callback_data="selfie_colortype_start")],
            [InlineKeyboardButton("Потом", callback_data="selfie_colortype_later")],
        ])
        await message.reply_text(
            "🎉 5 вещей! Хочешь точнее подбирать цвета? Пришли селфи!",
            reply_markup=keyboard,
        )

    # 8 items (mom): first full outfit
    segment = getattr(user, "segment", "no_kids") or "no_kids"
    if item_count >= 8 and segment in ("mom_girl", "mom_boy") and "full_outfit" not in reached:
        new_milestones.append("full_outfit")
        await message.reply_text("🎉 Первый полный образ!")
        try:
            _redis = context.bot_data.get("redis") if context else None
            if _redis:
                from core.queue import RedisQueue, QueuePriority
                queue = RedisQueue(_redis)
                await queue.push(
                    "generate_brief",
                    {"user_id": str(user.id)},
                    priority=QueuePriority.HIGH,
                )
        except Exception as e:
            logger.warning("milestone.full_outfit.failed", error=str(e))

    # 10 items (woman/no_kids): wardrobe collected
    if item_count >= 10 and segment in ("no_kids", "pregnant") and "wardrobe_collected" not in reached:
        new_milestones.append("wardrobe_collected")
        await message.reply_text(
            "🎉 Гардероб собран! Завтра утром — первый образ."
        )

    # Save new milestones
    if new_milestones:
        reached.extend(new_milestones)
        try:
            async with AsyncWriteSession() as session:
                await session.execute(
                    sa.update(User).where(User.id == user.id)
                    .values(milestones_reached=reached)
                )
                await session.commit()
            user.milestones_reached = reached
            logger.info("milestones.updated",
                user_id=str(user.id),
                new=new_milestones,
                total=reached,
            )
        except Exception as e:
            logger.error("milestones.save_failed", error=str(e))


# ── Selfie colortype detection ────────────────────────────────────────────

# Hex palettes for colortype card rendering
_COLORTYPE_CARD_HEX = {
    "spring": ["#FFD1A9", "#FF9966", "#FFCC66", "#99CC66", "#FFE0B2", "#FFAB91"],
    "summer": ["#B2A4D4", "#E8B4C8", "#A0C4D8", "#C8E0D8", "#D8C0D8", "#B0D0E0"],
    "autumn": ["#CC9933", "#CC6633", "#8B8B00", "#996633", "#CC9966", "#8B6914"],
    "winter": ["#FFFFFF", "#000000", "#3366CC", "#CC0066", "#C0C0C0", "#003366"],
}

_COLORTYPE_NAMES_RU = {
    "spring": "Весна 🌸",
    "summer": "Лето ☀️",
    "autumn": "Осень 🍂",
    "winter": "Зима ❄️",
}


async def handle_selfie_colortype_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: user tapped 'Отправить селфи' button."""
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_selfie"] = True
    await query.message.reply_text(
        "📸 Отправь селфи при дневном свете — я определю твой цветотип!\n"
        "Лучше без фильтров и макияжа."
    )


async def handle_selfie_colortype_later(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: user tapped 'Потом' on colortype prompt."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Хорошо! Когда будешь готова — зайди в Профиль → Цветотип 🎨")


async def handle_selfie_colortype_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: user picks colortype manually after low-confidence detection."""
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]  # spring/summer/autumn/winter
    user = context.user_data.get("db_user")
    if not user:
        return

    # Determine target: child for mom segments, user otherwise
    segment = getattr(user, "segment", "no_kids") or "no_kids"
    if segment in ("mom_girl", "mom_boy"):
        from db.crud.children import get_children
        async with AsyncReadSession() as session:
            children = await get_children(session, user.id)
        if children:
            child = children[0]
            from db.models.child import Child
            async with AsyncWriteSession() as session:
                await session.execute(
                    sa.update(Child).where(Child.id == child.id)
                    .values(colortype=choice)
                )
                await session.commit()
            target_name = child.name
        else:
            await _save_colortype_to_user(user, choice)
            target_name = user.name
    else:
        await _save_colortype_to_user(user, choice)
        target_name = user.name

    ct_label = _COLORTYPE_NAMES_RU.get(choice, choice)
    # Render colortype card
    card_bytes = await _build_colortype_card(target_name, choice)
    if card_bytes:
        from io import BytesIO
        await query.message.reply_photo(
            photo=BytesIO(card_bytes),
            caption=f"✨ {target_name} — {ct_label}\nТеперь буду подбирать цвета под твой цветотип!",
        )
    else:
        await query.message.reply_text(
            f"✨ {target_name} — {ct_label}\nТеперь буду подбирать цвета под твой цветотип!"
        )


async def _save_colortype_to_user(user, colortype: str) -> None:
    """Save colortype to user record."""
    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(User).where(User.id == user.id)
            .values(colortype=colortype)
        )
        await session.commit()
    user.colortype = colortype


async def _analyze_selfie_colortype(photo_bytes: bytes) -> dict:
    """Call Vision (Sonnet) to determine colortype from selfie. Returns {colortype, confidence}."""
    pool = get_anthropic_pool()
    prompt = (
        "Определи цветотип человека на фото. Анализируй тон кожи, цвет волос, контраст между ними.\n"
        'Ответь JSON: {"colortype": "spring"|"summer"|"autumn"|"winter", "confidence": 0.0-1.0}\n'
        "Только JSON, без пояснений."
    )
    try:
        response = await pool.create_message(
            model="claude-sonnet-4-6",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.standard_b64encode(photo_bytes).decode(),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            system="Ты эксперт по цветотипированию. Отвечай только JSON.",
            max_tokens=100,
        )
        text = response.content[0].text.strip()
        # Parse JSON from response
        import re as _re
        json_match = _re.search(r'\{[^}]+\}', text)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "colortype": result.get("colortype", "summer"),
                "confidence": float(result.get("confidence", 0.5)),
            }
        return {"colortype": "summer", "confidence": 0.0}
    except Exception as e:
        logger.warning("selfie_colortype.vision_failed", error=str(e))
        sentry_sdk.capture_exception(e)
        return {"colortype": "summer", "confidence": 0.0}


async def _build_colortype_card(name: str, colortype: str) -> bytes | None:
    """Render a colortype card via Satori: 440x300 with gradient, name, and 6 swatches."""
    from services.image_builder import _render_satori
    from services.brief_card import _div, _text, _row, _col

    hex_colors = _COLORTYPE_CARD_HEX.get(colortype, _COLORTYPE_CARD_HEX["summer"])
    ct_label = _COLORTYPE_NAMES_RU.get(colortype, colortype)

    # Gradient backgrounds per colortype
    _GRADIENTS = {
        "spring": ("linear-gradient(135deg, #FFF8E7, #FFE8D0)", "#8B6B4A"),
        "summer": ("linear-gradient(135deg, #F0E8F8, #E0F0F8)", "#5B4A6B"),
        "autumn": ("linear-gradient(135deg, #FFF0E0, #F0E0C8)", "#6B4A2A"),
        "winter": ("linear-gradient(135deg, #E8EDF8, #D8E0F0)", "#2A3A5B"),
    }
    gradient, text_color = _GRADIENTS.get(colortype, _GRADIENTS["summer"])

    # Build swatches
    swatches = []
    for hx in hex_colors[:6]:
        swatches.append(
            _div([], width=48, height=48, borderRadius=8,
                 backgroundColor=hx,
                 border="1px solid rgba(0,0,0,0.08)")
        )

    root = _div(
        [
            _col(
                [
                    _text(name, 24, text_color, fontWeight=700,
                          textAlign="center", justifyContent="center", width="100%"),
                    _text(ct_label, 18, text_color,
                          textAlign="center", justifyContent="center", width="100%",
                          marginTop=4),
                ],
                gap=4,
                alignItems="center",
                padding="24px 20px 8px",
            ),
            _text("Твоя палитра:", 13, text_color,
                  textAlign="center", justifyContent="center", width="100%",
                  opacity=0.7),
            _row(swatches, gap=10, justifyContent="center", padding="8px 20px"),
            _text("Буду учитывать при подборе образов", 12, text_color,
                  textAlign="center", justifyContent="center", width="100%",
                  opacity=0.5, padding="0 20px 16px"),
        ],
        flexDirection="column",
        width="100%",
        height="100%",
        backgroundImage=gradient,
        borderRadius=20,
        alignItems="center",
    )

    return await _render_satori(root, 440, 300)


async def _handle_selfie_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Process selfie photo for colortype detection. Returns True if handled."""
    if not context.user_data.get("awaiting_selfie"):
        return False

    context.user_data.pop("awaiting_selfie", None)
    user = context.user_data.get("db_user")
    if not user:
        return True

    await update.message.reply_text("🔍 Анализирую цветотип...")

    # Download photo
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    else:
        await update.message.reply_text("Отправь фото, а не файл 📸")
        context.user_data["awaiting_selfie"] = True
        return True

    try:
        photo_file = await context.bot.get_file(file_id)
        photo_ba = bytearray()
        await photo_file.download_as_bytearray(photo_ba)
        photo_bytes = bytes(photo_ba)
    except Exception as e:
        logger.warning("selfie.download_failed", error=str(e))
        await update.message.reply_text("Не удалось загрузить фото. Попробуй ещё раз 📸")
        context.user_data["awaiting_selfie"] = True
        return True

    # Analyze
    result = await _analyze_selfie_colortype(photo_bytes)
    colortype = result["colortype"]
    confidence = result["confidence"]

    logger.info("selfie_colortype.result",
        user_id=str(user.id),
        colortype=colortype,
        confidence=confidence,
    )

    # Determine target
    segment = getattr(user, "segment", "no_kids") or "no_kids"
    children = []
    if segment in ("mom_girl", "mom_boy"):
        from db.crud.children import get_children
        async with AsyncReadSession() as session:
            children = await get_children(session, user.id)
        target_name = children[0].name if children else user.name
    else:
        target_name = user.name

    if confidence >= 0.6:
        # High confidence — save directly
        if segment in ("mom_girl", "mom_boy") and children:
            from db.models.child import Child
            async with AsyncWriteSession() as session:
                await session.execute(
                    sa.update(Child).where(Child.id == children[0].id)
                    .values(colortype=colortype)
                )
                await session.commit()
        else:
            await _save_colortype_to_user(user, colortype)

        ct_label = _COLORTYPE_NAMES_RU.get(colortype, colortype)
        card_bytes = await _build_colortype_card(target_name, colortype)
        if card_bytes:
            from io import BytesIO
            await update.message.reply_photo(
                photo=BytesIO(card_bytes),
                caption=f"✨ {target_name} — {ct_label}\nТеперь буду подбирать цвета под твой цветотип!",
            )
        else:
            await update.message.reply_text(
                f"✨ {target_name} — {ct_label}\nТеперь буду подбирать цвета под твой цветотип!"
            )
    else:
        # Low confidence — offer manual choice
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Весна 🌸", callback_data="manual_colortype:spring"),
                InlineKeyboardButton("Лето ☀️", callback_data="manual_colortype:summer"),
            ],
            [
                InlineKeyboardButton("Осень 🍂", callback_data="manual_colortype:autumn"),
                InlineKeyboardButton("Зима ❄️", callback_data="manual_colortype:winter"),
            ],
        ])
        await update.message.reply_text(
            "🤔 Сложно определить точно по фото. Выбери свой цветотип:",
            reply_markup=keyboard,
        )

    return True


# ── Brief trigger ──────────────────────────────────────────────────────────

async def _maybe_trigger_first_brief(user, owner_id, owner_type, message, context, redis) -> None:
    """Триггер первого брифа ровно на 5-й вещи. Работает для ВСЕХ планов."""
    if redis is None:
        return
    lock_key = f"lock:first_brief:{user.id}"
    acquired = await redis.set(lock_key, "1", ex=86400, nx=True)
    if not acquired:
        return
    try:
        from db.crud.wardrobe import get_owner_items_count
        async with AsyncReadSession() as session:
            wardrobe_count = await get_owner_items_count(session, owner_id, owner_type)
        if wardrobe_count < 3:
            await redis.delete(lock_key)
            remaining = 3 - wardrobe_count
            if remaining == 1:
                suffix = "вещь"
            elif remaining < 5:
                suffix = "вещи"
            else:
                suffix = "вещей"
            await message.reply_text(f"📸 Ещё {remaining} {suffix} — и я соберу первый образ!")
            return
        from core.queue import RedisQueue, QueuePriority
        queue = RedisQueue(redis)
        await queue.push(
            "generate_brief",
            {"user_id": str(user.id)},
            priority=QueuePriority.HIGH,
        )
        await message.reply_text(
            "✨ У тебя уже 5 вещей! Собираю первый образ — подожди пару секунд..."
        )
        logger.info("wardrobe.first_brief_triggered", user_id=str(user.id), count=wardrobe_count)
    except Exception as e:
        logger.warning("wardrobe.first_brief_trigger_failed", error=str(e))


async def _upload_crop(
    photo_bytes: bytes,
    bbox: dict | None,
    owner_id: uuid.UUID | None = None,
    redis=None,
) -> tuple[str | None, bool]:
    """Кропит по bbox → удаляет фон → загружает PNG в R2."""
    if not bbox:
        return None, True
    try:
        crop_bytes = _crop_bbox(photo_bytes, bbox)
        from services.image_processor import remove_background
        png_bytes = await remove_background(crop_bytes, redis=redis)
        good_crop = _check_crop_quality(png_bytes)
        if not good_crop:
            logger.warning("wardrobe.crop.low_quality", action="show_in_collage=False")
        is_png = png_bytes[:4] == b'\x89PNG'
        ext = "png" if is_png else "jpg"
        content_type = "image/png" if is_png else "image/jpeg"
        from services.storage.r2_storage import get_r2_storage
        r2 = get_r2_storage()
        filename = f"{uuid.uuid4()}.{ext}"
        key = await r2.upload_photo(
            png_bytes, filename,
            owner_id=str(owner_id) if owner_id else "",
            content_type=content_type,
        )
        url = r2.get_public_url(key) if settings.cloudflare_r2_cdn_url else key
        return url, good_crop
    except Exception as e:
        logger.warning("wardrobe.crop_upload_failed", error=str(e))
        return None, True


RATE_LIMIT_FREE = 5
RATE_LIMIT_PREMIUM = 20


async def _save_one(
    owner_id: uuid.UUID,
    owner_type: str,
    photo_id: str,
    data: dict,
    matrix=None,
    photo_url: str | None = None,
    show_in_collage: bool = True,
    session=None,
) -> bool:
    """Сохраняет WardrobeItem.

    If ``session`` is provided, the item is added to that session (no commit).
    The caller is responsible for committing. If ``session`` is None, a new
    session is created and committed immediately (legacy behaviour).
    """
    category_group = data.get("category_group") or "top"
    if category_group not in _VALID_CATEGORY_GROUPS:
        category_group = "top"
    data["category_group"] = category_group

    raw_breakdown = data.get("score_breakdown") or {}
    if matrix and raw_breakdown:
        score_breakdown = raw_breakdown
        score_item = calc_item_score(raw_breakdown, matrix)
        score_version = "v3.0"
    else:
        score_breakdown, score_item = _default_score()
        score_version = "v1.0"

    from services.scoring import classify_role as _classify_role
    item_role = _classify_role(data.get("type") or "", data.get("color") or "")

    async def _do_create(s):
        return await create(
            s,
            owner_id=owner_id,
            owner_type=owner_type,
            photo_id=photo_id,
            photo_url=photo_url,
            category_group=category_group,
            category_code=data.get("category_code") or category_group,
            type=data.get("type") or "вещь",
            color=data.get("color") or "неизвестный",
            style=data.get("style") or "casual",
            brand=data.get("brand"),
            season=data.get("season") or ["spring", "summer", "autumn"],
            occasion=data.get("occasion") or ["everyday"],
            condition="новая",
            wear_count=0,
            keep=True,
            wishlist=False,
            quantity=1,
            show_in_collage=show_in_collage,
            is_base_layer=(category_group == "base_layer"),
            role=item_role,
            score_item=score_item,
            score_breakdown=score_breakdown,
            score_version=score_version,
            score_notes="",
        )

    try:
        item = None
        if session is not None:
            item = await _do_create(session)
        else:
            async with AsyncWriteSession() as s:
                item = await _do_create(s)
                await s.commit()
        return item.id if item else None
    except Exception as e:
        logger.error(
            "wardrobe.save_failed",
            error=str(e),
            exc_info=True,
            owner_id=str(owner_id),
            item_type=data.get("type"),
            category_group=category_group,
        )
        raise


# ── Ядро: анализ + сохранение одного фото ──────────────────────────────────

async def _analyze_and_save(
    photo_id: str,
    owner_id: uuid.UUID,
    owner_type: str,
    bot,
    matrix=None,
    redis=None,
) -> list[dict]:
    """Скачать фото → Claude Vision → сохранить WardrobeItem → enqueue bg removal.

    Background removal (crop + rembg + R2 upload) is deferred to the worker
    via rmbg_process task so the user gets an immediate response after Vision.
    All DB inserts happen inside a single transaction.
    """
    tg_file = await bot.get_file(photo_id)
    photo_bytes = bytes(await tg_file.download_as_bytearray())

    items_data = await _call_vision(photo_bytes)

    # Дедупликация: загружаем существующие вещи
    existing_set = await _load_existing_set(owner_id, owner_type)

    added: list[dict] = []
    # Collect (item_id, bbox) pairs for deferred bg removal
    rmbg_queue: list[tuple[uuid.UUID, dict | None]] = []

    async with AsyncWriteSession() as session:
        for data in items_data:
            cg = data.get("category_group") or "top"
            if cg not in _VALID_CATEGORY_GROUPS:
                cg = "top"
            data["category_group"] = cg

            key = _dedup_key(data)
            if key in existing_set:
                logger.info("wardrobe.dedup.skipped", type=data.get("type"), color=data.get("color"))
                continue

            _fix_bbox(data)
            bbox = data.get("bbox") or {}
            bw = float(bbox.get("w", 0.5))
            bh = float(bbox.get("h", 0.5))

            # Переклассификация: маленькая "шапка" → носки
            if (data.get("category_group") == "accessory" and
                    any(w in (data.get("type") or "").lower()
                        for w in ["шапка", "шапочка", "hat"]) and
                    bw <= 0.2 and bh <= 0.2):
                logger.info("wardrobe.reclassify",
                    from_type=data.get("type"), to_type="носки",
                    reason="small_bbox_accessory")
                data["category_group"] = "base_layer"
                data["type"] = "носки"

            # Save with original photo_id, no crop/rembg yet
            item_id = await _save_one(
                owner_id, owner_type, photo_id, data, matrix,
                photo_url=None, show_in_collage=True,
                session=session,
            )
            existing_set.add(key)
            added.append(data)
            if item_id:
                rmbg_queue.append((item_id, data.get("bbox")))

        # Commit all items in a single transaction
        if added:
            await session.commit()

    # Инвалидировать кеш wardrobe summary (after successful commit)
    if added and redis:
        try:
            await redis.delete(f"wardrobe_summary:{owner_id}")
        except Exception:
            pass

    # Enqueue background removal tasks (after commit, so items exist)
    if rmbg_queue and redis:
        try:
            from core.queue import RedisQueue, QueuePriority
            queue = RedisQueue(redis)
            for item_id, bbox in rmbg_queue:
                await queue.push(
                    "rmbg_process",
                    {
                        "item_id": str(item_id),
                        "file_id": photo_id,
                        "owner_id": str(owner_id),
                        "bbox": bbox,
                    },
                    priority=QueuePriority.HIGH,
                )
            logger.info("wardrobe.rmbg_enqueued", count=len(rmbg_queue))
        except Exception as e:
            logger.warning("wardrobe.rmbg_enqueue_failed", error=str(e))

    return added


# ── Оценка образа ───────────────────────────────────────────────────────────

async def _rate_photos(
    file_ids: list[str],
    mode: str,
    message,
    bot,
    owner_id: uuid.UUID | None = None,
    owner_type: str | None = None,
    db_user=None,
) -> None:
    try:
        if mode == "single":
            photo_bytes_list = []
            for file_id in file_ids:
                logger.info("rate.photo_source",
                    file_id=file_id[:20], source="telegram_original")
                tg_file = await bot.get_file(file_id)
                photo_bytes = bytes(await tg_file.download_as_bytearray())
                logger.info("rate.download_ok",
                    file_id=file_id[:20], size=len(photo_bytes))
                photo_bytes_list.append(photo_bytes)
            result = await _call_rate_vision(photo_bytes_list, owner_id=owner_id, owner_type=owner_type)
            await message.reply_text(result, reply_markup=get_main_menu(db_user))
        else:
            for i, file_id in enumerate(file_ids, 1):
                tg_file = await bot.get_file(file_id)
                photo_bytes = bytes(await tg_file.download_as_bytearray())
                result = await _call_rate_vision([photo_bytes], owner_id=owner_id, owner_type=owner_type)
                await message.reply_text(f"📷 Фото {i}:\n{result}", reply_markup=get_main_menu(db_user))
    except Exception as e:
        await message.reply_text("Не удалось оценить образ. Попробуй ещё раз.", reply_markup=get_main_menu(db_user))
        logger.error("rate_photos.error", error=str(e))
        sentry_sdk.capture_exception(e)


# ── UX: кнопки выбора действия ──────────────────────────────────────────────

async def _send_action_buttons(message, group_id: str) -> None:
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👜 В гардероб", callback_data=f"photo_action:add:{group_id}"),
        InlineKeyboardButton("⭐ Оценить образ", callback_data=f"photo_action:rate:{group_id}"),
    ]])
    await message.reply_text("Что делаем с фото?", reply_markup=keyboard)


async def _collect_and_ask(group_id: str, message, redis) -> None:
    """Ждём 3 сек (пока Telegram пришлёт все фото группы), потом спрашиваем."""
    await asyncio.sleep(3)
    try:
        raw_ids = await redis.lrange(f"media_group:{group_id}", 0, -1)
        file_ids = [fid.decode() if isinstance(fid, bytes) else fid for fid in raw_ids]
    except Exception as e:
        logger.error("collect_and_ask.redis_failed", error=str(e))
        return
    if not file_ids:
        return
    try:
        await redis.set(f"photo_pending:{group_id}", json.dumps(file_ids), ex=300)
    except Exception as e:
        logger.error("collect_and_ask.store_failed", error=str(e))
        return
    await _send_action_buttons(message, group_id)


# ── handle_photo ───────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    if not user.onboarding_completed:
        await update.message.reply_text("Сначала пройди настройку: /start")
        return

    # Selfie colortype detection mode
    if context.user_data.get("awaiting_selfie"):
        handled = await _handle_selfie_photo(update, context)
        if handled:
            return

    # Режим оценки образа (из кнопки меню)
    if context.user_data.get("awaiting_rate_photo"):
        context.user_data.pop("awaiting_rate_photo")

        # Проверить лимит оценок
        redis = context.bot_data.get("redis")
        from datetime import date as _date_rate
        today = _date_rate.today().isoformat()
        rate_key = f"rate_limit:{user.id}:{today}"
        effective_plan = get_effective_plan(user)
        rate_limit = get_limit("rate_per_day", effective_plan)
        rate_count = 0
        if redis:
            val = await redis.get(rate_key)
            rate_count = int(val) if val else 0
        if rate_count >= rate_limit:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
            ]])
            await update.message.reply_text(
                f"✋ Лимит оценок на сегодня ({rate_limit}/день).\n"
                f"Завтра снова доступно!",
                reply_markup=keyboard,
            )
            return

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id
        else:
            return
        owner_id, owner_type = await _get_owner(user, context)
        await update.message.reply_text("⭐ Оцениваю...")
        _track_task(
            _rate_photos([file_id], "single", update.message,
                         context.bot, owner_id=owner_id, owner_type=owner_type)
        )
        # Увеличить счётчик после запуска оценки
        if redis:
            await redis.incr(rate_key)
            await redis.expire(rate_key, 86400)
        return

    redis = context.bot_data.get("redis")

    # ── Лимиты: фото в день и размер гардероба ───────────────────────────────
    _effective_plan = get_effective_plan(user)
    if _effective_plan != "admin":
        # Первые 5 вещей — без лимита (онбординг через фото)
        _owner_id_check, _owner_type_check = await _get_owner(user, context)
        async with AsyncReadSession() as _session_check:
            _existing_items = await get_owner_items(_session_check, _owner_id_check, _owner_type_check)
        _skip_daily_limit = len(_existing_items) < 5

        from datetime import date as _date_ph
        _today_ph = _date_ph.today().isoformat()
        _photo_key = f"photos_day:{user.id}:{_today_ph}"
        _photo_count = 0
        if redis:
            _val = await redis.get(_photo_key)
            _photo_count = int(_val) if _val else 0
        _photo_limit = get_limit("photos_per_day", _effective_plan)
        if not _skip_daily_limit and _photo_count >= _photo_limit:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
            ]])
            await update.message.reply_text(
                f"📸 Добавлено {_photo_count}/{_photo_limit} фото сегодня.\n"
                f"Лимит восстановится завтра!",
                reply_markup=keyboard,
            )
            return

        # Проверить лимит размера гардероба (используем _existing_items уже загруженный выше)
        _wardrobe_limit = get_limit("wardrobe_size", _effective_plan)
        if len(_existing_items) >= _wardrobe_limit:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Расширить гардероб →", callback_data="show_upgrade")
            ]])
            if _effective_plan == "free":
                msg = t(
                    "wardrobe.full.free",
                    used=str(len(_existing_items)),
                    max=str(_wardrobe_limit),
                )
            else:
                msg = t(
                    "wardrobe.full",
                    used=str(len(_existing_items)),
                    max=str(_wardrobe_limit),
                )
            await update.message.reply_text(msg, reply_markup=keyboard)
            return

    # ── Trial активация при первом фото ──────────────────────────────────────
    if not getattr(user, "trial_started_at", None):
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        from sqlalchemy import update as _sa_update
        _now = _dt.now(_tz.utc)
        async with AsyncWriteSession() as _ts:
            _res = await _ts.execute(
                _sa_update(User)
                .where(User.id == user.id)
                .where(User.trial_started_at.is_(None))
                .values(trial_started_at=_now, trial_ends_at=_now + _td(days=14))
            )
            await _ts.commit()
        if _res.rowcount > 0:
            user.trial_started_at = _now
            user.trial_ends_at = _now + _td(days=14)
            logger.info("trial.activated", user_id=str(user.id))
            await update.message.reply_text(t("trial.activated"))

    # Подсказка про bulk upload — один раз, если гардероб пуст
    if redis:
        tip_key = f"shown_bulk_tip:{user.id}"
        if not await redis.get(tip_key):
            async with AsyncReadSession() as session:
                existing = await get_owner_items(session, user.id, "user")
            if not existing:
                await update.message.reply_text(
                    "💡 Советы для лучшего результата:\n"
                    "📱 Снимай вертикально\n"
                    "🗂 До 10 вещей на фото\n"
                    "💡 Раскладывай вещи так чтобы они не перекрывали друг друга"
                )
                await redis.set(tip_key, "1", ex=31_536_000)

    if not redis:
        # Redis недоступен — немедленное добавление в гардероб
        owner_id, owner_type = await _get_owner(user, context)
        effective_plan = get_effective_plan(user)
        limit = get_limit("photos_per_day", effective_plan)
        if limit != 9999 and user.daily_requests_used >= limit:
            await update.message.reply_text(get_limit_exceeded_msg(user))
            return
        await _handle_single_photo(update, context, user, owner_id, owner_type)
        return

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    else:
        return
    media_group_id = update.message.media_group_id

    if not media_group_id:
        # Одиночное фото — сохраняем pending и показываем кнопки
        group_id = str(uuid.uuid4())
        await redis.set(f"photo_pending:{group_id}", json.dumps([file_id]), ex=300)
        await _send_action_buttons(update.message, group_id)
    else:
        # Медиагруппа — собираем все фото за 3 сек, потом спрашиваем
        list_key = f"media_group:{media_group_id}"
        length = await redis.rpush(list_key, file_id)
        if length == 1:
            await redis.expire(list_key, 15)
            _track_task(
                _collect_and_ask(media_group_id, update.message, redis)
            )


# ── Одиночное фото (fallback без Redis) ─────────────────────────────────────

async def _handle_single_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    owner_id: uuid.UUID,
    owner_type: str,
) -> None:
    try:
        start = time.monotonic()
        photo_id = update.message.photo[-1].file_id

        redis = context.bot_data.get("redis")
        matrix = await _get_scoring_matrix(redis, user, owner_id, owner_type)
        added = await _analyze_and_save(photo_id, owner_id, owner_type, context.bot, matrix, redis=redis)

        new_count = user.daily_requests_used + 1
        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User).where(User.id == user.id)
                .values(daily_requests_used=new_count)
            )
            await session.commit()
        user.daily_requests_used = new_count

        duration_ms = int((time.monotonic() - start) * 1000)

        lines = []
        if added:
            # Guided first photos: counter + micro-praise
            async with AsyncReadSession() as _cnt_sess:
                _all_now = await get_owner_items(_cnt_sess, owner_id, owner_type)
            _total_now = len(_all_now)
            _first_outfit_threshold = 3

            if _total_now < _first_outfit_threshold:
                _left = _first_outfit_threshold - _total_now
                _praise = f"✅ {_item_label(added[0])}"
                if len(added) > 1:
                    for d in added[1:]:
                        _praise += f"\n✅ {_item_label(d)}"
                _praise += f"\n\nЕщё {_left} и соберу первый образ ({_total_now}/{_first_outfit_threshold})"
                lines.append(_praise)
            elif _total_now == _first_outfit_threshold:
                for d in added:
                    lines.append(f"✅ {_item_label(d)}")
                lines.append(f"\n🎉 Есть {_first_outfit_threshold} вещи! Собираю первый образ...")
            else:
                lines.append(f"✅ Добавила {len(added)} вещей:")
                for d in added:
                    lines.append(f"→ {_item_label(d)}")
        if not added:
            lines.append("🤔 На фото не найдено одежды")

        await update.message.reply_text("\n".join(lines))

        # Комментарий стилиста для первой добавленной вещи
        if added:
            try:
                from datetime import date
                from services.scoring_comment import generate_item_comment
                from services.scoring import classify_role
                first = added[0]
                _item_type = first.get("type") or "вещь"
                _item_color = first.get("color") or ""
                _role = classify_role(_item_type, _item_color)
                _pool = get_anthropic_pool()
                # Тон из матрицы
                _tone = ""
                if matrix and hasattr(matrix, "criteria"):
                    _tone = matrix.criteria.get("_tone") or ""
                # Информация о ребёнке/пользователе
                _child_name = _child_gender = _child_age = None
                if owner_type == "child":
                    try:
                        from db.crud.children import get_children
                        async with AsyncReadSession() as _cs:
                            _children = await get_children(_cs, user.id)
                        _ch = next((c for c in _children if c.id == owner_id), None)
                        if _ch:
                            _child_name = _ch.name
                            _child_gender = getattr(_ch, "gender", None)
                            _child_age = (date.today() - _ch.birthdate).days // 365 if _ch.birthdate else None
                    except Exception:
                        pass
                _colortype = getattr(user, "colortype", None)
                _comment = await generate_item_comment(
                    pool=_pool,
                    item_type=_item_type,
                    item_color=_item_color,
                    score=0.0,
                    role=_role,
                    colortype=_colortype,
                    colortype_match=True,
                    wardrobe_summary="",
                    gender=_child_gender,
                    age=_child_age,
                    child_name=_child_name,
                    tone=_tone,
                )
                await update.message.reply_text(f"💬 {_comment}")
            except Exception as _e:
                logger.warning("wardrobe.item_comment_failed", error=str(_e))

        # ── Guided hints for first items ──────────────────────────────────
        if added:
            await _send_guided_hint(_total_now, update.message)

        # ── Milestone rewards ──────────────────────────────────────────────
        if added and user.onboarding_completed:
            await check_milestones(user, _total_now, update.message, owner_id, owner_type, context)

        # ── Balance insight при milestone (каждые 10 вещей) ────────────────
        if added:
            try:
                from services.scoring import get_wardrobe_balance_insight
                async with AsyncReadSession() as _bi_sess:
                    _all_items = await get_owner_items(_bi_sess, owner_id, owner_type)
                _count = len(_all_items)
                if _count > 0 and _count % 10 == 0:
                    _insight = get_wardrobe_balance_insight(_all_items)
                    if _insight:
                        await update.message.reply_text(_insight)
            except Exception as _e:
                logger.warning("wardrobe.balance_insight_failed", error=str(_e))

        # ── Триггер первого брифа на 5-й вещи (для ВСЕХ юзеров) ────────────
        if added and user.onboarding_completed:
            await _maybe_trigger_first_brief(user, owner_id, owner_type, update.message, context, redis)

        usage = get_usage_str(user)
        if usage:
            await update.message.reply_text(usage)

        logger.info(
            "wardrobe.item.added",
            user_id=str(user.id),
            action="wardrobe.item.added",
            added=len(added),
            duration_ms=duration_ms,
        )
        if added:
            logger.info("metric.photo_added",
                user_id=str(user.id),
                item_count=_total_now,
                segment=user.segment,
            )

    except (RateLimitError, FashionBotError) as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        logger.error("wardrobe.photo.error", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)


# ── Callback: выбор действия с фото ─────────────────────────────────────────

async def handle_photo_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    action, group_id = parts[1], parts[2]

    user = context.user_data.get("db_user")
    if not user:
        return

    redis = context.bot_data.get("redis")
    if not redis:
        await query.edit_message_text("Сервис временно недоступен")
        return

    raw = await redis.get(f"photo_pending:{group_id}")
    if not raw:
        await query.edit_message_text("⏱ Время вышло. Отправь фото ещё раз.")
        return

    file_ids = json.loads(raw if isinstance(raw, str) else raw.decode())

    if action == "add":
        effective_plan = get_effective_plan(user)
        limit = get_limit("photos_per_day", effective_plan)
        if limit != 9999 and user.daily_requests_used >= limit:
            await query.edit_message_text(get_limit_exceeded_msg(user))
            return
        # Progressive: immediately show "Анализирую" before Vision starts
        await query.edit_message_text("✨ Анализирую фото...")
        _track_task(
            _process_media_group(
                file_ids=file_ids,
                user_id=str(user.id),
                message=query.message,
                bot=context.bot,
                context=context,
            )
        )

    elif action == "rate":
        owner_id, owner_type = await _get_owner(user, context)
        if len(file_ids) > 1:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("👗 Это один образ", callback_data=f"rate_mode:single:{group_id}"),
                InlineKeyboardButton("👗👗 Каждое фото отдельно", callback_data=f"rate_mode:each:{group_id}"),
            ]])
            await query.edit_message_text("Как оцениваем?", reply_markup=keyboard)
        else:
            await query.edit_message_text("⭐ Оцениваю...")
            _track_task(_rate_photos(file_ids, "single", query.message, context.bot, owner_id=owner_id, owner_type=owner_type))



# ── handle_rate_mode_text (кнопка Оценить образ из меню) ────────────────

async def handle_rate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    owner_id, owner_type = await _get_owner(user, context)

    if owner_type == "child":
        async with AsyncReadSession() as session:
            from db.models.child import Child as _Child
            from sqlalchemy import select as _sel
            _res = await session.execute(_sel(_Child).where(_Child.id == owner_id))
            _child = _res.scalar_one_or_none()
        name = _child.name if _child else "ребёнка"
        prompt = f"Оцениваю образ для <b>{name}</b> 👧\nПришли фото в полный рост!"
    else:
        prompt = "Оцениваю <b>твой</b> образ 👗\nПришли фото в полный рост!"

    context.user_data["awaiting_rate_photo"] = True
    await update.message.reply_text(prompt, parse_mode="HTML")


# ── Callback: режим оценки ───────────────────────────────────────────────────

async def handle_rate_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    mode, group_id = parts[1], parts[2]

    redis = context.bot_data.get("redis")
    raw = await redis.get(f"photo_pending:{group_id}") if redis else None
    if not raw:
        await query.edit_message_text("⏱ Время вышло. Отправь фото ещё раз.")
        return

    user = context.user_data.get("db_user")
    owner_id, owner_type = await _get_owner(user, context) if user else (None, None)

    file_ids = json.loads(raw if isinstance(raw, str) else raw.decode())
    await query.edit_message_text("⭐ Оцениваю...")
    db_user = context.user_data.get("db_user")
    _track_task(_rate_photos(file_ids, mode, query.message, context.bot, owner_id=owner_id, owner_type=owner_type, db_user=db_user))


# ── Обработка медиагруппы (добавление в гардероб) ──────────────────────────

async def _process_media_group(
    file_ids: list[str],
    user_id: str,
    message,
    bot,
    context,
) -> None:
    """Process photo(s) for wardrobe with progressive status messages.

    Single photo flow:
      1. "✨ Анализирую фото..." (already shown by caller)
      2. "👚 Кофта розовая! Сохраняю..."
      3. "✅ Кофта розовая добавлена! (3/8)" + CTA

    Multi-photo flow:
      ONE status message updated per photo with running results.

    Vision failure: "🤔 Не могу разобрать. Сфоткай ближе на светлом фоне?"
    """
    total_received = len(file_ids)
    if not total_received:
        return

    is_single = total_received == 1
    # For single photo, `message` is the already-sent "✨ Анализирую фото..." msg
    # that we will progressively edit.
    # For multi-photo, we need to create a new progress message.
    progress_msg = message if is_single else None

    # Загрузить актуального пользователя из БД
    try:
        uid = uuid.UUID(user_id)
        async with AsyncReadSession() as session:
            from sqlalchemy import select as _select
            result = await session.execute(_select(User).where(User.id == uid))
            user = result.scalar_one_or_none()
        if not user:
            return
    except Exception as e:
        logger.error("media_group.user_load_failed", error=str(e))
        return

    owner_id, owner_type = await _get_owner(user, context)

    # Проверка лимита
    effective_plan = get_effective_plan(user)
    limit = get_limit("photos_per_day", effective_plan)
    if limit != 9999:
        remaining = limit - user.daily_requests_used
        if remaining <= 0:
            if is_single:
                await _safe_edit_text(message, get_limit_exceeded_msg(user))
            else:
                await message.reply_text(get_limit_exceeded_msg(user))
            return
    else:
        remaining = total_received  # unlimited

    to_process = file_ids[:min(10, remaining)]
    total = len(to_process)
    skipped_limit = max(0, min(total_received, 10) - total)

    if not is_single:
        if total_received > 10:
            await _safe_edit_text(
                message,
                f"✨ Получила {total_received} фото — обработаю первые {total}. Анализирую...",
            )
            progress_msg = message
        else:
            await _safe_edit_text(
                message,
                f"✨ Получила {total_received} фото. Анализирую...",
            )
            progress_msg = message

    _redis = context.bot_data.get("redis") if context else None
    matrix = await _get_scoring_matrix(_redis, user, owner_id, owner_type)

    photo_lines: list[str] = []
    all_added_items: list[dict] = []  # track all added items for final message
    total_added = 0
    successful_photos = 0

    for i, file_id in enumerate(to_process):
        try:
            logger.info("wardrobe.processing", index=i, file_id=file_id[:20])

            # Multi-photo: update progress per photo
            if not is_single and total > 1:
                await _safe_edit_text(
                    progress_msg,
                    f"✨ Анализирую фото {i + 1} из {total}...",
                )

            logger.info("wardrobe.vision_start", index=i)
            tg_file = await bot.get_file(file_id)
            photo_bytes = bytes(await tg_file.download_as_bytearray())
            items_data = await _call_vision(photo_bytes)
            logger.info("wardrobe.vision_done", index=i, items_count=len(items_data))

            if not items_data:
                # Vision returned nothing
                if is_single:
                    await _safe_edit_text(
                        progress_msg,
                        "🤔 Не могу разобрать. Сфоткай ближе на светлом фоне?",
                    )
                    return
                else:
                    photo_lines.append(f"📷 Фото {i + 1}: одежды не найдено")
                    continue

            # Single photo: show what Vision found
            if is_single:
                first_label = _item_label(items_data[0])
                if len(items_data) > 1:
                    extra = f" и ещё {len(items_data) - 1}"
                else:
                    extra = ""
                await _safe_edit_text(
                    progress_msg,
                    f"👚 {first_label.capitalize()}{extra}! Сохраняю...",
                )

            # Дедупликация: загружаем актуальный набор вещей
            existing_set = await _load_existing_set(owner_id, owner_type)

            added: list[dict] = []
            rmbg_queue: list[tuple[uuid.UUID, dict | None]] = []
            async with AsyncWriteSession() as _batch_session:
                for data in items_data:
                    cg = data.get("category_group") or "top"
                    if cg not in _VALID_CATEGORY_GROUPS:
                        cg = "top"
                    data["category_group"] = cg

                    key = _dedup_key(data)
                    if key in existing_set:
                        logger.info("wardrobe.dedup.skipped", index=i, type=data.get("type"), color=data.get("color"))
                        continue

                    logger.info("wardrobe.save_start", index=i, item_type=data.get("type"))
                    _fix_bbox(data)
                    _bbox = data.get("bbox") or {}
                    _bw = float(_bbox.get("w", 0.5))
                    _bh = float(_bbox.get("h", 0.5))
                    if (data.get("category_group") == "accessory" and
                            any(w in (data.get("type") or "").lower()
                                for w in ["шапка", "шапочка", "hat"]) and
                            _bw <= 0.2 and _bh <= 0.2):
                        logger.info("wardrobe.reclassify",
                            from_type=data.get("type"), to_type="носки",
                            reason="small_bbox_accessory")
                        data["category_group"] = "base_layer"
                        data["type"] = "носки"
                    # Save with original photo_id, defer crop+rembg to worker
                    item_id = await _save_one(
                        owner_id, owner_type, file_id, data, matrix,
                        photo_url=None, show_in_collage=True,
                        session=_batch_session,
                    )
                    existing_set.add(key)
                    added.append(data)
                    if item_id:
                        rmbg_queue.append((item_id, data.get("bbox")))
                    logger.info("wardrobe.save_done", index=i)

                # Commit all items from this photo in one transaction
                if added:
                    await _batch_session.commit()

            # Enqueue bg removal for items from this photo
            if rmbg_queue and _redis:
                try:
                    from core.queue import RedisQueue, QueuePriority
                    _q = RedisQueue(_redis)
                    for _item_id, _bbox_data in rmbg_queue:
                        await _q.push(
                            "rmbg_process",
                            {
                                "item_id": str(_item_id),
                                "file_id": file_id,
                                "owner_id": str(owner_id),
                                "bbox": _bbox_data,
                            },
                            priority=QueuePriority.HIGH,
                        )
                    logger.info("wardrobe.rmbg_enqueued", index=i, count=len(rmbg_queue))
                except Exception as _eq:
                    logger.warning("wardrobe.rmbg_enqueue_failed", index=i, error=str(_eq))

            successful_photos += 1
            total_added += len(added)
            all_added_items.extend(added)

            if added:
                names = ", ".join(_item_label(d) for d in added)
                photo_lines.append(f"📷 Фото {i + 1}: {names}")
            else:
                photo_lines.append(f"📷 Фото {i + 1}: одежды не найдено")

            logger.info(
                "wardrobe.item.added",
                user_id=user_id,
                action="wardrobe.item.added",
                photo_index=i,
                added=len(added),
                bulk=True,
            )
        except Exception as e:
            if is_single:
                await _safe_edit_text(
                    progress_msg,
                    "🤔 Не могу разобрать. Сфоткай ближе на светлом фоне?",
                )
                logger.error("media_group.item_failed", index=i, error=str(e), exc_info=True)
                return
            photo_lines.append(f"📷 Фото {i + 1}: ❌ не удалось распознать")
            logger.error("media_group.item_failed", index=i, error=str(e), exc_info=True)

    for j in range(skipped_limit):
        photo_lines.append(f"📷 Фото {total + j + 1}: ⏭ пропущено (лимит запросов)")

    if successful_photos > 0:
        try:
            async with AsyncWriteSession() as session:
                await session.execute(
                    sa.update(User).where(User.id == uid)
                    .values(daily_requests_used=User.daily_requests_used + successful_photos)
                )
                await session.commit()
        except Exception as e:
            logger.error("media_group.counter_update_failed", error=str(e))

    # Инвалидировать кеш wardrobe summary (after all commits)
    if total_added > 0 and _redis:
        try:
            await _redis.delete(f"wardrobe_summary:{owner_id}")
        except Exception:
            pass

    # ── Final progress message ─────────────────────────────────────────
    _current_count = 0
    _all_items_now: list = []
    if total_added > 0:
        try:
            async with AsyncReadSession() as _cnt_sess2:
                _all_items_now = await get_owner_items(_cnt_sess2, owner_id, owner_type)
            _current_count = len(_all_items_now)
        except Exception:
            pass

    if is_single:
        # Single photo: final edit with result + count + CTA
        if total_added > 0 and all_added_items:
            _added_names = ", ".join(_item_label(d) for d in all_added_items)
            _final = f"✅ {_added_names.capitalize()} добавлена! ({_current_count}/8)"

            # CTA: suggest next item
            _cta = _suggest_next_item(_all_items_now, _current_count)
            if _cta:
                _final += f"\n{_cta}"

            await _safe_edit_text(progress_msg, _final)
        elif total_added == 0:
            await _safe_edit_text(
                progress_msg,
                "🤔 Не могу разобрать. Сфоткай ближе на светлом фоне?",
            )
    else:
        # Multi-photo: final summary
        summary = "\n".join(photo_lines)
        _final_multi = f"✅ Добавила {total_added} вещей из {total} фото:\n\n{summary}"
        if _current_count > 0:
            _cta = _suggest_next_item(_all_items_now, _current_count)
            if _cta:
                _final_multi += f"\n\n{_cta}"
        await _safe_edit_text(progress_msg, _final_multi)

    if total_added > 0:
        if _current_count > 0:
            logger.info("metric.photo_added",
                user_id=str(user.id),
                item_count=_current_count,
                segment=user.segment,
            )

        # Guided hints for first items (skip for single — CTA already shown)
        if not is_single and _current_count > 0:
            await _send_guided_hint(_current_count, message)

        # Milestone rewards
        if _current_count > 0 and user.onboarding_completed:
            await check_milestones(user, _current_count, message, owner_id, owner_type, context)

    # ── Триггер первого брифа на 5-й вещи (для ВСЕХ юзеров) ────────────
    if total_added > 0 and user.onboarding_completed:
        _redis2 = context.bot_data.get("redis") if context else None
        await _maybe_trigger_first_brief(user, owner_id, owner_type, message, context, _redis2)


# ── handle_wardrobe_menu (кнопка Гардероб в меню) ───────────────────────────

async def handle_wardrobe_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать гардероб — обзор с категориями, сезонами, переключением владельца."""
    user = context.user_data.get("db_user")
    if not user:
        return

    from bot.handlers.wardrobe_browser import (
        _build_overview_text, _build_overview_buttons, _get_children_info,
    )

    owner_id, owner_type = await _get_owner(user, context)

    # Owner name
    if owner_type == "user":
        owner_name = user.name or "Мой"
    else:
        async with AsyncReadSession() as session:
            from db.crud.children import get_children
            children = await get_children(session, user.id)
        child = next((c for c in children if c.id == owner_id), None)
        owner_name = child.name if child else "Ребёнок"

    async with AsyncReadSession() as session:
        all_items = await get_owner_items(session, owner_id, owner_type)

    has_children, child_name, child_id, child_gender = await _get_children_info(user)

    text = _build_overview_text(all_items, owner_name)
    markup = _build_overview_buttons(
        all_items,
        owner_type=owner_type,
        has_children=has_children,
        child_name=child_name,
        child_id=child_id,
        child_gender=child_gender,
    )

    await update.message.reply_text(text, reply_markup=markup)


async def handle_switch_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: переключить владельца, обновить кнопки в том же сообщении."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    import uuid as _uuid
    redis = context.bot_data.get("redis")
    parts = query.data.split(":")  # switch_owner:user OR switch_owner:child:{uuid}
    target = parts[1] if len(parts) > 1 else "child"
    child_id_str = parts[2] if len(parts) > 2 else None

    # Загрузить детей один раз для валидации и формирования кнопок
    async with AsyncReadSession() as session:
        from db.crud.children import get_children as _gc
        children = await _gc(session, user.id)

    if target == "user":
        new_owner_id = user.id
        new_owner_type = "user"
        owner_label = f"👩 Гардероб: {user.name}"
        context.user_data["active_owner_type"] = "user"
    elif target == "child" and child_id_str:
        try:
            child_id = _uuid.UUID(child_id_str)
        except ValueError:
            await query.answer("Ошибка: неверный ID")
            return
        child = next((c for c in children if c.id == child_id), None)
        if not child:
            await query.answer("Ребёнок не найден")
            return
        new_owner_id = child_id
        new_owner_type = "child"
        _child_icon = "👧" if child.gender == "girl" else "👦"
        owner_label = f"{_child_icon} Гардероб: {child.name}"
        context.user_data["active_owner_type"] = "child"
        context.user_data["active_owner_gender"] = child.gender
    else:
        return

    # Сохранить новый owner в кеш и Redis
    cache_key = f"owner:{user.id}"
    context.bot_data[cache_key] = (new_owner_id, new_owner_type)
    if redis:
        mode_val = f"child:{new_owner_id}" if new_owner_type == "child" else "user"
        await redis.set(f"owner_mode:{user.id}", mode_val, ex=86400 * 30)

    # Show updated overview with new owner
    from bot.handlers.wardrobe_browser import (
        _build_overview_text, _build_overview_buttons,
    )

    async with AsyncReadSession() as session:
        items = await get_owner_items(session, new_owner_id, new_owner_type)

    owner_name = owner_label.split(": ", 1)[-1] if ": " in owner_label else owner_label
    text = f"✅ Переключено\n\n{_build_overview_text(items, owner_name)}"

    has_children = bool(children)
    child_name = ""
    _child_id_btn = ""
    child_gender = "girl"
    if children:
        _c = children[0]
        child_name = _c.name
        _child_id_btn = str(_c.id)
        child_gender = _c.gender or "girl"

    new_markup = _build_overview_buttons(
        items,
        owner_type=new_owner_type,
        has_children=has_children,
        child_name=child_name,
        child_id=_child_id_btn,
        child_gender=child_gender,
    )

    try:
        await query.edit_message_text(text, reply_markup=new_markup)
    except Exception as e:
        if "not modified" not in str(e).lower():
            await query.message.reply_text(text, reply_markup=new_markup)


async def handle_add_items_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: подсказка как добавить вещи (при пустом гардеробе)."""
    query = update.callback_query
    await query.answer("📸 Пришли фото — добавлю в гардероб!", show_alert=False)



# ── handle_outfit_request (кнопка Образ дня из Гардероба) ───────────────────

async def _generate_outfit_for_user(message, user, context, exclude_ids: set | None = None) -> None:
    """Общая логика генерации образа. Вызывается из меню и из inline-кнопки гардероба."""
    redis = context.bot_data.get("redis")
    from datetime import date as _date, datetime as _datetime
    import random as _random

    today = _date.today().isoformat()
    limit_key = f"outfit_req:{user.id}:{today}"
    _ep_outfit = get_effective_plan(user)
    day_limit = get_limit("outfit_req_per_day", _ep_outfit)

    count = 0
    if redis:
        val = await redis.get(limit_key)
        count = int(val) if val else 0

    if count >= day_limit and _ep_outfit != "admin":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
        ]])
        await message.reply_text(
            f"✋ На сегодня лимит образов ({day_limit}/день).\n"
            "Следующий образ — завтра утром в 07:00 🌅",
            reply_markup=keyboard,
        )
        return

    await context.bot.send_chat_action(message.chat_id, "typing")
    status_msg = await message.reply_text("✨ Подбираю образ...")

    try:
        from services.weather import WeatherService

        # Найти детей
        async with AsyncReadSession() as session:
            from db.crud.children import get_children as _get_children
            children = await _get_children(session, user.id)

        is_no_kids = getattr(user, "segment", None) == "no_kids"

        if not children and not is_no_kids:
            try:
                await status_msg.delete()
            except Exception:
                pass
            await message.reply_text(
                "Добавь ребёнка в профиле чтобы получать образы 👧",
                reply_markup=get_main_menu(context.user_data.get("db_user"), context),
            )
            return

        child = children[0] if children else None

        # Погода — Open-Meteo (утро/день/вечер)
        temp_m, temp_e = 10.0, 12.0
        _weather_data: dict = {}
        try:
            if user.city:
                from services.brief_weather import _geocode_city, _get_weather
                _coords = await _geocode_city(user.city)
                if _coords:
                    _weather_data = await _get_weather(
                        _coords[0], _coords[1], user.timezone or "Europe/Vilnius"
                    )
                    temp_m = _weather_data.get("temp_morning") or 10.0
                    temp_e = _weather_data.get("temp_evening") or temp_m
                    logger.info("outfit_request.weather_ok",
                        city=user.city, temp_m=temp_m, temp_e=temp_e)
        except Exception as we:
            logger.warning("outfit_request.weather_failed",
                error=str(we), city=getattr(user, "city", None))

        # Вещи: для no_kids — из гардероба пользователя, иначе — ребёнка
        if child:
            owner_id_for_outfit, owner_type_for_outfit = child.id, "child"
            colortype_for_outfit = getattr(child, "colortype", None) or "default"
        else:
            owner_id_for_outfit, owner_type_for_outfit = user.id, "user"
            colortype_for_outfit = getattr(user, "colortype", None) or "default"

        async with AsyncReadSession() as session:
            items = await get_owner_items(session, owner_id_for_outfit, owner_type_for_outfit)

        if not items:
            try:
                await status_msg.delete()
            except Exception:
                pass
            await message.reply_text(
                "Гардероб пуст — добавь вещи через фото 📸",
                reply_markup=get_main_menu(context.user_data.get("db_user"), context),
            )
            return

        # Полностью случайный seed при каждом запросе
        import uuid as _uuid
        _random.seed(str(_uuid.uuid4()))

        # Накопленные исключения из Redis (все ранее показанные образы сегодня)
        shown_key = f"outfit_shown:{user.id}:{owner_id_for_outfit}"
        accumulated_ids: set = set(exclude_ids or [])
        if redis:
            try:
                raw_shown = await redis.smembers(shown_key)
                for raw in raw_shown:
                    try:
                        accumulated_ids.add(_uuid.UUID(raw.decode() if isinstance(raw, bytes) else raw))
                    except Exception:
                        pass
            except Exception:
                pass

        # Исключить ранее показанные. Сброс если осталось < половины гардероба.
        if accumulated_ids:
            items_shuffled = [i for i in items if i.id not in accumulated_ids]
            _min_remaining = max(3, len(items) // 2)
            if len(items_shuffled) < _min_remaining:
                if redis:
                    try:
                        await redis.delete(shown_key)
                    except Exception:
                        pass
                items_shuffled = list(items)
        else:
            items_shuffled = list(items)
        _random.shuffle(items_shuffled)

        today_date = _date.today()
        season = SEASONS[today_date.month]
        outfit = select_outfit(items_shuffled, season, today_date, temp_m, temp_e)

        regime = get_temp_regime(temp_m)
        all_slots = build_outfit_slots(
            outfit, child=child, temp=temp_m, colortype=colortype_for_outfit, regime=regime
        )

        _day_type = ("садик" if today_date.weekday() < 5 else "прогулка") if child else ""
        _collage_params = get_collage_params(
            child=child, user=user, temp=temp_m,
            temp_now=_weather_data.get("temp_now"),
            temp_day=_weather_data.get("temp_day"),
            temp_evening=_weather_data.get("temp_evening"),
            day_type=_day_type,
        )

        # Тёплый комментарий Касси
        scored = [float(i.score_item) for i in outfit.get("all_items", []) if i.score_item]
        has_ow = any(s["slot"] == "outerwear" and s.get("has_item") for s in all_slots)
        missing = [s["slot"] for s in all_slots if not s.get("has_item")]
        child_name_str = child.name if child else None
        # Count real photos & get first item description for single-item context
        _real_count = sum(1 for s in all_slots if s.get("has_item") and (s.get("photo_url") or s.get("photo_id")))
        _first_desc = ""
        if _real_count <= 1:
            for s in all_slots:
                if s.get("has_item"):
                    _first_desc = f"{s.get('item_type', '')} {s.get('item_color', '')}".strip().lower()
                    break
        # Get previous comment from Redis to avoid repetition
        _prev_comment = ""
        if redis:
            _prev_key = f"last_kassi_comment:{user.id}"
            try:
                _prev_raw = await redis.get(_prev_key)
                if _prev_raw:
                    _prev_comment = _prev_raw.decode() if isinstance(_prev_raw, bytes) else _prev_raw
            except Exception:
                pass
        if scored:
            avg = sum(scored) / len(scored)
            comment = _warm_outfit_comment(
                avg, child_name_str, temp_m, has_ow, missing,
                exclude_comment=_prev_comment, real_item_count=_real_count, first_item_desc=_first_desc,
            )
        else:
            comment = _warm_outfit_comment(
                6.0, child_name_str, temp_m, has_ow, missing,
                exclude_comment=_prev_comment, real_item_count=_real_count, first_item_desc=_first_desc,
            )
        # Store current comment in Redis for next re-roll
        if redis:
            try:
                await redis.set(f"last_kassi_comment:{user.id}", comment, ex=86400)
            except Exception:
                pass

        caption = ""  # всё на карточке

        # Новый brief card (Satori) — единственный путь рендеринга
        from services.brief_card import build_brief_card, get_brief_buttons
        collage_bytes = await build_brief_card(
            user=user,
            child=child,
            outfit=outfit,
            weather=_weather_data,
            outfit_slots=all_slots,
            advice_text=comment,
            colortype=colortype_for_outfit,
        )

        # Сохранить BriefLog для кнопок feedback
        from db.base import AsyncWriteSession as _AWS_outfit
        from db.crud.brief_log import create_log as _create_log_outfit
        _outfit_ids = [str(i.id) for i in outfit.get("all_items", []) if hasattr(i, "id")]
        try:
            async with _AWS_outfit() as _s_outfit:
                _log = await _create_log_outfit(
                    _s_outfit,
                    user_id=user.id,
                    date=today_date,
                    weather_summary=f"{temp_m}°C",
                    outfit_description=caption,
                    outfit_items=_outfit_ids,
                    is_wow=bool(scored and sum(scored) / len(scored) >= 8.0),
                )
                await _s_outfit.commit()
                _outfit_brief_id = str(_log.id)
        except Exception:
            _outfit_brief_id = ""

        if redis:
            await redis.incr(limit_key)
            await redis.expire(limit_key, 86400)
            try:
                shown_item_ids = [str(i.id) for i in outfit.get("all_items", []) if hasattr(i, "id")]
                if shown_item_ids:
                    await redis.sadd(shown_key, *shown_item_ids)
                    await redis.expire(shown_key, 86400)
            except Exception:
                pass

        # Кнопки по сегменту и количеству фото
        real_photos = sum(1 for s in all_slots if s.get("has_item") and (s.get("photo_url") or s.get("photo_id")))
        _segment = "mom" if user.segment in ("mom_girl", "mom_boy") else "woman"
        _missing = [s for s in all_slots
                    if not s.get("has_item")
                    and s.get("slot") not in ("underwear", "tights", "socks", "base_layer")]
        if _missing:
            _ms = _missing[0]
            from services.collage_styles import _get_placeholder_label as _gpl
            _first_missing = _ms.get("label") or _gpl(
                _ms.get("slot", "top"), _ms.get("gender", "girl"))
        else:
            _first_missing = ""

        _btn_dict = get_brief_buttons(
            segment=_segment,
            real_photo_count=real_photos,
            brief_id=_outfit_brief_id,
            first_missing_slot=_first_missing,
        )
        # Convert dict to InlineKeyboardMarkup
        _kbd_rows = []
        for row in _btn_dict.get("inline_keyboard", []):
            _kbd_rows.append([
                InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"])
                for b in row
            ])
        _outfit_markup = InlineKeyboardMarkup(_kbd_rows)

        # Delete status message before sending result
        try:
            await status_msg.delete()
        except Exception:
            pass

        if collage_bytes:
            await message.reply_photo(
                photo=collage_bytes, caption=caption, reply_markup=_outfit_markup
            )
        else:
            await message.reply_text(
                f"💡 {comment}" if comment else "Не удалось собрать коллаж. Попробуй позже.",
                reply_markup=_outfit_markup,
            )

    except Exception as e:
        logger.error("outfit_request.failed", error=str(e))
        import sentry_sdk as _sentry
        _sentry.capture_exception(e)
        try:
            await status_msg.edit_text("😔 Не получилось собрать образ. Попробуй ещё раз!")
        except Exception:
            await message.reply_text(
                "Не удалось собрать образ. Попробуй позже.",
                reply_markup=get_main_menu(context.user_data.get("db_user"), context),
            )


async def handle_outfit_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline-кнопка 'Образ дня' в гардеробе → генерация образа."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    await _generate_outfit_for_user(query.message, user, context)


async def handle_what_to_wear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка '✨ Что надеть' в главном меню → сразу генерирует образ."""
    user = context.user_data.get("db_user")
    if not user:
        return
    await _generate_outfit_for_user(update.message, user, context)


async def handle_ask_kassi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка '💬 Спросить Касси' → подсказка для чата."""
    user = context.user_data.get("db_user")
    from core.permissions import get_effective_plan as _gep, get_limit as _gl
    plan = _gep(user) if user else "free"
    chat_limit = _gl("chat_per_day", plan)
    await update.message.reply_text(
        "Напиши вопрос про стиль — помогу! 👗\n"
        f"(до {chat_limit} вопросов в день)",
        reply_markup=get_main_menu(context.user_data.get("db_user"), context),
    )


# ── handle_list ─────────────────────────────────────────────────────────────

async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    page = context.user_data.get("wardrobe_page", 0)
    await _show_wardrobe_page(update.message, user, page, context=context)
    usage = get_usage_str(user)
    if usage:
        await update.message.reply_text(usage)


async def handle_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback кнопка 📋 Посмотреть вещи из меню гардероба."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    context.user_data["wardrobe_page"] = 0
    await _show_wardrobe_page(query.message, user, 0, context=context)


async def handle_wardrobe_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    page = int(query.data.split(":")[2])
    context.user_data["wardrobe_page"] = page
    await _show_wardrobe_page(query.message, user, page, context=context)


async def _show_wardrobe_page(message, user, page: int, owner_id=None, owner_type=None, context=None) -> None:
    try:
        if owner_id is None:
            if context is not None:
                owner_id, owner_type = await _get_owner(user, context)
            else:
                owner_id, owner_type = user.id, "user"
        elif owner_type is None:
            owner_type = "user"
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, owner_id, owner_type)

        if not items:
            await message.reply_text(t("wardrobe.empty"))
            return

        total = len(items)

        paged = items[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
        paged_groups: dict[str, list] = {}
        for item in paged:
            paged_groups.setdefault(item.category_group, []).append(item)

        lines = [f"👗 Гардероб ({total} вещей)\n"]
        for group, group_items in paged_groups.items():
            label = _CATEGORY_LABELS.get(group, group)
            item_strs = []
            for i in group_items[:5]:
                parts = [f"{color_circle(i.color)} {i.type} {i.color}"]
                brand = getattr(i, "brand", None)
                if brand:
                    parts[0] += f" ({brand})"
                wc = getattr(i, "wear_count", 0) or 0
                if wc > 0:
                    parts.append(f"×{wc}")
                sc = getattr(i, "score_item", None)
                if sc is not None:
                    parts.append(score_to_text(float(sc)).split(" ", 1)[0])  # just emoji
                item_strs.append(" ".join(parts))
            lines.append(f"{label} ({len(group_items)}): {', '.join(item_strs)}")

        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton("← Назад", callback_data=f"wardrobe:page:{page - 1}"))
        if (page + 1) * PAGE_SIZE < total:
            buttons.append(InlineKeyboardButton("Ещё →", callback_data=f"wardrobe:page:{page + 1}"))

        await message.reply_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([buttons]) if buttons else None,
        )

    except Exception as e:
        await message.reply_text(t("error.generic"))
        logger.error("wardrobe.list.error", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)


# ── Upgrade flow ─────────────────────────────────────────────────────────────

async def handle_show_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать экран выбора плана."""
    query = update.callback_query
    await query.answer()
    from core.permissions import PRICES, ULTRA_FEATURES

    text = (
        "✨ Касси Premium\n\n"
        "📅 Бриф каждый день\n"
        "👗 Образ дня без ограничений\n"
        "📸 30 фото в день\n"
        "⭐ 20 оценок образа\n"
        "💬 20 вопросов стилисту\n"
        "👧 До 3 детей\n\n"
        "Выбери план:\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_monthly']['label']}",
            callback_data="subscribe:monthly",
        )],
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_quarterly']['label']}",
            callback_data="subscribe:quarterly",
        )],
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_yearly']['label']} ⭐",
            callback_data="subscribe:yearly",
        )],
        [InlineKeyboardButton("🔒 Ultra — скоро!", callback_data="show_ultra")],
    ])
    await query.message.reply_text(text, reply_markup=keyboard)


async def handle_show_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию об Ultra плане."""
    query = update.callback_query
    await query.answer()
    from core.permissions import ULTRA_FEATURES

    text = "💎 Касси Ultra — скоро!\n\nВ разработке:\n"
    for f in ULTRA_FEATURES:
        text += f"  {f}\n"
    text += "\nОставь контакт и мы уведомим о запуске!"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔔 Уведомить меня", callback_data="notify_ultra")
    ]])
    await query.message.reply_text(text, reply_markup=keyboard)


async def handle_notify_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Заглушка: пользователь хочет узнать про Ultra."""
    query = update.callback_query
    await query.answer("Отлично! Уведомим тебя первой 🎉")
    # TODO: сохранить в БД список желающих Ultra


async def handle_gap_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: gap_analysis → on-demand gap analysis."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    from core.permissions import get_effective_plan, can_gap_analysis
    plan = get_effective_plan(user)
    if not can_gap_analysis(plan):
        await query.message.reply_text(
            "📋 Анализ гардероба доступен в Premium!\n✨ Нажми «Подписка» для доступа."
        )
        return

    await query.message.reply_text("📋 Анализирую гардероб...")

    redis = context.bot_data.get("redis")
    owner_id, owner_type = await _get_owner(user, context)

    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    from services.gap_analysis import build_shopping_list, _get_current_season
    from services.i18n.ru import t
    from core.redis import get_redis

    result = await build_shopping_list(user, items, get_redis())

    if result is None:
        await query.message.reply_text(
            "📸 Добавь больше вещей в гардероб — нужно минимум 5 для анализа!"
        )
    elif result == "lock":
        await query.message.reply_text("⏳ Анализ уже выполняется, подожди немного...")
    elif result == "":
        await query.message.reply_text("✅ Гардероб укомплектован на этот сезон!")
    else:
        season = _get_current_season(user.timezone or "Europe/Vilnius")
        await query.message.reply_text(t("shopping.header", season=season, list=result))
