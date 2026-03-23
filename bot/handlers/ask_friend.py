"""Ask a Friend — 1-click outfit voting via deep link.

Flow: User → [Спросить подругу] → share link → friend votes → notification back.
Friend doesn't need the bot installed. Deep link: t.me/bot?start=vote_XXXX
"""
import json
import uuid
import structlog
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from services.i18n import t, get_user_lang

logger = structlog.get_logger()


async def create_vote_link(user_id: str, photo_id: str, description: str, redis, bot_username: str) -> str:
    """Create a voting link for outfit."""
    vote_id = uuid.uuid4().hex[:8]
    vote_data = {
        "user_id": str(user_id),
        "photo_id": photo_id,
        "description": description,
        "votes": {},
        "created_at": datetime.now().isoformat(),
    }
    await redis.set(f"vote:{vote_id}", json.dumps(vote_data, ensure_ascii=False), ex=48 * 3600)
    return f"https://t.me/{bot_username}?start=vote_{vote_id}"


async def handle_ask_friend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: ask_friend:{brief_id} → generate vote link."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return

    redis = context.bot_data.get("redis")
    if not redis:
        return

    # Weekly limit
    from core.permissions import get_effective_plan
    from datetime import date
    plan = get_effective_plan(user)
    is_premium = plan in ("premium", "ultra", "admin")
    week_key = f"ask_friend:{user.id}:{date.today().isocalendar()[1]}"

    if not is_premium:
        val = await redis.get(week_key)
        if val and int(val) >= 1:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Premium", callback_data="show_upgrade"),
            ]])
            await query.message.reply_text(
                "📤 1 раз/неделю в Free. В Premium — без лимита!",
                reply_markup=keyboard,
            )
            return

    # Get photo_id from brief_log or last collage
    parts = query.data.split(":")
    brief_id = parts[1] if len(parts) > 1 else None

    photo_id = None
    if brief_id:
        try:
            from db.base import AsyncReadSession
            from db.crud.brief_log import get_log
            import uuid as _uuid
            async with AsyncReadSession() as session:
                log = await get_log(session, _uuid.UUID(brief_id))
            if log and log.collage_file_id:
                photo_id = log.collage_file_id
        except Exception:
            pass

    if not photo_id:
        lang = get_user_lang(user)
        await query.message.reply_text(t("ask_friend.share_hint", lang))
        return

    bot_username = (await context.bot.get_me()).username
    link = await create_vote_link(str(user.id), photo_id, "Образ дня", redis, bot_username)

    await redis.incr(week_key)
    await redis.expire(week_key, 8 * 86400)

    await query.message.reply_text(
        f"📤 Отправь подруге — она проголосует за образ!\n\n{link}"
    )
    logger.info("ask_friend.link_created", user_id=str(user.id))


async def handle_vote_start(update: Update, context: ContextTypes.DEFAULT_TYPE, vote_id: str) -> None:
    """Handle deep link: /start vote_XXXX → show collage + vote buttons."""
    redis = context.bot_data.get("redis")
    if not redis:
        await update.message.reply_text(t("ask_friend.vote_unavailable"))
        return

    raw = await redis.get(f"vote:{vote_id}")
    if not raw:
        await update.message.reply_text(t("ask_friend.vote_closed"))
        return

    data = json.loads(raw if isinstance(raw, str) else raw.decode())

    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=data["photo_id"],
            caption=f"👗 {data['description']}\n\nКак тебе образ?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👍 Огонь!", callback_data=f"vote:{vote_id}:yes"),
                InlineKeyboardButton("🔄 Попробуй другой", callback_data=f"vote:{vote_id}:no"),
            ]]),
        )
    except Exception as e:
        logger.warning("vote.send_failed", error=str(e))
        await update.message.reply_text(t("ask_friend.load_failed"))


async def handle_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: vote:{id}:{yes|no} → record vote, notify user."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 3:
        return
    vote_id = parts[1]
    choice = parts[2]

    redis = context.bot_data.get("redis")
    if not redis:
        return

    raw = await redis.get(f"vote:{vote_id}")
    if not raw:
        try:
            await query.edit_message_caption(caption=t("ask_friend.vote_closed"))
        except Exception:
            pass
        return

    data = json.loads(raw if isinstance(raw, str) else raw.decode())
    friend_id = str(update.effective_user.id)
    data["votes"][friend_id] = choice
    await redis.set(f"vote:{vote_id}", json.dumps(data, ensure_ascii=False), ex=48 * 3600)

    friend_name = update.effective_user.first_name or "Подруга"

    # Reply to friend
    if choice == "yes":
        try:
            await query.edit_message_caption(caption="👍 Ты проголосовала: Огонь! ✨")
        except Exception:
            pass
    else:
        try:
            await query.edit_message_caption(caption="🔄 Ты проголосовала: Попробуй другой")
        except Exception:
            pass

    # Notify user
    try:
        from db.base import AsyncReadSession
        from db.models.user import User
        from sqlalchemy import select
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User.telegram_id).where(User.id == data["user_id"])
            )
            user_tg_id = result.scalar()

        if user_tg_id:
            if choice == "yes":
                await context.bot.send_message(
                    user_tg_id,
                    f"✨ {friend_name} одобряет твой образ! 👍"
                )
            else:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Другой образ", callback_data="outfit_request"),
                ]])
                await context.bot.send_message(
                    user_tg_id,
                    f"🤔 {friend_name} предлагает попробовать другой",
                    reply_markup=keyboard,
                )
    except Exception as e:
        logger.warning("vote.notify_failed", error=str(e))

    # Promo for non-user friends
    try:
        from db.base import AsyncReadSession as _ARS
        from db.models.user import User as _U
        from sqlalchemy import select as _sel
        async with _ARS() as _s:
            exists = await _s.execute(_sel(_U.id).where(_U.telegram_id == int(friend_id)))
            if not exists.scalar():
                await context.bot.send_message(
                    update.effective_chat.id,
                    "💡 Хочешь так же? Касси подбирает образы каждое утро!\n"
                    "Попробуй бесплатно → /start",
                )
    except Exception:
        pass

    logger.info("vote.cast", vote_id=vote_id, choice=choice, friend=friend_name)
