"""Verify trial degradation is wired into all handler limits."""
import pathlib
import pytest


class TestTrialDegradationWiring:
    """get_effective_limits must be used in handlers that enforce limits."""

    def test_brief_uses_effective_limits(self):
        content = pathlib.Path("bot/handlers/brief.py").read_text()
        assert "get_effective_limits" in content
        assert 'effective.get("reroll"' in content

    def test_text_uses_effective_limits(self):
        content = pathlib.Path("bot/handlers/text.py").read_text()
        assert "get_effective_limits" in content
        assert '_eff_limits.get("chat_per_day"' in content

    def test_help_uses_effective_limits(self):
        content = pathlib.Path("bot/handlers/help.py").read_text()
        assert "get_effective_limits" in content

    def test_evening_schedule_checks_degradation(self):
        content = pathlib.Path("worker/tasks/morning_brief.py").read_text()
        # schedule_evening should check evening_brief limit
        start = content.find("async def schedule_evening")
        end = content.find("\nasync def ", start + 1)
        fn = content[start:end] if end > start else content[start:]
        assert "get_effective_limits" in fn
        assert 'evening_brief' in fn

    def test_temperature_rounded_in_child_brief(self):
        """Weather line should use round() not raw float."""
        content = pathlib.Path("worker/tasks/morning_brief.py").read_text()
        # The child brief weather line (line ~524)
        assert "round(temp_m)" in content or ":.0f}" in content
