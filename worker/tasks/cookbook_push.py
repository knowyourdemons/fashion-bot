"""Кукбук: ежедневный пуш «что на ужин» в Telegram.

Заменяет фешн morning/evening brief (Стас фешн-ботом не пользуется).
Шлёт cookbook-allowed юзерам ссылку на персональный экран #/today (подбор — на клиенте:
кладовка, вкусы, цель по калориям, профиль ребёнка).
"""
import structlog

from config import settings

logger = structlog.get_logger()

DINNER_URL = "https://bot.fashioncastle.app/?src=push#/today"
DINNER_TEXT = (
    "🍽 Что на ужин сегодня?\n\n"
    "Открой персональный подбор — учтёт кладовку, вкусы и цель по калориям "
    "и предложит блюдо за секунду."
)


async def run() -> None:
    ids = [x.strip() for x in (settings.cookbook_allowed_telegram_ids or "").split(",") if x.strip()]
    if not (ids and settings.telegram_bot_token):
        return
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

    bot = Bot(token=settings.telegram_bot_token)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🍽 Что сегодня?", url=DINNER_URL)]])
    sent = 0
    for chat_id in ids:
        try:
            await bot.send_message(chat_id=int(chat_id), text=DINNER_TEXT, reply_markup=kb)
            sent += 1
        except Exception as e:
            logger.warning("cookbook_push.send_failed", chat_id=chat_id, error=str(e))
    logger.info("cookbook_push.sent", n=sent)
