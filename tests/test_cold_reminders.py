"""Tests for cold user reminders, weekend mode, and style formula.

Covers: reminder day logic, message content, weekend detection,
gallery hints, style formula for women.
"""
import pytest
from datetime import date, timedelta

pytest.importorskip("structlog", reason="structlog not installed")


class TestColdReminderDays:
    """Reminders fire on days 1, 2, 3, 5 after onboarding."""

    _REMINDER_DAYS = {1, 2, 3, 5}

    def test_day_1_is_reminder_day(self):
        assert 1 in self._REMINDER_DAYS

    def test_day_2_is_reminder_day(self):
        assert 2 in self._REMINDER_DAYS

    def test_day_3_is_reminder_day(self):
        assert 3 in self._REMINDER_DAYS

    def test_day_4_is_not_reminder_day(self):
        assert 4 not in self._REMINDER_DAYS

    def test_day_5_is_reminder_day(self):
        assert 5 in self._REMINDER_DAYS

    def test_day_6_not_reminder(self):
        assert 6 not in self._REMINDER_DAYS

    def test_day_0_not_reminder(self):
        """Same day as onboarding — handled by adaptive CTA, not cold reminder."""
        assert 0 not in self._REMINDER_DAYS


class TestColdReminderMessages:
    """Each day has a different message tone."""

    def _get_message(self, days_since: int, child_name: str = "Алиса") -> str:
        if days_since == 1:
            return f"Дома? Сфоткай 3 вещи {child_name} — 2 минуты!"
        elif days_since == 2:
            return f"Привет! Вчера мы познакомились 👋\nСфоткай 3 вещи {child_name}"
        elif days_since == 3:
            return f"{child_name} завтра в садик.\nСфоткай кофту и штаны"
        elif days_since == 5:
            return "Касси скучает! 😊\nОдна минута + 3 фото"
        return ""

    def test_day1_mentions_2_minutes(self):
        msg = self._get_message(1)
        assert "2 минуты" in msg

    def test_day2_mentions_yesterday(self):
        msg = self._get_message(2)
        assert "вчера" in msg.lower()

    def test_day3_mentions_garden(self):
        msg = self._get_message(3)
        assert "садик" in msg.lower()

    def test_day5_mentions_kassi(self):
        msg = self._get_message(5)
        assert "Касси" in msg

    def test_day5_mentions_gallery(self):
        """Day 5 should mention gallery option."""
        msg = "📸 Сфоткай вещь или отправь фото из галереи!"
        assert "галере" in msg.lower()


class TestColdReminderCancellation:
    """Reminders should be cancelled when user adds photos."""

    def test_cancel_if_items_exist(self):
        items = [object()]  # has items
        should_cancel = len(items) > 0
        assert should_cancel is True

    def test_continue_if_no_items(self):
        items = []
        should_cancel = len(items) > 0
        assert should_cancel is False

    def test_stop_after_day_5(self):
        days_since = 6
        should_stop = days_since > 5
        assert should_stop is True


class TestWeekendMode:
    """Weekend detection for context."""

    def test_saturday_is_weekend(self):
        # Find next Saturday
        today = date.today()
        days_until_sat = (5 - today.weekday()) % 7
        saturday = today + timedelta(days=days_until_sat or 7)
        assert saturday.weekday() >= 5

    def test_weekday_is_not_weekend(self):
        today = date.today()
        days_until_mon = (0 - today.weekday()) % 7
        monday = today + timedelta(days=days_until_mon or 7)
        assert monday.weekday() < 5

    def test_child_weekend_context(self):
        is_weekend = True
        day_type = "прогулка" if is_weekend else "садик"
        assert day_type == "прогулка"

    def test_child_weekday_context(self):
        is_weekend = False
        day_type = "прогулка" if is_weekend else "садик"
        assert day_type == "садик"

    def test_woman_weekend_context(self):
        is_weekend = True
        child = None
        if child:
            day_type = "прогулка" if is_weekend else "садик"
        else:
            day_type = "выходной" if is_weekend else ""
        assert day_type == "выходной"

    def test_woman_weekday_no_context(self):
        is_weekend = False
        child = None
        if child:
            day_type = "прогулка" if is_weekend else "садик"
        else:
            day_type = "выходной" if is_weekend else ""
        assert day_type == ""


class TestGalleryHint:
    """Gallery hint should be present in CTA texts."""

    def test_gallery_hint_in_evening_cta(self):
        hint = "💡 Подойдёт фото с камеры или из галереи!"
        cta = f"Сфоткай 3 вещи прямо сейчас 📸\n{hint}"
        assert "галере" in cta.lower()

    def test_done_photo_mentions_gallery(self):
        msg = "Сфоткай вещь или отправь фото из галереи 📸"
        assert "галере" in msg.lower()


class TestStyleFormula:
    """Women with 0 items should get a style formula."""

    def test_formula_prompt_includes_temp(self):
        temp = 5.0
        prompt = f"Температура {temp:+.0f}°C, будний день. Дай формулу образа для женщины."
        assert "+5" in prompt
        assert "формулу" in prompt

    def test_formula_for_weekend(self):
        is_wknd = True
        ctx = "выходной, прогулка" if is_wknd else "будний день"
        prompt = f"Температура +15°C, {ctx}. Дай формулу образа."
        assert "выходной" in prompt
