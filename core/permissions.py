"""
Планы, лимиты и конверсионные триггеры.
"""
from typing import Any

from exceptions import PermissionDeniedError, WardrobeFullError

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
