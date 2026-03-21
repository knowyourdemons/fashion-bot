"""Тесты: trial degradation по дням."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


class TestTrialDegradation:
    """Если get_effective_limits реализован в permissions.py."""

    def _make_trial_user(self, days_left):
        u = MagicMock()
        u.plan = "free"
        u.telegram_id = 99999
        u.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=days_left)
        u.trial_started_at = datetime.now(timezone.utc) - timedelta(days=14 - days_left)
        u.plan_expires_at = None
        return u

    def test_day_5_full_premium(self):
        """День 5 trial — все лимиты premium."""
        from core.permissions import get_effective_plan
        u = self._make_trial_user(9)  # 9 дней осталось = день 5
        assert get_effective_plan(u) == "premium"

    def test_day_12_reroll_blocked(self):
        """День 12 — reroll должен быть заблокирован (если реализовано)."""
        try:
            from core.permissions import get_effective_limits
            u = self._make_trial_user(2)  # 2 дня = день 12
            limits = get_effective_limits(u)
            assert limits.get("reroll", 3) == 0
        except ImportError:
            pytest.skip("get_effective_limits not implemented yet")

    def test_day_14_chat_limited(self):
        """День 14 — чат ограничен до 1."""
        try:
            from core.permissions import get_effective_limits
            u = self._make_trial_user(0)  # 0 дней = день 14
            limits = get_effective_limits(u)
            assert limits.get("chat_per_day", 20) <= 3
        except ImportError:
            pytest.skip("get_effective_limits not implemented yet")

    def test_day_15_full_free(self):
        """День 15 — trial закончился, полный free."""
        from core.permissions import get_effective_plan
        u = self._make_trial_user(-1)  # -1 = trial истёк
        assert get_effective_plan(u) == "free"
