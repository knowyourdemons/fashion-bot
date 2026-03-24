"""
Планы, лимиты и конверсионные триггеры.
Источник правды: CLAUDE.md → "Система планов и лимитов".
"""
from datetime import datetime, timezone
from typing import Any, Optional


# ── Лимиты по планам ─────────────────────────────────────────────────────────

LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "photos_per_day":     3,
        "wardrobe_size":      30,
        "rate_per_day":       3,
        "chat_per_day":       3,
        "outfit_req_per_day": 1,
        "brief_days":         [1, 3],   # вт=1, чт=3 (weekday, 0=пн)
        "brief_weekends":     False,
        "children_max":       1,
        "reroll":             1,
        "evening_brief":      False,
        "gap_analysis":       False,
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
        "reroll":             3,
        "evening_brief":      True,
        "gap_analysis":       True,
    },
    # ultra — отложен до v2.0, но plan="ultra" в БД должен работать без краша
    "ultra": {
        "photos_per_day":     100,
        "wardrobe_size":      2000,
        "rate_per_day":       50,
        "chat_per_day":       50,
        "outfit_req_per_day": 10,
        "brief_days":         [0, 1, 2, 3, 4, 5, 6],
        "brief_weekends":     True,
        "children_max":       10,
        "reroll":             10,
        "evening_brief":      True,
        "gap_analysis":       True,
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
        "reroll":             9999,
        "evening_brief":      True,
        "gap_analysis":       True,
    },
}

# Маппинг legacy планов из БД → новые (для плавного перехода)
_PLAN_ALIAS: dict[str, str] = {
    "basic":  "premium",
    "family": "premium",
}

# ── Цены (usd в центах для Stripe!) ──────────────────────────────────────────

PRICES: dict[str, dict[str, Any]] = {
    "premium_monthly": {
        "usd": 900, "stars": 700, "period_months": 1,
        "label": "Месяц — $9",
        "label_usd": "Месяц — $9",
        "label_stars": "Месяц — 700 ⭐",
        "stripe_price_id": "",  # заполнить из Stripe dashboard
    },
    "premium_quarterly": {
        "usd": 2200, "stars": 1700, "period_months": 3,
        "label": "3 месяца — $22 (экономия $5)",
        "label_usd": "3 месяца — $22 (экономия $5)",
        "label_stars": "3 месяца — 1700 ⭐",
        "stripe_price_id": "",
    },
    "premium_yearly": {
        "usd": 7200, "stars": 5500, "period_months": 12,
        "label": "Год — $72 (экономия $36)",
        "label_usd": "Год — $72 (экономия $36) ⭐ Лучшая цена",
        "label_stars": "Год — 5500 ⭐",
        "stripe_price_id": "",
    },
}

# ── Константы (единый источник для сообщений и логики) ─────────────────────

TRIAL_DAYS = 14
PHOTO_TARGET = 5          # минимум вещей для первого брифа
MIN_ITEMS_GAP_ANALYSIS = 5  # минимум для анализа гардероба/капсулы
NUDGE_THRESHOLD = 8       # ниже этого — nudge "добавь ещё"


def premium_features_text() -> dict[str, str]:
    """Возвращает словарь фича→текст для Premium, из LIMITS."""
    p = LIMITS["premium"]
    return {
        "photos":   str(p["photos_per_day"]),
        "rate":     str(p["rate_per_day"]),
        "chat":     str(p["chat_per_day"]),
        "children": str(p["children_max"]),
        "wardrobe": str(p["wardrobe_size"]),
    }


# ── Ultra фичи (заглушки для promote) ────────────────────────────────────────

ULTRA_FEATURES = [
    "🛍 Шоппинг-лист с партнёрскими ссылками",
    "💎 Капсульный гардероб на сезон",
    "📊 Глубокий анализ гардероба",
    "👨‍👩‍👧 Семейный аккаунт (папа тоже видит образы)",
    "🔄 Передача вещей между детьми",
    "📦 Хранение архива вещей",
]


# ── Основные функции ──────────────────────────────────────────────────────────

def get_effective_plan(user) -> str:
    """
    Возвращает реальный план с учётом trial, paid subscription и admin.
    Приоритет: admin > paid (plan_expires_at > now) > trial (trial_ends_at > now) > free.
    """
    if not user:
        return "free"

    # Admin через telegram_id
    try:
        from config import settings
        if int(getattr(user, "telegram_id", -1)) in settings.admin_ids_list:
            return "admin"
    except Exception:
        pass

    plan = getattr(user, "plan", "free") or "free"
    # Алиасы legacy планов (basic/family → premium) для самого плана в БД
    effective_stored = _PLAN_ALIAS.get(plan, plan)
    now = datetime.now(timezone.utc)

    # Активная платная подписка
    plan_expires = getattr(user, "plan_expires_at", None)
    if plan_expires and effective_stored in ("premium", "ultra"):
        exp = plan_expires
        if hasattr(exp, "tzinfo") and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > now:
            return effective_stored
        return "free"

    # Активный trial
    trial_ends = getattr(user, "trial_ends_at", None)
    if trial_ends:
        if hasattr(trial_ends, "tzinfo") and trial_ends.tzinfo is None:
            trial_ends = trial_ends.replace(tzinfo=timezone.utc)
        if trial_ends > now:
            return "premium"

    # Платный план без действующей подписки и без trial → деградация до free
    if effective_stored in ("premium", "ultra"):
        return "free"
    return "free"


def get_limit(key: str, plan: str) -> int:
    """Получить числовой лимит для плана. Неизвестный план → free лимиты + warning."""
    resolved = _PLAN_ALIAS.get(plan, plan)
    plan_limits = LIMITS.get(resolved)
    if plan_limits is None:
        import structlog
        structlog.get_logger().warning("permissions.unknown_plan",
                                        plan=plan, resolved=resolved, fallback="free")
        plan_limits = LIMITS["free"]
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
    """Сколько дней осталось в trial. None если trial нет или истёк."""
    trial_ends = getattr(user, "trial_ends_at", None)
    if not trial_ends:
        return None
    now = datetime.now(timezone.utc)
    if hasattr(trial_ends, "tzinfo") and trial_ends.tzinfo is None:
        trial_ends = trial_ends.replace(tzinfo=timezone.utc)
    if trial_ends <= now:
        return None
    return max(0, (trial_ends - now).days)


def is_trial_active(user) -> bool:
    days = get_trial_days_left(user)
    return days is not None and days > 0


def days_until_expiry(user) -> Optional[int]:
    """Дней до конца платной подписки (не trial). None если нет подписки."""
    plan_expires = getattr(user, "plan_expires_at", None)
    if not plan_expires:
        return None
    now = datetime.now(timezone.utc)
    if hasattr(plan_expires, "tzinfo") and plan_expires.tzinfo is None:
        plan_expires = plan_expires.replace(tzinfo=timezone.utc)
    return max(0, (plan_expires - now).days)


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


def can_gap_analysis(plan: str) -> bool:
    resolved = _PLAN_ALIAS.get(plan, plan)
    return bool(LIMITS.get(resolved, LIMITS["free"]).get("gap_analysis", False))


def get_effective_limits(user) -> dict:
    """Лимиты с учётом trial degradation (последние 3 дня trial → постепенное снижение)."""
    plan = get_effective_plan(user)
    limits = dict(LIMITS.get(plan, LIMITS["free"]))

    if plan == "premium" and is_trial_active(user):
        days_left = get_trial_days_left(user)
        if days_left is not None:
            if days_left <= 2:  # день 12
                limits["reroll"] = 0
            if days_left <= 1:  # день 13
                limits["evening_brief"] = False
            if days_left <= 0:  # день 14 (последний)
                limits["chat_per_day"] = 3
                limits["outfit_req_per_day"] = 1

    return limits
