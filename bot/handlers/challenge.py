"""Style Challenge: 5 outfits from 15 capsule items over 10 days.

Flexible deadline: 5 outfits at your pace within 10 days.
Free: 1/month. Premium: unlimited.
"""
import json
import uuid
import structlog
from collections import Counter
from datetime import date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db.base import AsyncReadSession
from db.crud.wardrobe import get_owner_items
from services.scoring import calc_item_versatility
from services.i18n import t, get_user_lang

logger = structlog.get_logger()

_CHALLENGE_CAPSULE = 15   # capsule size
_CHALLENGE_OUTFITS = 5    # target outfits
_CHALLENGE_DAYS = 10      # deadline days


def select_capsule(items: list, size: int = 15) -> list:
    """Select 15 items with max versatility and color diversity."""
    slots = {"top": 4, "bottom": 3, "outerwear": 2, "footwear": 2, "one_piece": 2, "accessory": 2}
    capsule = []
    used_colors: dict[str, int] = {}

    for category, count in slots.items():
        category_items = sorted(
            [i for i in items if getattr(i, "category_group", "") == category],
            key=lambda i: calc_item_versatility(i, items),
            reverse=True,
        )
        added = 0
        for item in category_items:
            if added >= count:
                break
            color = getattr(item, "color", "unknown") or "unknown"
            if used_colors.get(color, 0) >= 2:
                continue
            capsule.append(item)
            used_colors[color] = used_colors.get(color, 0) + 1
            added += 1

    return capsule[:size]


async def handle_challenge_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start capsule challenge."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    redis = context.bot_data.get("redis")
    if not redis:
        return

    # Check monthly limit
    from core.permissions import get_effective_plan
    plan = get_effective_plan(user)
    is_premium = plan in ("premium", "ultra", "admin")
    month_key = f"challenge_month:{user.id}:{date.today().strftime('%Y-%m')}"

    if not is_premium:
        val = await redis.get(month_key)
        if val and int(val) >= 1:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Premium", callback_data="show_upgrade"),
            ]])
            await query.message.reply_text(
                "🏆 1 challenge/мес в Free. В Premium — без лимита!",
                reply_markup=keyboard,
            )
            return

    # Load wardrobe
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, user.id, "user")

    visual = [i for i in items if getattr(i, "category_group", "") not in ("underwear", "base_layer")]
    if len(visual) < _CHALLENGE_CAPSULE:
        await query.message.reply_text(
            f"🏆 Для challenge нужно минимум {_CHALLENGE_CAPSULE} вещей. У тебя {len(visual)}.\n"
            f"📸 Добавь ещё {_CHALLENGE_CAPSULE - len(visual)} — и начнём!"
        )
        return

    capsule = select_capsule(visual, _CHALLENGE_CAPSULE)
    from services.wardrobe_math import calc_wardrobe_combos
    combos = calc_wardrobe_combos(capsule)

    challenge_data = {
        "capsule_ids": [str(i.id) for i in capsule],
        "completed": 0,
        "outfits_shown": [],
        "started_at": date.today().isoformat(),
        "deadline": (date.today() + timedelta(days=_CHALLENGE_DAYS)).isoformat(),
    }
    await redis.set(f"challenge:{user.id}", json.dumps(challenge_data), ex=(_CHALLENGE_DAYS + 1) * 86400)
    await redis.incr(month_key)
    await redis.expire(month_key, 32 * 86400)

    capsule_names = ", ".join(f"{i.type} {i.color}" for i in capsule[:8])
    await query.message.reply_text(
        f"🏆 Challenge начался!\n\n"
        f"Твоя капсула: {_CHALLENGE_CAPSULE} вещей → {combos} комбинаций!\n"
        f"{_CHALLENGE_OUTFITS} образов за {_CHALLENGE_DAYS} дней. Темп — твой.\n\n"
        f"Вещи: {capsule_names}...\n\n"
        f"Первый образ придёт в утреннем брифе! ✨"
    )
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    logger.info("challenge.started", user_id=str(user.id), capsule_size=len(capsule), combos=combos)


async def handle_challenge_later(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    lang = get_user_lang(user)
    try:
        await query.edit_message_text(t("challenge.later", lang))
    except Exception:
        pass


async def get_challenge_outfit_filter(user_id, redis) -> list[str] | None:
    """Check if user has active challenge. Returns capsule_ids or None."""
    if not redis:
        return None
    try:
        raw = await redis.get(f"challenge:{user_id}")
        if not raw:
            return None
        data = json.loads(raw if isinstance(raw, str) else raw.decode())
        if data["completed"] >= 5:
            return None
        deadline = date.fromisoformat(data["deadline"])
        if date.today() > deadline:
            await redis.delete(f"challenge:{user_id}")
            return None
        return data["capsule_ids"]
    except Exception:
        return None


async def record_challenge_outfit(user_id, outfit_item_ids: list[str], redis) -> str | None:
    """Record outfit in challenge. Returns status text if milestone."""
    if not redis:
        return None
    try:
        raw = await redis.get(f"challenge:{user_id}")
        if not raw:
            return None
        data = json.loads(raw if isinstance(raw, str) else raw.decode())
        data["completed"] += 1
        data["outfits_shown"].append(outfit_item_ids)
        day_num = data["completed"]

        if day_num >= 5:
            # Challenge complete!
            used_items = set()
            for outfit in data["outfits_shown"]:
                used_items.update(outfit)
            usage_pct = len(used_items) / len(data["capsule_ids"]) * 100
            await redis.delete(f"challenge:{user_id}")
            return (
                f"🏆 Challenge пройден!\n\n"
                f"{_CHALLENGE_OUTFITS} образов · {_CHALLENGE_CAPSULE} вещей · 0 покупок\n"
                f"Использовано {len(used_items)} из {_CHALLENGE_CAPSULE} ({usage_pct:.0f}%)\n\n"
                f"Твой шкаф мощнее чем кажется! ✨"
            )
        else:
            await redis.set(f"challenge:{user_id}", json.dumps(data), ex=11 * 86400)
            remaining = 5 - day_num
            return f"🏆 Challenge {day_num}/5 ✅ Ещё {remaining}!"
    except Exception as e:
        logger.warning("challenge.record_failed", error=str(e))
        return None
