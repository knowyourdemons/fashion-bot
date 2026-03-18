"""
Планы, лимиты и конверсионные триггеры.
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from exceptions import PermissionDeniedError, WardrobeFullError

# ── Старые PLANS (обратная совместимость) ────────────────────────────────────

PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "daily_requests": 3,
        "max_wardrobe_items": 20,
        "max_children": 0,
        "morning_brief": False,
        "gap_analysis": False,
        "wow_builder": False,
    },
    "basic": {
        "daily_requests": 50,
        "max_wardrobe_items": 50,
        "max_children": 1,
        "morning_brief": True,
        "gap_analysis": False,
        "wow_builder": False,
    },
    "family": {
        "daily_requests": 100,
        "max_wardrobe_items": 200,
        "max_children": 2,
        "morning_brief": True,
        "gap_analysis": True,
        "wow_builder": False,
    },
    "premium": {
        "daily_requests": -1,
        "max_wardrobe_items": -1,
        "max_children": -1,
        "morning_brief": True,
        "gap_analysis": True,
        "wow_builder": True,
    },
}

PLAN_ORDER = ["free", "basic", "family", "premium"]

UPGRADE_TRIGGERS: dict[str, str] = {
    "items_limit_90pct": (
        "У тебя {used}/{max} вещей. Перейди на {next_plan} и добавь ещё"
    ),
    "brief_blocked": (
        "Сегодня {weather}. Хочешь образ для {child_name}? Morning Brief в Basic $5"
    ),
    "daily_limit": (
        "Использовано {used}/{max} запросов. Basic $5 — 50 запросов в день"
    ),
}


def get_plan_limits(plan: str) -> dict[str, Any]:
    return PLANS.get(plan, PLANS["free"])


def get_next_plan(plan: str) -> str | None:
    idx = PLAN_ORDER.index(plan) if plan in PLAN_ORDER else 0
    if idx < len(PLAN_ORDER) - 1:
        return PLAN_ORDER[idx + 1]
    return None


def check_feature(plan: str, feature: str) -> None:
    """Raises PermissionDeniedError если фича недоступна на плане."""
    limits = get_plan_limits(plan)
    if not limits.get(feature, False):
        next_plan = get_next_plan(plan)
        msg = f"Функция '{feature}' недоступна на плане {plan}."
        if next_plan:
            msg += f" Перейди на {next_plan}."
        raise PermissionDeniedError(msg)


def check_wardrobe_limit(plan: str, current_count: int) -> None:
    """Raises WardrobeFullError если гардероб заполнен."""
    limit = get_plan_limits(plan)["max_wardrobe_items"]
    if limit == -1:
        return
    if current_count >= limit:
        next_plan = get_next_plan(plan)
        msg = f"Гардероб заполнен: {current_count}/{limit} вещей."
        if next_plan:
            msg += f" Перейди на {next_plan} для расширения."
        raise WardrobeFullError(msg)


def check_children_limit(plan: str, current_count: int) -> None:
    """Raises PermissionDeniedError если достигнут лимит детей."""
    limit = get_plan_limits(plan)["max_children"]
    if limit == -1:
        return
    if current_count >= limit:
        next_plan = get_next_plan(plan)
        msg = f"Достигнут лимит детей: {current_count}/{limit}."
        if next_plan:
            msg += f" Перейди на {next_plan}."
        raise PermissionDeniedError(msg)


def get_daily_limit(plan: str) -> int:
    return int(get_plan_limits(plan)["daily_requests"])


def upgrade_trigger(trigger: str, **kwargs: Any) -> str:
    template = UPGRADE_TRIGGERS.get(trigger, "")
    return template.format(**kwargs)


# ── Новые лимиты по фичам ────────────────────────────────────────────────────

LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "photos_per_day":     3,
        "wardrobe_size":      15,
        "rate_per_day":       3,
        "chat_per_day":       3,
        "outfit_req_per_day": 1,
        "brief_days":         [1, 3],   # вт=1, чт=3
        "brief_weekends":     False,
        "children_max":       1,
    },
    "premium": {
        "photos_per_day":     30,
        "wardrobe_size":      500,
        "rate_per_day":       20,
        "chat_per_day":       20,
        "outfit_req_per_day": 5,
        "brief_days":         [0, 1, 2, 3, 4, 5, 6],
        "brief_weekends":     True,
        "children_max":       3,
    },
    "ultra": {
        "photos_per_day":     100,
        "wardrobe_size":      2000,
        "rate_per_day":       50,
        "chat_per_day":       50,
        "outfit_req_per_day": 10,
        "brief_days":         [0, 1, 2, 3, 4, 5, 6],
        "brief_weekends":     True,
        "children_max":       10,
    },
    "admin": {
        "photos_per_day":     9999,
        "wardrobe_size":      9999,
        "rate_per_day":       9999,
        "chat_per_day":       9999,
        "outfit_req_per_day": 9999,
        "brief_days":         [0, 1, 2, 3, 4, 5, 6],
        "brief_weekends":     True,
        "children_max":       99,
    },
}

# Маппинг старых планов → новые для LIMITS
_PLAN_ALIAS: dict[str, str] = {
    "basic":  "premium",
    "family": "premium",
}

# ── Цены ─────────────────────────────────────────────────────────────────────

PRICES: dict[str, dict[str, Any]] = {
    "premium_monthly":   {"amount": 9,  "period": "month",  "label": "Месяц — $9"},
    "premium_quarterly": {"amount": 22, "period": "3month", "label": "3 месяца — $22 (экономия $5)"},
    "premium_yearly":    {"amount": 72, "period": "year",   "label": "Год — $72 (экономия $36)"},
}

# ── Ultra фичи (заглушки) ────────────────────────────────────────────────────

ULTRA_FEATURES = [
    "🛍 Шоппинг-лист с партнёрскими ссылками",
    "💎 Капсульный гардероб на сезон",
    "📊 Анализ гардероба",
    "👨‍👩‍👧 Семейный аккаунт",
    "🔄 Передача вещей между детьми",
]


# ── Вспомогательные функции ──────────────────────────────────────────────────

def get_effective_plan(user) -> str:
    """
    Возвращает реальный план с учётом trial и admin.
    Trial даёт premium доступ пока не истёк.
    Admin определяется по telegram_id из settings.
    """
    if not user:
        return "free"

    # Проверить admin через telegram_id
    try:
        from config import settings
        if int(getattr(user, "telegram_id", -1)) in settings.admin_ids_list:
            return "admin"
    except Exception:
        pass

    plan = getattr(user, "plan", "free") or "free"

    # Проверить активный trial
    trial_ends = getattr(user, "trial_ends_at", None)
    if trial_ends:
        now = datetime.now(timezone.utc)
        # Сделать aware если naive
        if hasattr(trial_ends, "tzinfo") and trial_ends.tzinfo is None:
            trial_ends = trial_ends.replace(tzinfo=timezone.utc)
        if trial_ends > now:
            return "premium"

    # Маппинг legacy планов
    return _PLAN_ALIAS.get(plan, plan)


def get_limit(key: str, plan: str) -> int:
    """Получить числовой лимит для плана."""
    resolved = _PLAN_ALIAS.get(plan, plan)
    plan_limits = LIMITS.get(resolved, LIMITS["free"])
    return int(plan_limits.get(key, 0))


def is_brief_day(plan: str, user_timezone: str) -> bool:
    """Должен ли прийти бриф сегодня для данного плана."""
    import pytz
    resolved = _PLAN_ALIAS.get(plan, plan)
    try:
        tz = pytz.timezone(user_timezone or "Europe/Vilnius")
        today_weekday = datetime.now(tz).weekday()
    except Exception:
        today_weekday = datetime.now().weekday()
    plan_limits = LIMITS.get(resolved, LIMITS["free"])
    return today_weekday in plan_limits.get("brief_days", [1, 3])


def is_brief_day_tomorrow(plan: str, user_timezone: str) -> bool:
    """Должен ли прийти бриф завтра."""
    import pytz
    resolved = _PLAN_ALIAS.get(plan, plan)
    try:
        tz = pytz.timezone(user_timezone or "Europe/Vilnius")
        tomorrow_weekday = (datetime.now(tz).weekday() + 1) % 7
    except Exception:
        tomorrow_weekday = (datetime.now().weekday() + 1) % 7
    plan_limits = LIMITS.get(resolved, LIMITS["free"])
    return tomorrow_weekday in plan_limits.get("brief_days", [1, 3])


def get_trial_days_left(user) -> Optional[int]:
    """Сколько дней осталось в trial. None если нет trial."""
    trial_ends = getattr(user, "trial_ends_at", None)
    if not trial_ends:
        return None
    now = datetime.now(timezone.utc)
    if hasattr(trial_ends, "tzinfo") and trial_ends.tzinfo is None:
        trial_ends = trial_ends.replace(tzinfo=timezone.utc)
    delta = trial_ends - now
    days = delta.days
    return max(0, days)


def is_trial_active(user) -> bool:
    days = get_trial_days_left(user)
    return days is not None and days > 0


def is_trial_just_ended(user) -> bool:
    """Trial закончился в последние 24 часа."""
    trial_ends = getattr(user, "trial_ends_at", None)
    trial_started = getattr(user, "trial_started_at", None)
    if not trial_ends or not trial_started:
        return False
    now = datetime.now(timezone.utc)
    if hasattr(trial_ends, "tzinfo") and trial_ends.tzinfo is None:
        trial_ends = trial_ends.replace(tzinfo=timezone.utc)
    delta = now - trial_ends
    return 0 <= delta.total_seconds() <= 86400
