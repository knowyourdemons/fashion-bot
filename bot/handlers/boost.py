"""Outfit Confidence Boost — positive-only outfit feedback before going out.

NO numeric score. Only warmth, confidence, and 1 soft suggestion.
"""
import structlog
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = structlog.get_logger()


async def handle_boost_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Button '💪 Как я?' → enable boost mode for next photo."""
    user = context.user_data.get("db_user")
    if not user:
        return

    # Limit check
    from core.permissions import get_effective_plan
    plan = get_effective_plan(user)
    is_premium = plan in ("premium", "ultra", "admin")
    redis = context.bot_data.get("redis")

    if not is_premium and redis:
        week_key = f"boost:{user.id}:{date.today().isocalendar()[1]}"
        val = await redis.get(week_key)
        if val and int(val) >= 2:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Premium", callback_data="show_upgrade"),
            ]])
            await update.message.reply_text(
                "💪 2 boost/неделю в Free. В Premium — без лимита!",
                reply_markup=keyboard,
            )
            return

    context.user_data["mode"] = "boost"
    await update.message.reply_text(
        "📸 Сфоткай себя в образе — скажу как ты!\n\n"
        "Зеркальное селфи или фото в полный рост 🪞"
    )


async def process_boost_photo(update, context, user, photo_bytes: bytes) -> bool:
    """Process photo in boost mode. Returns True if handled."""
    if context.user_data.get("mode") != "boost":
        return False

    context.user_data.pop("mode", None)

    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    status = await update.message.reply_text("✨ Оцениваю образ...")

    try:
        import base64
        from core.anthropic_client import get_anthropic_pool

        pool = get_anthropic_pool()

        # Build boost-specific prompt
        style_prefs = getattr(user, "style_preferences", None) or {}
        style_type = style_prefs.get("style_type", "")
        colortype = getattr(user, "colortype", None) or ""

        system = (
            "Ты Касси — подруга-стилист. Твоя задача: boost confidence.\n\n"
            "ПРАВИЛА:\n"
            "- НАЧНИ с восторга: 'Огонь!', 'Вау!', 'Красота!' и т.д.\n"
            "- Отметь 1-2 КОНКРЕТНЫХ плюса (цвет, силуэт, сочетание)\n"
            "- Если хочешь дать совет — ТОЛЬКО 1, мягко: 'Шарфик добавит изюминку!'\n"
            "- Заверши уверенностью: 'Смело иди!', 'Ты готова!'\n"
            "- НЕ давай цифровой score. НИКОГДА.\n"
            "- Максимум 3 предложения.\n"
            "- ЗАПРЕЩЕНО: 'не хватает', 'нужно', 'должна', 'плохо'\n"
        )
        if colortype:
            system += f"\nЦветотип: {colortype}."
        if style_type:
            from bot.handlers.style_quiz import STYLE_TYPES
            st = STYLE_TYPES.get(style_type)
            if st:
                system += f"\nСтиль: {st['label']}. Используй слова: {', '.join(st['tone_words'])}."

        b64 = base64.standard_b64encode(photo_bytes).decode()
        response = await pool.create_message(
            model="claude-sonnet-4-6",
            system=system,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": "Как мне этот образ?"},
                ],
            }],
            max_tokens=200,
        )

        comment = response.content[0].text.strip() if response.content else "Огонь! Ты готова! 🔥"

        # Increment counter
        redis = context.bot_data.get("redis")
        if redis:
            week_key = f"boost:{user.id}:{date.today().isocalendar()[1]}"
            try:
                await redis.incr(week_key)
                await redis.expire(week_key, 8 * 86400)
            except Exception:
                pass

        try:
            await status.delete()
        except Exception:
            pass

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Спасибо!", callback_data="noop"),
            InlineKeyboardButton("📤 Спросить подругу", callback_data="ask_friend:boost"),
        ]])
        await update.message.reply_text(f"💪 {comment}", reply_markup=keyboard)

        logger.info("boost.done", user_id=str(user.id))

    except Exception as e:
        logger.error("boost.error", error=str(e))
        try:
            await status.edit_text("Огонь! Ты отлично выглядишь! 🔥 Смело иди!")
        except Exception:
            pass

    return True
