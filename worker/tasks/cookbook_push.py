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


async def _expiring_for(tg_id: str, days: int = 2, limit: int = 4) -> list[str]:
    """Названия продуктов из кладовки юзера со сроком ≤days дней (анти-waste крючок в пуш)."""
    from datetime import date
    from sqlalchemy import select
    from db.base import AsyncReadSession
    from db.models.cookbook_state import CookbookState
    try:
        async with AsyncReadSession() as session:
            row = (await session.execute(
                select(CookbookState).where(CookbookState.tg_id == str(tg_id), CookbookState.key == "pantry")
            )).scalar_one_or_none()
        if not row or not isinstance(row.value, dict):
            return []
        items = row.value.get("items") or {}
        expiry = row.value.get("expiry") or {}
        today = date.today()
        out = []
        for name, dstr in expiry.items():
            if not items.get(name):
                continue
            try:
                if (date.fromisoformat(str(dstr)) - today).days <= days:
                    out.append(name)
            except Exception:
                continue
        return out[:limit]
    except Exception as e:
        logger.warning("cookbook_push.pantry_read_failed", tg_id=tg_id, error=str(e))
        return []


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
            exp = await _expiring_for(chat_id)
            text = DINNER_TEXT
            if exp:
                text += "\n\n⏳ Скоро испортится: " + ", ".join(exp) + " — подскажу, что из них приготовить."
            await bot.send_message(chat_id=int(chat_id), text=text, reply_markup=kb)
            sent += 1
        except Exception as e:
            logger.warning("cookbook_push.send_failed", chat_id=chat_id, error=str(e))
    logger.info("cookbook_push.sent", n=sent)
