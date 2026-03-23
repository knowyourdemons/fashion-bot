"""Style Quiz: 10 image pairs → style type → influences Kassi and outfit selection."""
import io
import structlog
from pathlib import Path
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes

from db.base import AsyncWriteSession
from db.models.user import User
from services.i18n import t, get_user_lang
import sqlalchemy as sa

logger = structlog.get_logger()

ASSETS_DIR = Path(__file__).parent.parent.parent / "assets" / "style_quiz"

# ── Quiz pairs ────────────────────────────────────────────────────────────────

QUIZ_PAIRS = [
    {"num": 1, "left_label": "Classic", "right_label": "Edgy", "left_axis": "classic", "right_axis": "edgy"},
    {"num": 2, "left_label": "Minimalist", "right_label": "Maximalist", "left_axis": "minimalist", "right_axis": "maximalist"},
    {"num": 3, "left_label": "Romantic", "right_label": "Sporty", "left_axis": "romantic", "right_axis": "sporty"},
    {"num": 4, "left_label": "Feminine", "right_label": "Athletic", "left_axis": "feminine", "right_axis": "athletic"},
    {"num": 5, "left_label": "Warm", "right_label": "Cool", "left_axis": "warm", "right_axis": "cool"},
    {"num": 6, "left_label": "Fitted", "right_label": "Oversized", "left_axis": "fitted", "right_axis": "oversized"},
    {"num": 7, "left_label": "Neutral", "right_label": "Bold", "left_axis": "neutral", "right_axis": "bold"},
    {"num": 8, "left_label": "Structured", "right_label": "Flowy", "left_axis": "structured", "right_axis": "flowy"},
    {"num": 9, "left_label": "Timeless", "right_label": "Trendy", "left_axis": "timeless", "right_axis": "trendy"},
    {"num": 10, "left_label": "Layered", "right_label": "Simple", "left_axis": "layered", "right_axis": "simple"},
]

# ── Style types ───────────────────────────────────────────────────────────────

STYLE_TYPES = {
    "elegant_classic": {
        "axes": ["classic", "minimalist", "timeless", "structured", "neutral"],
        "label": "Elegant Classic",
        "desc": "Элегантность в деталях, благородные сочетания",
        "tone_words": ["элегантный", "утончённый", "классика", "безупречный"],
        "palette": ["#2C3E6B", "#C5A882", "#F5F0EB", "#8B4D5C"],
    },
    "romantic_soft": {
        "axes": ["romantic", "feminine", "flowy", "warm", "layered"],
        "label": "Romantic Soft",
        "desc": "Нежность и женственность, мягкие текстуры",
        "tone_words": ["нежный", "женственный", "мягкий", "воздушный"],
        "palette": ["#D4A0B0", "#F5E6D8", "#A0C4B8", "#E8D0C0"],
    },
    "street_casual": {
        "axes": ["edgy", "athletic", "oversized", "bold", "trendy"],
        "label": "Street Casual",
        "desc": "Свободный стиль, городская энергия",
        "tone_words": ["расслабленный", "urban", "свободный", "дерзкий"],
        "palette": ["#303030", "#E05050", "#F0F0F0", "#5080A0"],
    },
    "sporty_minimal": {
        "axes": ["sporty", "minimalist", "fitted", "simple", "cool"],
        "label": "Sporty Minimal",
        "desc": "Чистые линии, функциональная элегантность",
        "tone_words": ["чистые линии", "функциональный", "лаконичный", "свежий"],
        "palette": ["#F5F5F5", "#303030", "#70A0D0", "#E0E0E0"],
    },
    "bold_creative": {
        "axes": ["maximalist", "trendy", "bold", "edgy", "layered"],
        "label": "Bold Creative",
        "desc": "Яркий микс, неожиданные сочетания",
        "tone_words": ["яркий", "смелый", "неожиданный", "выразительный"],
        "palette": ["#E04080", "#3060D0", "#F0C020", "#40A060"],
    },
    "relaxed_natural": {
        "axes": ["athletic", "neutral", "warm", "simple", "flowy"],
        "label": "Relaxed Natural",
        "desc": "Естественная красота, уют и натуральность",
        "tone_words": ["естественный", "уютный", "натуральный", "тёплый"],
        "palette": ["#C8B8A0", "#8B7D6B", "#E8DDD0", "#A0B890"],
    },
}


# ── PIL image builder ─────────────────────────────────────────────────────────

def build_quiz_image(pair_num: int) -> bytes:
    """Build side-by-side comparison image for quiz pair."""
    a_path = ASSETS_DIR / f"pair_{pair_num:02d}_a.jpg"
    b_path = ASSETS_DIR / f"pair_{pair_num:02d}_b.jpg"
    a = Image.open(a_path)
    b = Image.open(b_path)
    canvas = Image.new("RGB", (440, 280), (245, 243, 240))
    a_resized = a.resize((200, 250), Image.LANCZOS)
    b_resized = b.resize((200, 250), Image.LANCZOS)
    canvas.paste(a_resized, (10, 15))
    canvas.paste(b_resized, (230, 15))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()


def _quiz_caption(step: int) -> str:
    """Build caption for quiz step."""
    if step >= 7:
        return f"Какой образ ближе? ({step}/10 \u00b7 Почти! \U0001f525)"
    return f"Какой образ ближе? ({step}/10)"


def _quiz_keyboard(pair: dict) -> InlineKeyboardMarkup:
    """Build inline keyboard for quiz pair."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"\u2190 {pair['left_label']}", callback_data=f"quiz:{pair['num']}:left"),
        InlineKeyboardButton(f"{pair['right_label']} \u2192", callback_data=f"quiz:{pair['num']}:right"),
    ]])


def compute_style_type(scores: dict) -> str:
    """Compute style type from quiz scores."""
    best_type = "elegant_classic"
    best_score = -1
    for type_name, type_info in STYLE_TYPES.items():
        total = sum(scores.get(axis, 0) for axis in type_info["axes"])
        if total > best_score:
            best_score = total
            best_type = type_name
    return best_type


# ── Handlers ──────────────────────────────────────────────────────────────────

async def handle_quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: quiz_start → send first quiz image."""
    query = update.callback_query
    await query.answer()

    pair = QUIZ_PAIRS[0]
    context.user_data["quiz_step"] = 1
    context.user_data["quiz_scores"] = {}

    await context.bot.send_chat_action(query.message.chat_id, "typing")

    # Try cached file_id first
    redis = context.bot_data.get("redis")
    file_id = None
    if redis:
        try:
            cached = await redis.get(f"quiz_file:{pair['num']}")
            if cached:
                file_id = cached.decode() if isinstance(cached, bytes) else cached
        except Exception:
            pass

    if file_id:
        msg = await query.message.reply_photo(
            photo=file_id,
            caption=_quiz_caption(1),
            reply_markup=_quiz_keyboard(pair),
        )
    else:
        img_bytes = build_quiz_image(pair["num"])
        msg = await query.message.reply_photo(
            photo=img_bytes,
            caption=_quiz_caption(1),
            reply_markup=_quiz_keyboard(pair),
        )
        # Cache file_id
        if redis and msg.photo:
            try:
                await redis.set(f"quiz_file:{pair['num']}", msg.photo[-1].file_id, ex=30 * 86400)
            except Exception:
                pass

    # Remove trigger message buttons
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    logger.info("quiz.started", user_id=str(context.user_data.get("db_user", {}).id) if context.user_data.get("db_user") else "unknown")


async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: quiz:{pair_num}:{left|right} → record answer, show next or result."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    pair_num = int(parts[1])
    choice = parts[2]  # "left" or "right"

    pair = QUIZ_PAIRS[pair_num - 1]
    scores = context.user_data.get("quiz_scores", {})

    # Record score
    if choice == "left":
        axis = pair["left_axis"]
    else:
        axis = pair["right_axis"]
    scores[axis] = scores.get(axis, 0) + 1
    context.user_data["quiz_scores"] = scores

    # Last question → compute result
    if pair_num >= 10:
        await _show_quiz_result(query, context, scores)
        return

    # Next question
    next_pair = QUIZ_PAIRS[pair_num]
    step = pair_num + 1
    context.user_data["quiz_step"] = step

    redis = context.bot_data.get("redis")
    file_id = None
    if redis:
        try:
            cached = await redis.get(f"quiz_file:{next_pair['num']}")
            if cached:
                file_id = cached.decode() if isinstance(cached, bytes) else cached
        except Exception:
            pass

    if file_id:
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=file_id, caption=_quiz_caption(step)),
                reply_markup=_quiz_keyboard(next_pair),
            )
        except Exception:
            # Fallback: send new photo
            msg = await query.message.reply_photo(
                photo=file_id,
                caption=_quiz_caption(step),
                reply_markup=_quiz_keyboard(next_pair),
            )
    else:
        img_bytes = build_quiz_image(next_pair["num"])
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=img_bytes, caption=_quiz_caption(step)),
                reply_markup=_quiz_keyboard(next_pair),
            )
            # Cache file_id from edited message
            if redis and query.message.photo:
                try:
                    await redis.set(f"quiz_file:{next_pair['num']}", query.message.photo[-1].file_id, ex=30 * 86400)
                except Exception:
                    pass
        except Exception:
            msg = await query.message.reply_photo(
                photo=img_bytes,
                caption=_quiz_caption(step),
                reply_markup=_quiz_keyboard(next_pair),
            )
            if redis and msg.photo:
                try:
                    await redis.set(f"quiz_file:{next_pair['num']}", msg.photo[-1].file_id, ex=30 * 86400)
                except Exception:
                    pass


async def _show_quiz_result(query, context, scores: dict) -> None:
    """Compute style type, save to DB, render result card."""
    user = context.user_data.get("db_user")
    style_type = compute_style_type(scores)
    st = STYLE_TYPES[style_type]

    # Save to DB
    if user:
        prefs = getattr(user, "style_preferences", None) or {}
        prefs["style_type"] = style_type
        prefs["quiz_completed"] = True
        prefs["quiz_scores"] = scores
        try:
            async with AsyncWriteSession() as session:
                await session.execute(
                    sa.update(User).where(User.id == user.id)
                    .values(style_preferences=prefs)
                )
                await session.commit()
            user.style_preferences = prefs
        except Exception as e:
            logger.error("quiz.save_failed", error=str(e))

    # Show loading
    try:
        await query.edit_message_caption(caption="✨ Уже определяю твой стиль...")
    except Exception:
        pass
    await context.bot.send_chat_action(query.message.chat_id, "typing")

    # Render result card via Playwright
    result_png = None
    try:
        from services.brief_renderer import render_template, render_html_to_png
        name = getattr(user, "name", "").split()[0] if getattr(user, "name", "") else ""
        html = render_template(
            "tpl_style_result.html",
            name=name or "Style",
            style_label=st["label"],
            style_desc=st["desc"],
            palette=st["palette"],
            tone_words=", ".join(st["tone_words"]),
        )
        result_png = await render_html_to_png(html, width=440)
    except Exception as e:
        logger.warning("quiz.render_failed", error=str(e))

    # Send result
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\U0001f44d \u041a\u043b\u0430\u0441\u0441!", callback_data="quiz_done"),
    ]])

    text = f"\U0001f48c \u0422\u044b \u2014 {st['label']}! {st['desc']}\n\n\u0422\u0435\u043f\u0435\u0440\u044c \u0431\u0443\u0434\u0443 \u043f\u043e\u0434\u0431\u0438\u0440\u0430\u0442\u044c \u043e\u0431\u0440\u0430\u0437\u044b \u0432 \u0442\u0432\u043e\u0451\u043c \u0441\u0442\u0438\u043b\u0435 \u2728"

    if result_png:
        try:
            await query.message.reply_photo(photo=result_png)
        except Exception:
            pass
        import asyncio
        await asyncio.sleep(0.1)
        try:
            await query.message.reply_text(text, reply_markup=keyboard)
        except Exception as e:
            logger.warning("quiz.result_text_failed", error=str(e))
    else:
        await query.message.reply_text(text, reply_markup=keyboard)

    # Clean up quiz message
    try:
        await query.message.delete()
    except Exception:
        pass

    # Clear quiz state
    context.user_data.pop("quiz_step", None)
    context.user_data.pop("quiz_scores", None)

    logger.info("quiz.completed", style_type=style_type, scores=scores,
                user_id=str(user.id) if user else "unknown")


async def handle_quiz_later(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: quiz_later → decline quiz, set Redis TTL."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    redis = context.bot_data.get("redis")

    if redis and user:
        try:
            await redis.set(f"quiz_declined:{user.id}", "1", ex=3 * 86400)
        except Exception:
            pass

    lang = get_user_lang(user)
    try:
        await query.edit_message_text(t("quiz.later", lang))
    except Exception:
        pass


async def handle_quiz_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: quiz_done → acknowledge result."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
