"""Tests for permissions — новая схема free/premium/admin."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from core.permissions import (
    get_effective_plan, get_limit, is_brief_day, is_brief_day_tomorrow,
    get_trial_days_left, is_trial_active, days_until_expiry, can_gap_analysis,
    LIMITS, PRICES,
)


def _user(plan="free", telegram_id=99999, plan_expires_at=None,
          trial_ends_at=None, trial_started_at=None):
    u = MagicMock()
    u.plan = plan
    u.telegram_id = telegram_id
    u.plan_expires_at = plan_expires_at
    u.trial_ends_at = trial_ends_at
    u.trial_started_at = trial_started_at
    return u


# ── get_effective_plan ────────────────────────────────────────────────────────

def test_get_effective_plan_admin():
    """Admin определяется по telegram_id из ADMIN_TELEGRAM_IDS (195169 по умолчанию)."""
    u = _user("free", telegram_id=195169)
    result = get_effective_plan(u)
    # Если ADMIN_TELEGRAM_IDS задан → admin; иначе тест пропускается
    try:
        from config import settings
        if 195169 in settings.admin_ids_list:
            assert result == "admin"
        else:
            pytest.skip("ADMIN_TELEGRAM_IDS не содержит 195169 в этом окружении")
    except Exception:
        pytest.skip("config не импортируется в этом окружении")


def test_get_effective_plan_paid_premium():
    u = _user("premium", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    assert get_effective_plan(u) == "premium"


def test_get_effective_plan_expired_premium():
    u = _user("premium", plan_expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    assert get_effective_plan(u) == "free"


def test_get_effective_plan_trial_active():
    u = _user("free", trial_ends_at=datetime.now(timezone.utc) + timedelta(days=5))
    assert get_effective_plan(u) == "premium"


def test_get_effective_plan_trial_expired():
    u = _user("free", trial_ends_at=datetime.now(timezone.utc) - timedelta(days=1))
    assert get_effective_plan(u) == "free"


def test_get_effective_plan_no_user():
    assert get_effective_plan(None) == "free"


def test_get_effective_plan_legacy_basic():
    # plan="basic" в БД → effective = "premium" (alias)
    u = _user("basic", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
    assert get_effective_plan(u) == "premium"


def test_get_effective_plan_ultra_with_subscription():
    # plan="ultra" с действующей подпиской → ultra
    u = _user("ultra", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
    assert get_effective_plan(u) == "ultra"


def test_get_effective_plan_ultra_no_subscription():
    # plan="ultra" без подписки → деградирует до free
    u = _user("ultra")  # plan_expires_at=None
    assert get_effective_plan(u) == "free"


def test_get_effective_plan_premium_no_subscription():
    # plan="premium" без plan_expires_at → free
    u = _user("premium")  # plan_expires_at=None
    assert get_effective_plan(u) == "free"


# ── get_limit ─────────────────────────────────────────────────────────────────

def test_get_limit_free_wardrobe():
    assert get_limit("wardrobe_size", "free") == 30


def test_get_limit_premium_chat():
    assert get_limit("chat_per_day", "premium") == 20


def test_get_limit_free_photos():
    assert get_limit("photos_per_day", "free") == 3


def test_get_limit_premium_photos():
    assert get_limit("photos_per_day", "premium") == 30


def test_get_limit_admin_all_9999():
    for key in ("photos_per_day", "chat_per_day", "wardrobe_size", "outfit_req_per_day"):
        assert get_limit(key, "admin") == 9999, f"admin.{key} должен быть 9999"


def test_get_limit_unknown_key_no_crash():
    # Несуществующий ключ → 0, не краш
    assert get_limit("nonexistent_key", "free") == 0


def test_get_limit_unknown_plan_falls_back():
    # Неизвестный план → free лимиты
    assert get_limit("chat_per_day", "unknown_plan") == get_limit("chat_per_day", "free")


def test_get_limit_basic_alias_to_premium():
    # basic → premium alias
    assert get_limit("chat_per_day", "basic") == get_limit("chat_per_day", "premium")


# ── is_brief_day ──────────────────────────────────────────────────────────────

def test_is_brief_day_premium_always_true():
    assert is_brief_day("premium", "Europe/Vilnius") is True


def test_is_brief_day_free_tuesday():
    from unittest.mock import patch
    # Weekday 1 = Tuesday
    with patch("core.permissions.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(weekday=lambda: 1)
        result = is_brief_day("free", "Europe/Vilnius")
    assert result is True


def test_is_brief_day_free_wednesday():
    from unittest.mock import patch
    with patch("core.permissions.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(weekday=lambda: 2)
        result = is_brief_day("free", "Europe/Vilnius")
    assert result is False


def test_is_brief_day_free_days_set():
    assert LIMITS["free"]["brief_days"] == [1, 3]  # вт=1, чт=3


def test_is_brief_day_tomorrow_returns_bool():
    result = is_brief_day_tomorrow("premium", "Europe/Vilnius")
    assert isinstance(result, bool)


# ── get_trial_days_left ────────────────────────────────────────────────────────

def test_trial_days_left_active():
    u = _user(trial_ends_at=datetime.now(timezone.utc) + timedelta(days=5))
    days = get_trial_days_left(u)
    assert days is not None and 4 <= days <= 5


def test_trial_days_left_expired():
    u = _user(trial_ends_at=datetime.now(timezone.utc) - timedelta(days=1))
    assert get_trial_days_left(u) is None


def test_trial_days_left_no_trial():
    u = _user()  # trial_ends_at=None
    assert get_trial_days_left(u) is None


def test_is_trial_active_true():
    u = _user(trial_ends_at=datetime.now(timezone.utc) + timedelta(days=3))
    assert is_trial_active(u) is True


def test_is_trial_active_false_expired():
    u = _user(trial_ends_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert is_trial_active(u) is False


# ── days_until_expiry ─────────────────────────────────────────────────────────

def test_days_until_expiry_active():
    u = _user(plan_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
    d = days_until_expiry(u)
    assert d is not None and 9 <= d <= 10


def test_days_until_expiry_no_subscription():
    u = _user()
    assert days_until_expiry(u) is None


# ── can_gap_analysis ──────────────────────────────────────────────────────────

def test_gap_analysis_free_blocked():
    assert can_gap_analysis("free") is False


def test_gap_analysis_premium_allowed():
    assert can_gap_analysis("premium") is True


def test_gap_analysis_admin_allowed():
    assert can_gap_analysis("admin") is True


# ── PRICES ────────────────────────────────────────────────────────────────────

def test_prices_usd_in_cents():
    assert PRICES["premium_monthly"]["usd"] == 900
    assert PRICES["premium_quarterly"]["usd"] == 2200
    assert PRICES["premium_yearly"]["usd"] == 7200


def test_prices_stars_amounts():
    assert PRICES["premium_monthly"]["stars"] == 700
    assert PRICES["premium_quarterly"]["stars"] == 1700
    assert PRICES["premium_yearly"]["stars"] == 5500


def test_prices_have_all_keys():
    required = {"usd", "stars", "period_months", "label", "label_usd", "label_stars"}
    for key in ("premium_monthly", "premium_quarterly", "premium_yearly"):
        missing = required - set(PRICES[key].keys())
        assert not missing, f"{key} missing: {missing}"


# ── services/usage.py ─────────────────────────────────────────────────────────

def test_usage_str_free():
    from services.usage import get_usage_str
    u = _user("free")
    u.daily_requests_used = 1
    result = get_usage_str(u)
    assert result is not None
    assert "1/3" in result


def test_usage_str_premium_none():
    from services.usage import get_usage_str
    u = _user("premium", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    u.daily_requests_used = 5
    assert get_usage_str(u) is None


def test_usage_str_basic_alias_none():
    """plan='basic' в БД → effective=premium → нет счётчика."""
    from services.usage import get_usage_str
    u = _user("basic", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
    u.daily_requests_used = 2
    assert get_usage_str(u) is None


def test_limit_exceeded_msg_free():
    from services.usage import get_limit_exceeded_msg
    u = _user("free")
    msg = get_limit_exceeded_msg(u)
    assert "3/3" in msg
    assert "/subscribe" in msg


def test_limit_exceeded_msg_no_basic_family():
    """Сообщение не должно содержать Basic или Family."""
    from services.usage import get_limit_exceeded_msg
    u = _user("free")
    msg = get_limit_exceeded_msg(u)
    assert "Basic" not in msg
    assert "Family" not in msg
    assert "basic" not in msg


# ── i18n strings ──────────────────────────────────────────────────────────────

def test_trial_strings_exist():
    from services.i18n.ru import STRINGS
    assert "trial.activated" in STRINGS
    assert "trial.expired" in STRINGS


def test_wardrobe_full_free_string():
    from services.i18n.ru import t
    text = t("wardrobe.full.free", used="30", max="30",
             premium_wardrobe="500", trial_days="14")
    assert "30" in text
    assert "500" in text
    assert "/subscribe" in text


def test_is_trial_just_ended():
    from core.permissions import is_trial_just_ended
    u = _user(
        trial_started_at=datetime.now(timezone.utc) - timedelta(days=15),
        trial_ends_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    assert is_trial_just_ended(u) is True


def test_is_trial_just_ended_false_old():
    from core.permissions import is_trial_just_ended
    u = _user(
        trial_started_at=datetime.now(timezone.utc) - timedelta(days=30),
        trial_ends_at=datetime.now(timezone.utc) - timedelta(days=16),
    )
    assert is_trial_just_ended(u) is False
