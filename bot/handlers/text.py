"""Text handler — stylist consultant."""
import time
import sentry_sdk
import structlog
import sqlalchemy as sa
from datetime import date
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.anthropic_client import get_anthropic_pool
from db.base import AsyncWriteSession
from db.models.user import User
from exceptions import FashionBotError, RateLimitError
from services.i18n.ru import t
from bot.handlers.menu import get_main_menu
from core.permissions import get_effective_plan, get_limit, is_trial_just_ended

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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    # Во время онбординга лимиты не применяются
    if not getattr(user, "onboarding_completed", True):
        return

    # ── Режим редактирования профиля (edit_city) ──────────────────────────
    editing = context.user_data.get("editing")
    editing_ts = context.user_data.get("editing_ts", 0)
    if editing and (time.time() - editing_ts) > 300:
        context.user_data.pop("editing", None)
        context.user_data.pop("editing_ts", None)
        editing = None

    if editing:
        text_input = update.message.text.strip()
        if text_input.lower() in ("отмена", "назад", "cancel", "/cancel"):
            context.user_data.pop("editing", None)
            context.user_data.pop("editing_ts", None)
            await update.message.reply_text("Отменено ✅")
            return
        if editing == "city":
            from services.brief_weather import _geocode_city
            coords = await _geocode_city(text_input)
            if not coords:
                await update.message.reply_text(
                    "Не нашла такой город 🤔\nПопробуй по-другому или напиши «отмена»"
                )
                return
            import sqlalchemy as _sa
            from db.models.user import User as _User
            async with AsyncWriteSession() as _sess:
                await _sess.execute(
                    _sa.update(_User).where(_User.id == user.id).values(city=text_input)
                )
                await _sess.commit()
            user.city = text_input
            redis = context.bot_data.get("redis")
            if redis:
                await redis.delete(f"weather:cache:{text_input}")
            context.user_data.pop("editing", None)
            context.user_data.pop("editing_ts", None)
            await update.message.reply_text(f"✅ Город обновлён: {text_input}")
            return
        return

    # ── Мини-онбординг добавления ребёнка ─────────────────────────────────
    adding_child = context.user_data.get("adding_child")
    if adding_child:
        text_input = update.message.text.strip()
        step = adding_child.get("step")

        if text_input.lower() in ("отмена", "назад", "cancel", "/cancel"):
            context.user_data.pop("adding_child", None)
            await update.message.reply_text("Отменено ✅")
            return

        if step == "name":
            adding_child["name"] = text_input
            adding_child["step"] = "birthdate"
            context.user_data["adding_child"] = adding_child
            await update.message.reply_text(
                "📅 Когда родилась?\nНапример: «15.03.2022» или «3 года» (или «отмена»)"
            )
            return

        if step == "birthdate":
            from bot.handlers.onboarding import parse_birthdate
            bd = parse_birthdate(text_input)
            if bd is None:
                await update.message.reply_text(
                    "Не понял дату 🤔 Попробуй: «15.03.2022», «2 года 3 месяца», или «отмена»"
                )
                return
            adding_child["birthdate"] = bd
            adding_child["step"] = "size"
            context.user_data["adding_child"] = adding_child
            await update.message.reply_text(
                "👕 Какой размер одежды? (например 92 или 104)\nИли напиши «пропустить»"
            )
            return

        if step == "size":
            if text_input.lower() not in ("пропустить", "skip", "-"):
                adding_child["size"] = text_input
            adding_child["step"] = "done"
            context.user_data["adding_child"] = adding_child
            from bot.handlers.profile import _finish_add_child
            await _finish_add_child(update.message, user, context)
            return

    # Лимит чата через Redis (отдельный от лимита фото)
    redis = context.bot_data.get("redis")
    effective_plan = get_effective_plan(user)
    chat_limit = get_limit("chat_per_day", effective_plan)
    today = date.today().isoformat()
    chat_key = f"chat_limit:{user.id}:{today}"
    chat_count = 0
    if redis:
        val = await redis.get(chat_key)
        chat_count = int(val) if val else 0

    if chat_count >= chat_limit and effective_plan != "admin":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
        ]])
        if is_trial_just_ended(user):
            msg = t("trial.expired")
        else:
            msg = (
                f"✋ Лимит вопросов на сегодня ({chat_limit}/день).\n"
                "Лимит восстановится завтра!"
            )
        await update.message.reply_text(msg, reply_markup=keyboard)
        return

    try:
        start = time.monotonic()
        pool = get_anthropic_pool()
        system = _get_text_system(user)

        # Добавить контекст гардероба в system prompt
        try:
            from bot.handlers.wardrobe import _get_owner
            from db.base import AsyncReadSession
            from services.outfit_builder import get_wardrobe_summary_cached
            _owner_id, _owner_type = await _get_owner(user, context)
            async with AsyncReadSession() as _wsess:
                _wardrobe_ctx = await get_wardrobe_summary_cached(
                    _owner_id, _owner_type, redis, _wsess
                )
            if _wardrobe_ctx and _wardrobe_ctx != "Гардероб пуст.":
                system += f"\n\nГардероб пользователя:\n{_wardrobe_ctx}"
                system += "\nОтвечай с учётом конкретных вещей. Предлагай реальные сочетания из этих вещей."
        except Exception:
            pass  # не критично — отвечаем без контекста

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
            suffix = "\n\n⚠️ Это последний вопрос на сегодня."
        elif remaining <= 2:
            suffix = f"\n\n💬 Осталось вопросов сегодня: {remaining}/{chat_limit}"
        else:
            suffix = ""

        await update.message.reply_text(f"{reply}{suffix}", reply_markup=get_main_menu())

        # Инкремент лимита чата
        if redis:
            await redis.incr(chat_key)
            await redis.expire(chat_key, 86400)

        # Инкремент общего счётчика
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
