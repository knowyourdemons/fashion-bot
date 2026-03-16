"""Wardrobe handlers."""
import base64
import json
import time

import sentry_sdk
import structlog
import sqlalchemy as sa
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import settings
from core.anthropic_client import get_anthropic_pool
from db.base import AsyncWriteSession, AsyncReadSession
from db.crud.wardrobe import create, get_owner_items
from db.models.user import User
from exceptions import FashionBotError, RateLimitError
from services.i18n.ru import t

logger = structlog.get_logger()

_VALID_CATEGORY_GROUPS = {
    "outerwear", "top", "bottom", "one_piece", "footwear",
    "accessory", "base_layer", "sportswear", "special",
    "home_beach", "pregnant_specific",
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
}

_PLAN_LIMITS = {
    "free":    settings.daily_limits_free,
    "basic":   settings.daily_limits_basic,
    "family":  settings.daily_limits_family,
    "premium": -1,
}

PAGE_SIZE = 20

_VISION_SYSTEM = (
    "Ты стилист. Проанализируй вещь на фото. Верни ТОЛЬКО JSON без markdown:\n"
    '{"type":"...","color":"...","style":"...",'
    '"category_group":"outerwear|top|bottom|one_piece|footwear|accessory|base_layer|sportswear|special",'
    '"category_code":"...","season":["winter|spring|summer|autumn"],'
    '"occasion":["everyday|sport|formal|home|outdoor"],"brand":null}\n'
    "season: [winter/spring/summer/autumn], occasion: [everyday/sport/formal/home/outdoor]"
)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    if not user.onboarding_completed:
        await update.message.reply_text("Сначала пройди настройку: /start")
        return

    limit = _PLAN_LIMITS.get(user.plan, settings.daily_limits_free)
    if limit != -1 and user.daily_requests_used >= limit:
        await update.message.reply_text(t("error.rate_limit"))
        return

    try:
        start = time.monotonic()
        photo_id = update.message.photo[-1].file_id

        file = await context.bot.get_file(photo_id)
        photo_bytes = bytes(await file.download_as_bytearray())

        pool = get_anthropic_pool()
        response = await pool.create_message(
            system=_VISION_SYSTEM,
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
                    {"type": "text", "text": "Что за вещь?"},
                ],
            }],
            max_tokens=512,
        )

        raw = response.content[0].text.strip() if response.content else "{}"
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("wardrobe.json_parse_failed", raw=raw[:200], user_id=str(user.id))
            data = {}

        category_group = data.get("category_group", "top")
        if category_group not in _VALID_CATEGORY_GROUPS:
            category_group = "top"

        score_breakdown = {
            "safety": 1, "practicality": 1, "durability": 1,
            "age_authenticity": 1, "ease_of_care": 1, "colortype": 1,
            "comfort": 1, "versatility": 1, "condition": 1,
            "size_fit_score": 1, "seasonality": 1,
        }
        score_item = round((sum(score_breakdown.values()) / 15) * 10, 2)

        async with AsyncWriteSession() as session:
            await create(
                session,
                owner_id=user.id,
                owner_type="user",
                photo_id=photo_id,
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
                show_in_collage=True,
                is_base_layer=(category_group == "base_layer"),
                score_item=score_item,
                score_breakdown=score_breakdown,
                score_version="v1.0",
                score_notes="",
            )
            await session.commit()

        new_count = user.daily_requests_used + 1
        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User).where(User.id == user.id)
                .values(daily_requests_used=new_count)
            )
            await session.commit()
        user.daily_requests_used = new_count

        duration_ms = int((time.monotonic() - start) * 1000)
        season_str = ", ".join(data.get("season") or [])
        await update.message.reply_text(
            f"✅ Добавила!\n"
            f"👔 {data.get('type', 'вещь')}: {data.get('color', '')}, {data.get('style', '')}\n"
            f"📦 Сезон: {season_str}"
        )
        logger.info(
            "wardrobe.item.added",
            user_id=str(user.id),
            action="wardrobe.item.added",
            category=category_group,
            duration_ms=duration_ms,
        )

    except (RateLimitError, FashionBotError) as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        logger.error("wardrobe.photo.error", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)


async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    page = context.user_data.get("wardrobe_page", 0)
    await _show_wardrobe_page(update.message, user, page)


async def handle_wardrobe_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    page = int(query.data.split(":")[2])
    context.user_data["wardrobe_page"] = page
    await _show_wardrobe_page(query.message, user, page)


async def _show_wardrobe_page(message, user, page: int) -> None:
    try:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, user.id, "user")

        if not items:
            await message.reply_text(t("wardrobe.empty"))
            return

        total = len(items)
        scored = [float(i.score_item) for i in items if i.score_item]
        avg_score = round(sum(scored) / len(scored), 1) if scored else 0

        paged = items[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
        paged_groups: dict[str, list] = {}
        for item in paged:
            paged_groups.setdefault(item.category_group, []).append(item)

        lines = [f"👗 Гардероб ({total} вещей) · ⭐ средний скор: {avg_score}\n"]
        for group, group_items in paged_groups.items():
            label = _CATEGORY_LABELS.get(group, group)
            names = ", ".join(f"{i.color} {i.type}" for i in group_items[:5])
            lines.append(f"{label} ({len(group_items)}): {names}")

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
