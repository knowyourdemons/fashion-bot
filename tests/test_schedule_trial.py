"""Тесты: trial юзеры получают бриф, а не тизер."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


class TestScheduleTrialFilter:
    """schedule_all() должен отправлять trial юзерам бриф, не тизер."""

    def _make_user(self, plan="free", trial_days=None, telegram_id=99999):
        u = MagicMock()
        u.id = "test-user-id"
        u.telegram_id = telegram_id
        u.plan = plan
        u.city = "Vilnius"
        u.timezone = "Europe/Vilnius"
        u.is_active = True
        u.onboarding_completed = True
        u.deleted_at = None
        if trial_days is not None:
            u.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=trial_days)
            u.trial_started_at = datetime.now(timezone.utc) - timedelta(days=14 - trial_days)
        else:
            u.trial_ends_at = None
            u.trial_started_at = None
        u.plan_expires_at = None
        return u

    def test_trial_user_is_not_free_for_brief(self):
        """Trial юзер (plan=free, trial_ends_at в будущем) должен получить бриф."""
        user = self._make_user("free", trial_days=7)
        from core.permissions import get_effective_plan
        assert get_effective_plan(user) == "premium"

    def test_expired_trial_is_free(self):
        """Expired trial = free, получает тизер."""
        user = self._make_user("free", trial_days=None)
        user.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        user.trial_started_at = datetime.now(timezone.utc) - timedelta(days=15)
        from core.permissions import get_effective_plan
        assert get_effective_plan(user) == "free"

    def test_no_trial_free_is_free(self):
        """Юзер без trial = free, получает тизер."""
        user = self._make_user("free", trial_days=None)
        from core.permissions import get_effective_plan
        assert get_effective_plan(user) == "free"

    def test_paid_premium_is_premium(self):
        """Платящий premium не зависит от trial."""
        user = self._make_user("premium")
        user.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        from core.permissions import get_effective_plan
        assert get_effective_plan(user) == "premium"
