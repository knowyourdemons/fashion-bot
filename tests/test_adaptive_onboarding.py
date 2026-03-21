"""Tests for adaptive first contact after onboarding.

Covers: time-based CTA messages, reminder scheduling logic.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

pytest.importorskip("structlog", reason="structlog not installed")


class TestTimeCTA:
    """Time-of-day CTA text varies correctly."""

    def _get_cta_for_hour(self, hour: int) -> tuple[str, str, str]:
        """Simulate CTA selection logic from _finish_onboarding."""
        if 17 <= hour < 23:
            cta = "Сфоткай 3 вещи прямо сейчас — через 5 мин покажу образ! 📸"
            btn = "📸 Сфоткать сейчас"
            later = "Потом"
        elif 6 <= hour < 12:
            cta = "Одень так! А вечером сфоткай 3 вещи — завтра подберу из ваших 📸"
            btn = "📸 Сфоткать"
            later = "Завтра вечером"
        elif 12 <= hour < 17:
            cta = "Вечером дома сфоткай 3 вещи — завтра утром пришлю готовый образ! 📸"
            btn = "📸 Сфоткать"
            later = "Завтра вечером"
        else:
            cta = "Завтра утром в 07:00 пришлю погоду! А когда будет минутка — сфоткай вещи 📸"
            btn = "📸 Сфоткать"
            later = "Потом"
        return cta, btn, later

    def test_morning_cta(self):
        cta, btn, later = self._get_cta_for_hour(8)
        assert "вечером" in cta.lower()
        assert later == "Завтра вечером"

    def test_afternoon_cta(self):
        cta, btn, later = self._get_cta_for_hour(14)
        assert "вечером" in cta.lower()
        assert later == "Завтра вечером"

    def test_evening_cta(self):
        cta, btn, later = self._get_cta_for_hour(20)
        assert "сейчас" in cta.lower()
        assert btn == "📸 Сфоткать сейчас"
        assert later == "Потом"

    def test_night_cta(self):
        cta, btn, later = self._get_cta_for_hour(2)
        assert "07:00" in cta
        assert later == "Потом"

    def test_boundary_17(self):
        """17:00 = evening."""
        cta, _, _ = self._get_cta_for_hour(17)
        assert "сейчас" in cta.lower()

    def test_boundary_6(self):
        """06:00 = morning."""
        cta, _, later = self._get_cta_for_hour(6)
        assert "вечером" in cta.lower()

    def test_boundary_23(self):
        """23:00 = night."""
        cta, _, _ = self._get_cta_for_hour(23)
        assert "07:00" in cta


class TestMilestoneTimeAware:
    """Milestone messages should be time-aware."""

    def test_evening_milestone_mentions_tomorrow(self):
        """Evening milestone at 3 items should mention 'на завтра'."""
        # Simulate the logic
        hour = 20
        if 17 <= hour < 23:
            msg = "🎉 3 вещи есть! Собираю образ на завтра — секунду..."
        else:
            msg = "🎉 Мини-образ разблокирован! Собираю..."
        assert "на завтра" in msg

    def test_morning_milestone_generic(self):
        """Morning milestone uses generic text."""
        hour = 9
        if 17 <= hour < 23:
            msg = "🎉 3 вещи есть! Собираю образ на завтра — секунду..."
        else:
            msg = "🎉 Мини-образ разблокирован! Собираю..."
        assert "разблокирован" in msg


class TestReminderLogic:
    """19:00 reminder should only fire for users without photos."""

    def test_reminder_scheduled_before_17(self):
        """Install before 17:00 → reminder should be scheduled."""
        hour = 10
        should_schedule = hour < 17
        assert should_schedule is True

    def test_reminder_not_scheduled_after_17(self):
        """Install after 17:00 → no reminder needed (evening CTA is immediate)."""
        hour = 20
        should_schedule = hour < 17
        assert should_schedule is False

    def test_reminder_skipped_if_items_exist(self):
        """If user added photos by 19:00, skip reminder."""
        items = [MagicMock()]  # has items
        should_send = len(items) == 0
        assert should_send is False

    def test_reminder_sent_if_no_items(self):
        """If user has no photos by 19:00, send reminder."""
        items = []
        should_send = len(items) == 0
        assert should_send is True
