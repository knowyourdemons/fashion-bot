"""Примерочная на ходу — fit check для вещей из магазина.

Premium only. Юзер фоткает вещь в магазине → Касси проверяет:
дубликаты, цветовая совместимость, gap analysis, С ЧЕМ носить.
"""
import structlog
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = structlog.get_logger()

_FITTING_LIMIT = 5  # per month


async def handle_fitting_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка '🛍 Подойдёт?' → включить fitting mode."""
    user = context.user_data.get("db_user")
    if not user:
        return

    # Premium check
    from core.permissions import get_effective_plan
    plan = get_effective_plan(user)
    if plan not in ("premium", "ultra", "admin"):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Premium", callback_data="show_upgrade"),
        ]])
        await update.message.reply_text(
            "🛍 Примерочная — Premium фича!\n\n"
            "Фоткай вещь в магазине → Касси скажет, подходит ли к твоему гардеробу.",
            reply_markup=keyboard,
        )
        return

    # Monthly limit
    redis = context.bot_data.get("redis")
    month_key = f"fitting:{user.id}:{date.today().strftime('%Y-%m')}"
    count = 0
    if redis:
        try:
            val = await redis.get(month_key)
            count = int(val) if val else 0
        except Exception:
            pass

    if count >= _FITTING_LIMIT:
        await update.message.reply_text(
            f"🛍 Лимит примерочной: {_FITTING_LIMIT}/мес. Попробуй в следующем месяце!"
        )
        return

    context.user_data["mode"] = "fitting"
    await update.message.reply_text(
        "📸 Сфоткай вещь в магазине — скажу, подходит ли к твоему гардеробу!\n\n"
        "Фоткай одну вещь на светлом фоне."
    )


async def process_fitting_photo(update, context, user, photo_bytes: bytes) -> bool:
    """Process photo in fitting mode. Returns True if handled."""
    if context.user_data.get("mode") != "fitting":
        return False

    context.user_data.pop("mode", None)

    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    status = await update.message.reply_text("✨ Анализирую...")

    try:
        from services.vision import _call_vision
        from services.color_harmony import color_compatibility
        from services.gap_analysis import get_wardrobe_gaps_simple
        from db.base import AsyncReadSession
        from db.crud.wardrobe import get_owner_items
        from core.anthropic_client import get_anthropic_pool

        # 1. Vision — определить вещь
        vision_result = await _call_vision(photo_bytes)
        if not vision_result:
            await status.edit_text("🤔 Не могу разобрать вещь. Попробуй сфоткать ближе.")
            return True

        item_data = vision_result[0] if isinstance(vision_result, list) else vision_result
        new_type = item_data.get("type", "вещь")
        new_color = item_data.get("color", "")
        new_category = item_data.get("category_group", "top")

        # 2. Load wardrobe
        async with AsyncReadSession() as session:
            wardrobe = await get_owner_items(session, user.id, "user")

        # 3. Duplicates
        similar = [
            i for i in wardrobe
            if (i.type or "").lower() == new_type.lower()
            and (i.color or "").lower() == new_color.lower()
        ]
        similar_type = [
            i for i in wardrobe
            if (i.type or "").lower() == new_type.lower()
        ]

        # 4. Color compatibility
        compatible = []
        for item in wardrobe:
            if item.category_group in ("underwear", "base_layer"):
                continue
            try:
                score = color_compatibility(new_color, item.color or "")
                if score > 0:
                    compatible.append(f"{item.type} {item.color}")
            except Exception:
                pass

        # 5. Gap check
        has_category = sum(1 for i in wardrobe if i.category_group == new_category)

        # 6. Haiku comment
        pool = get_anthropic_pool()
        dup_text = f"{len(similar)} точных совпадений, {len(similar_type)} таких же типов" if similar else "нет дубликатов"
        compat_text = ", ".join(compatible[:5]) if compatible else "мало совпадений"
        gap_text = f"В категории '{new_category}' уже {has_category} вещей"

        prompt = (
            f"Юзер хочет купить: {new_type} {new_color}.\n\n"
            f"Дубликаты: {dup_text}.\n"
            f"Сочетается с: {compat_text}.\n"
            f"{gap_text}.\n\n"
            f"Ответь 2-3 предложения как подруга-стилист:\n"
            f"- Если дубликат: мягко предупреди\n"
            f"- Если подходит: скажи С ЧЕМ из гардероба носить\n"
            f"- Позитивный тон, без 'нужно/должна/обязательно'"
        )

        resp = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        comment = resp.content[0].text.strip() if resp.content else "Хорошая вещь!"

        # Increment counter
        redis = context.bot_data.get("redis")
        if redis:
            month_key = f"fitting:{user.id}:{date.today().strftime('%Y-%m')}"
            try:
                await redis.incr(month_key)
                await redis.expire(month_key, 32 * 86400)
            except Exception:
                pass

        try:
            await status.delete()
        except Exception:
            pass

        result_text = f"🛍 {new_type} {new_color}\n\n{comment}"
        await update.message.reply_text(result_text)

        logger.info("fitting.done",
                     user_id=str(user.id),
                     type=new_type, color=new_color,
                     duplicates=len(similar),
                     compatible=len(compatible))

    except Exception as e:
        logger.error("fitting.error", error=str(e))
        try:
            await status.edit_text("🤔 Не удалось проанализировать. Попробуй ещё раз.")
        except Exception:
            pass

    return True
