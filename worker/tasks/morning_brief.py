"""
Morning Brief задача:
- Запускается в 07:00 по timezone юзера
- Генерирует образ на день на основе погоды + гардероба
- Использует prompt caching для системного промпта
"""
import structlog
from worker.fast_worker import register

logger = structlog.get_logger()


@register("send_morning_brief")
async def handle_send_brief(payload: dict) -> dict:
    """Обрабатывает задачу отправки brief конкретному пользователю."""
    user_id = payload["user_id"]
    brief_text = payload.get("brief_text", "")
    is_wow = payload.get("is_wow", False)

    # TODO: отправить через Telegram Bot API
    logger.info("morning_brief.send", user_id=user_id, is_wow=is_wow)
    return {"sent": True}


async def schedule_all() -> None:
    """Cron: каждый час — отбирает юзеров у кого сейчас 07:00."""
    from datetime import datetime
    import pytz

    # TODO: получить всех active пользователей из БД
    # Фильтровать по: plan != free, onboarding_completed=True
    # Проверять timezone: datetime.now(tz).hour == 7
    # Проверять Redis lock: lock:brief:{user_id}:{date}
    # Пушить в queue:high задачу generate_brief

    logger.info("morning_brief.schedule_all", hour=datetime.utcnow().hour)


@register("generate_brief")
async def generate_brief(payload: dict) -> dict:
    """
    Генерирует Morning Brief:
    1. Получает погоду (WeatherService)
    2. Загружает гардероб юзера/ребёнка
    3. Строит системный промпт с cache_control
    4. Вызывает Claude (AnthropicPool)
    5. Парсит образ, считает score
    6. Сохраняет в BriefLog
    7. Пушит send_morning_brief
    """
    user_id = payload["user_id"]
    logger.info("morning_brief.generate", user_id=user_id)
    # TODO: реализовать
    return {}
