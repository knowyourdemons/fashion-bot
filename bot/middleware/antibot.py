"""
Antibot middleware: per-user rate limiting and spam protection.
Runs as PTB middleware (group=-3, before auth).

Uses Redis for atomic rate counting and temporary bans.
Raises ApplicationHandlerStop to silently drop updates from spammers.
"""
import structlog
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from core.redis import get_redis

logger = structlog.get_logger()


class AntibotMiddleware:
    """Per-user rate limiting. Runs as PTB middleware (group=-3, before auth)."""

    # Limits per user
    PHOTO_LIMIT = 20        # photos per 5 minutes
    PHOTO_WINDOW = 300      # 5 min
    MESSAGE_LIMIT = 30      # text messages per minute
    MESSAGE_WINDOW = 60     # 1 min
    CALLBACK_LIMIT = 60     # callback queries per minute
    CALLBACK_WINDOW = 60    # 1 min

    BAN_THRESHOLD = 3       # consecutive limit hits → temp ban
    BAN_DURATION = 300      # 5 min ban
    STRIKE_WINDOW = 600     # strikes expire after 10 min

    @staticmethod
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # 1. Get user_id from update
        user = update.effective_user
        if not user:
            return
        user_id = user.id

        try:
            redis = get_redis()
        except RuntimeError:
            # Redis not initialized yet — let through
            return

        # 2. Check ban
        ban_key = f"antibot:ban:{user_id}"
        try:
            is_banned = await redis.exists(ban_key)
        except Exception:
            # Redis error — don't block users
            return

        if is_banned:
            logger.debug("antibot.banned_user_blocked", user_id=user_id)
            raise ApplicationHandlerStop()

        # 3. Determine update type and limits
        if update.callback_query:
            rate_type = "callback"
            limit = AntibotMiddleware.CALLBACK_LIMIT
            window = AntibotMiddleware.CALLBACK_WINDOW
        elif update.message:
            if update.message.photo or (
                update.message.document
                and update.message.document.mime_type
                and update.message.document.mime_type.startswith("image/")
            ):
                rate_type = "photo"
                limit = AntibotMiddleware.PHOTO_LIMIT
                window = AntibotMiddleware.PHOTO_WINDOW
            elif update.message.text:
                rate_type = "message"
                limit = AntibotMiddleware.MESSAGE_LIMIT
                window = AntibotMiddleware.MESSAGE_WINDOW
            else:
                # Other message types (location, sticker, etc.) — let through
                return
        else:
            # Other update types — let through
            return

        # 4. Atomic INCR + EXPIRE via pipeline
        rate_key = f"antibot:rate:{user_id}:{rate_type}"
        try:
            pipe = redis.pipeline(transaction=True)
            pipe.incr(rate_key)
            pipe.expire(rate_key, window)
            results = await pipe.execute()
            count = results[0]
        except Exception as e:
            logger.warning("antibot.redis_error", user_id=user_id, error=str(e))
            return  # Redis error — don't block

        # 5. Check if over limit
        if count > limit:
            strike_key = f"antibot:strikes:{user_id}"
            try:
                pipe = redis.pipeline(transaction=True)
                pipe.incr(strike_key)
                pipe.expire(strike_key, AntibotMiddleware.STRIKE_WINDOW)
                strike_results = await pipe.execute()
                strikes = strike_results[0]
            except Exception:
                strikes = 1

            logger.warning(
                "antibot.rate_exceeded",
                user_id=user_id,
                rate_type=rate_type,
                count=count,
                limit=limit,
                strikes=strikes,
            )

            if strikes >= AntibotMiddleware.BAN_THRESHOLD:
                try:
                    await redis.setex(
                        ban_key,
                        AntibotMiddleware.BAN_DURATION,
                        b"1",
                    )
                    logger.warning(
                        "antibot.user_banned",
                        user_id=user_id,
                        duration=AntibotMiddleware.BAN_DURATION,
                    )
                except Exception:
                    pass

            raise ApplicationHandlerStop()
