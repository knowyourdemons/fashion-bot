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
from services.i18n import t, get_user_lang
from bot.handlers.menu import get_main_menu
from core.permissions import get_effective_plan, get_limit, is_trial_just_ended

logger = structlog.get_logger()

HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _get_text_system(user, weather_line: str = "") -> str:
    name = getattr(user, "name", "").split()[0] if getattr(user, "name", "") else ""
    segment = getattr(user, "segment", "no_kids") or "no_kids"
    city = getattr(user, "city", None)
    colortype = getattr(user, "colortype", None)
    body_type = getattr(user, "body_type", None)

    # Контекст сегмента
    if segment in ("mom_girl", "mom_boy"):
        gender = "девочки" if segment == "mom_girl" else "мальчика"
        segment_text = f"мама {gender}"
    elif segment == "pregnant":
        segment_text = "беременна"
    else:
        segment_text = "без детей"

    # Профиль пользователя
    profile_parts = [f"Имя: {name}" if name else None,
                     f"сегмент: {segment_text}",
                     f"город: {city}" if city else None,
                     f"цветотип: {colortype} (упоминай подходящие цвета при советах)" if colortype else "цветотип: не определён",
                     f"тип фигуры: {body_type}" if body_type else None]
    profile_line = ", ".join(p for p in profile_parts if p)

    # Ограничения по сегменту
    if segment in ("mom_girl", "mom_boy"):
        segment_rule = "Отвечай про детскую и женскую моду."
    elif segment == "pregnant":
        segment_rule = "Отвечай про моду для беременных и будущих мам."
    else:
        segment_rule = "Отвечай ТОЛЬКО про взрослую моду и стиль. НЕ упоминай детей."

    weather_part = f"\nПогода сейчас: {weather_line}" if weather_line else ""

    return (
        f"Ты Касси — подруга-стилист. Говоришь тепло и с энтузиазмом.\n"
        f"{profile_line}\n"
        f"{segment_rule}{weather_part}\n\n"
        f"Правила:\n"
        f"- Максимум 2-3 предложения. Короче = лучше.\n"
        f"- Предлагай конкретные вещи из гардероба юзера\n"
        f"- Только про одежду и стиль\n"
        f"- Если вопрос не про одежду — вежливо скажи: "
        f"\"Я стилист, могу помочь только с вопросами про одежду и стиль 👗\"\n"
        f"- ЗАПРЕЩЁННЫЕ слова: критически, обязательно, срочно, не хватает, нужно, должна, нельзя\n"
        f"- ВМЕСТО ЭТОГО: попробуй, добавь, будет здорово, классно смотрится\n"
        f"- Позитивный framing всегда\n"
        f"- Говори на русском\n"
        f"- Тон: {'тёплый, про комфорт и практичность' if segment in ('mom_girl', 'mom_boy') else 'стильный, про сочетания и тренды'}"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    # Во время онбординга и сразу после его завершения — пропускаем
    if not getattr(user, "onboarding_completed", True):
        return
    if context.user_data.pop("onboarding_just_completed", False):
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
            from telegram import ReplyKeyboardRemove
            await update.message.reply_text(
                f"✅ Город обновлён: {text_input}",
                reply_markup=ReplyKeyboardRemove(),
            )
            from bot.handlers.menu import get_main_menu
            await update.message.reply_text("Меню:", reply_markup=get_main_menu(context.user_data.get("db_user") if hasattr(context, "user_data") else None, context))
            return

        if editing == "child_size":
            import uuid as _uuid
            import sqlalchemy as _sa
            from db.models.child import Child as _Child
            child_id_str = context.user_data.get("editing_child_id", "")
            parts_input = text_input.split()
            new_size: str | None = None
            new_shoe: float | None = None
            try:
                if parts_input:
                    s = int(parts_input[0])
                    if 56 <= s <= 176:
                        new_size = str(s)
                    else:
                        await update.message.reply_text("Размер одежды должен быть от 56 до 176")
                        return
                if len(parts_input) >= 2:
                    try:
                        sh = float(parts_input[1].replace(",", "."))
                    except (ValueError, TypeError):
                        sh = None
                    if sh and 15 <= sh <= 45:
                        new_shoe = sh
                    else:
                        await update.message.reply_text("Размер обуви должен быть от 15 до 45")
                        return
            except ValueError:
                await update.message.reply_text("Не понял размер 🤔 Например: «104» или «104 27»")
                return
            try:
                child_id = _uuid.UUID(child_id_str)
                vals: dict = {}
                if new_size:
                    vals["current_size"] = new_size
                if new_shoe is not None:
                    vals["shoe_size"] = int(new_shoe)  # model expects Integer
                if vals:
                    async with AsyncWriteSession() as _sess:
                        await _sess.execute(
                            _sa.update(_Child).where(_Child.id == child_id).values(**vals)
                        )
                        await _sess.commit()
            except Exception as _e:
                import structlog as _sl
                _sl.get_logger().error("edit_child_size.failed", error=str(_e), child_id=child_id_str)
                await update.message.reply_text("Ошибка сохранения размера. Попробуй ещё раз.")
                context.user_data.pop("editing", None)
                return
            context.user_data.pop("editing", None)
            context.user_data.pop("editing_child_id", None)
            context.user_data.pop("editing_ts", None)
            parts_done = []
            if new_size:
                parts_done.append(f"одежда {new_size}")
            if new_shoe:
                parts_done.append(f"обувь {new_shoe}")
            await update.message.reply_text(f"✅ Размер обновлён: {', '.join(parts_done) if parts_done else 'без изменений'}")
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
                try:
                    s = int(text_input)
                    if 56 <= s <= 176:
                        adding_child["size"] = str(s)
                    else:
                        await update.message.reply_text("Размер одежды 56–176. Попробуй ещё раз или напиши «пропустить»")
                        return
                except ValueError:
                    await update.message.reply_text("Напиши число, например 92. Или «пропустить»")
                    return
            adding_child["step"] = "shoe"
            context.user_data["adding_child"] = adding_child
            await update.message.reply_text(
                "👟 Размер обуви? (например 27 или 26.5)\nИли напиши «пропустить»"
            )
            return

        if step == "shoe":
            if text_input.lower() not in ("пропустить", "skip", "-"):
                from bot.handlers.onboarding import _parse_shoe_size
                sh = _parse_shoe_size(text_input)
                if sh and 15 <= sh <= 45:
                    adding_child["shoe"] = sh
                else:
                    await update.message.reply_text("Размер обуви 15–45 (например 27 или 26.5). Или «пропустить»")
                    return
            adding_child["step"] = "done"
            context.user_data["adding_child"] = adding_child
            from bot.handlers.profile import _finish_add_child
            await _finish_add_child(update.message, user, context)
            return

    # Лимит чата через Redis (отдельный от лимита фото)
    redis = context.bot_data.get("redis")
    effective_plan = get_effective_plan(user)
    from core.permissions import get_effective_limits
    _eff_limits = get_effective_limits(user)
    chat_limit = _eff_limits.get("chat_per_day", get_limit("chat_per_day", effective_plan))
    today = date.today().isoformat()
    chat_key = f"chat_limit:{user.id}:{today}"
    chat_count = 0
    # Atomic: increment first, check after (prevents race condition)
    if redis:
        chat_count = await redis.incr(chat_key)
        await redis.expire(chat_key, 86400)
    else:
        chat_count = 1

    if chat_count > chat_limit and effective_plan != "admin":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Premium →", callback_data="show_upgrade")
        ]])
        if is_trial_just_ended(user):
            msg = t("trial.expired")
        else:
            from core.permissions import get_limit
            _pc = get_limit("chat_per_day", "premium")
            msg = (
                "Касси ответит завтра! 💬\n"
                f"Premium = {_pc} вопросов/день."
            )
        await update.message.reply_text(msg, reply_markup=keyboard)
        return

    try:
        start = time.monotonic()
        pool = get_anthropic_pool()

        # Получить погоду для контекста
        weather_line = ""
        city = getattr(user, "city", None)
        if city and redis:
            try:
                from services.weather import WeatherService
                ws = WeatherService(redis)
                wd = await ws.get(city)
                weather_line = f"{wd.temp_c}°C, {wd.description}"
            except Exception:
                pass  # не критично

        system = _get_text_system(user, weather_line=weather_line)

        # Добавить style_type в system prompt
        _style_prefs = getattr(user, "style_preferences", None) or {}
        _style_type = _style_prefs.get("style_type")
        if _style_type:
            from bot.handlers.style_quiz import STYLE_TYPES
            _st = STYLE_TYPES.get(_style_type)
            if _st:
                system += f"\n\nСтиль пользователя: {_st['label']}. Используй слова: {', '.join(_st['tone_words'])}."

        # Typing indicator
        await context.bot.send_chat_action(update.effective_chat.id, "typing")

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

        # Detect explicit preferences → save to Kassi memory
        _user_text = update.message.text.strip().lower()
        try:
            import re
            _MEM_PATTERNS = [
                (r"не люблю (.+)", "не любит {0}"),
                (r"не ношу (.+)", "не носит {0}"),
                (r"люблю (.+)", "любит {0}"),
                (r"предпочитаю (.+)", "предпочитает {0}"),
                (r"аллергия на (.+)", "аллергия на {0}"),
                (r"ненавижу (.+)", "не любит {0}"),
            ]
            for pattern, template in _MEM_PATTERNS:
                m = re.search(pattern, _user_text)
                if m:
                    from services.kassi_memory import save_explicit_memory
                    fact = template.format(m.group(1).strip()[:50])
                    await save_explicit_memory(str(user.id), fact)
                    logger.info("memory.explicit_saved", user_id=str(user.id), fact=fact)
                    break
        except Exception:
            pass

        response = await pool.create_message(
            model=HAIKU_MODEL,
            system=system,
            messages=[{"role": "user", "content": update.message.text}],
            max_tokens=512,
        )
        reply = response.content[0].text if response.content else t("error.generic")
        duration_ms = int((time.monotonic() - start) * 1000)

        # Суффикс — только когда мало осталось
        remaining = chat_limit - chat_count
        if remaining == 0:
            suffix = "\n\n⚠️ Это последний вопрос на сегодня."
        elif remaining <= 2:
            suffix = f"\n\n💬 Осталось вопросов сегодня: {remaining}/{chat_limit}"
        else:
            suffix = ""

        await update.message.reply_text(f"{reply}{suffix}", reply_markup=get_main_menu(context.user_data.get("db_user") if hasattr(context, "user_data") else None, context))

        # Chat counter already incremented atomically before the AI call

        # Инкремент общего счётчика (atomic)
        async with AsyncWriteSession() as session:
            result = await session.execute(
                sa.update(User)
                .where(User.id == user.id)
                .values(daily_requests_used=User.daily_requests_used + 1)
                .returning(User.daily_requests_used)
            )
            await session.commit()
            row = result.first()
            user.daily_requests_used = row[0] if row else user.daily_requests_used + 1

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
