"""Text handler — stylist consultant."""
import time
import sentry_sdk
import structlog
import sqlalchemy as sa
from telegram import Update
from telegram.ext import ContextTypes

from config import settings
from core.anthropic_client import get_anthropic_pool
from db.base import AsyncWriteSession
from db.models.user import User
from exceptions import FashionBotError, RateLimitError
from datetime import date
from services.i18n.ru import t
from bot.handlers.menu import get_main_menu
from services.usage import get_limit_exceeded_msg
from core.permissions import get_effective_plan, get_limit

logger = structlog.get_logger()

HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _get_text_system(user) -> str:
    segment = getattr(user, "segment", "no_kids") or "no_kids"
    colortype = getattr(user, "colortype", None)
    colortype_text = f"Цветотип пользователя: {colortype}." if colortype else ""

    if segment in ("mom_girl", "mom_boy"):
        gender = "девочки" if segment == "mom_girl" else "мальчика"
        context_line = (
            f"Пользователь — мама {gender}. "
            f"Отвечай про детскую и женскую моду. "
            f"{colortype_text}"
        )
    elif segment == "pregnant":
        context_line = (
            f"Пользователь беременна. "
            f"Отвечай про моду для беременных и будущих мам. "
            f"{colortype_text}"
        )
    else:  # no_kids
        context_line = (
            f"Пользователь без детей. "
            f"Отвечай ТОЛЬКО про взрослую моду и стиль. "
            f"НЕ упоминай детей, семью с детьми, детскую одежду. "
            f"{colortype_text}"
        )

    return (
        f"Ты Касси — дружелюбный персональный стилист. "
        f"{context_line}\n\n"
        f"Правила:\n"
        f"- Отвечай коротко (до 5 строк)\n"
        f"- Только про одежду и стиль\n"
        f"- Если вопрос не про одежду — вежливо скажи: "
        f"\"Я стилист, могу помочь только с вопросами про одежду и стиль 👗\"\n"
        f"- Используй эмодзи умеренно\n"
        f"- Говори на русском\n"
        f"- Тон: как подруга, не официально"
    )

_PLAN_LIMITS: dict[str, int] = {
    "free":    settings.daily_limits_free,
    "basic":   settings.daily_limits_basic,
    "family":  settings.daily_limits_family,
    "premium": -1,  # unlimited
}

CHAT_LIMIT_FREE = 5
CHAT_LIMIT_PREMIUM = 20



async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

<<<<<<< HEAD
    # Проверка дневного лимита (не применяется во время онбординга)
    if getattr(user, "onboarding_completed", True):
        limit = _PLAN_LIMITS.get(user.plan, settings.daily_limits_free)
        if limit != -1 and user.daily_requests_used >= limit:
            await update.message.reply_text(get_limit_exceeded_msg(user))
            return
=======
    # Лимит свободного чата (отдельный от лимита фото)
    redis = context.bot_data.get("redis")
    _ep_text = get_effective_plan(user)
    chat_limit = get_limit("chat_per_day", _ep_text)
    today = date.today().isoformat()
    chat_key = f"chat_limit:{user.id}:{today}"
    chat_count = 0
    if redis:
        val = await redis.get(chat_key)
        chat_count = int(val) if val else 0
    if chat_count >= chat_limit and _ep_text != "admin":
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
        ]])
        await update.message.reply_text(
            f"✋ Лимит вопросов на сегодня ({chat_limit}/день).\n"
            "Лимит восстановится завтра!",
            reply_markup=keyboard,
        )
        return

    # Проверка дневного лимита (фото/запросы)
    limit = _PLAN_LIMITS.get(user.plan, settings.daily_limits_free)
    if limit != -1 and user.daily_requests_used >= limit:
        await update.message.reply_text(get_limit_exceeded_msg(user))
        return
>>>>>>> 1d07f611829c008383f98f24d95e48e64a7b7bd7

    try:
        start = time.monotonic()
        pool = get_anthropic_pool()
        system = _get_text_system(user)
        response = await pool.create_message(
            model=HAIKU_MODEL,
            system=system,
            messages=[{"role": "user", "content": update.message.text}],
            max_tokens=512,
        )
        reply = response.content[0].text if response.content else t("error.generic")
        duration_ms = int((time.monotonic() - start) * 1000)

        # Суффикс — только когда мало осталось
        remaining = chat_limit - (chat_count + 1)
        if remaining == 0:
            suffix = f"\n\n⚠️ Это последний вопрос на сегодня."
        elif remaining <= 5:
            suffix = f"\n\n💬 Осталось вопросов сегодня: {remaining}/{chat_limit}"
        else:
            suffix = ""

        await update.message.reply_text(f"{reply}{suffix}", reply_markup=get_main_menu())

        # Инкремент лимита чата
        if redis:
            await redis.incr(chat_key)
            await redis.expire(chat_key, 86400)

        # Инкремент счётчика
        new_count = user.daily_requests_used + 1
        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User)
                .where(User.id == user.id)
                .values(daily_requests_used=new_count)
            )
            await session.commit()
        user.daily_requests_used = new_count

        logger.info(
            "stylist.response",
            user_id=str(user.id),
            action="stylist.text",
            duration_ms=duration_ms,
            requests_used=new_count,
        )
    except (RateLimitError, FashionBotError) as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        sentry_sdk.capture_exception(e)
