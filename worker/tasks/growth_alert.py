"""Growth alert — ежемесячная проверка размера ребёнка по стандартам ВОЗ."""
import structlog
from datetime import date

logger = structlog.get_logger()

# Размеры по ВОЗ: возраст в месяцах → размер одежды
_WHO_SIZE = {
    12: 80, 18: 86, 24: 92, 30: 98, 36: 98,
    42: 104, 48: 104, 54: 110, 60: 110,
    66: 116, 72: 116, 78: 122, 84: 122,
}


async def run() -> None:
    """Ежемесячно проверяет размеры детей по ВОЗ и отправляет алерт если нужно."""
    from config import settings
    from db.base import AsyncReadSession
    from db.models.user import User
    from db.crud.children import get_children
    from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    bot = Bot(token=settings.telegram_bot_token)
    count = 0

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User)
            .options(selectinload(User.children))
            .where(
                User.onboarding_completed.is_(True),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.segment.in_(["mom_girl", "mom_boy"]),
            )
        )
        users = list(result.scalars().all())

    for user in users:
        children = [c for c in (user.children or []) if c.deleted_at is None]
        for child in children:
            if not child.birthdate or not child.current_size:
                continue
            try:
                age_months = (date.today() - child.birthdate).days // 30
                # Найти ближайший порог
                expected = None
                for threshold, size in sorted(_WHO_SIZE.items()):
                    if age_months >= threshold:
                        expected = size
                if expected is None:
                    continue

                try:
                    current_size_int = int(str(child.current_size).split(".")[0])
                except (ValueError, TypeError):
                    continue

                if expected > current_size_int:
                    gender_word = "дочка" if child.gender == "girl" else "сын"
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("📏 Обновить размер", callback_data="edit_child_size"),
                    ]])
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=(
                            f"📏 {child.name} подрос(ла)!\n"
                            f"Размер в профиле: {child.current_size}, "
                            f"ожидаемый по возрасту ({age_months} мес): {expected}\n\n"
                            f"Обнови размер и проверь какие вещи пора менять 👗"
                        ),
                        reply_markup=keyboard,
                    )
                    logger.info(
                        "growth_alert.sent",
                        user_id=str(user.id),
                        child_id=str(child.id),
                        current=current_size_int,
                        expected=expected,
                    )
                    count += 1
            except Exception as e:
                logger.warning("growth_alert.child_error", child_id=str(child.id), error=str(e))

    logger.info("growth_alert.run", sent=count)
