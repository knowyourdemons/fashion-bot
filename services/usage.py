"""Утилиты для отображения лимитов пользователю."""
from core.permissions import get_effective_plan, get_limit


def get_usage_str(user) -> str | None:
    """Строка счётчика для показа пользователю. None для premium/admin (не нужен счётчик)."""
    effective_plan = get_effective_plan(user)
    if effective_plan != "free":
        return None
    limit = get_limit("photos_per_day", effective_plan)
    return f"📸 Фото сегодня: {user.daily_requests_used}/{limit}"


def get_limit_exceeded_msg(user) -> str:
    """Сообщение при исчерпании лимита."""
    effective_plan = get_effective_plan(user)
    limit = get_limit("photos_per_day", effective_plan)
    return (
        f"📸 Дневной лимит исчерпан ({limit}/{limit} фото)\n\n"
        f"Обновится завтра 🌅\n"
        f"Безлимит фото — на Premium: /subscribe"
    )
