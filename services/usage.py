"""Утилиты для отображения лимитов пользователю."""

_LIMITS = {"free": 3, "basic": 50, "family": 100, "premium": -1}


def get_usage_str(user) -> str | None:
    """Строка счётчика для показа пользователю. None для premium."""
    limit = _LIMITS.get(user.plan, 3)
    if limit == -1:
        return None
    return f"📸 Фото сегодня: {user.daily_requests_used}/{limit}"


def get_limit_exceeded_msg(user) -> str:
    """Сообщение при исчерпании лимита."""
    limit = _LIMITS.get(user.plan, 3)
    upsell = {
        "free": "Хочешь больше? /subscribe — от $5/мес",
        "basic": "Перейди на Family для 100 фото: /subscribe",
        "family": "Перейди на Premium для безлимита: /subscribe",
    }
    return (
        f"📸 Дневной лимит исчерпан ({limit}/{limit} фото)\n\n"
        f"Обновится завтра утром 🌅\n"
        f"{upsell.get(user.plan, '')}"
    )
