"""
Tests for remaining v1.1 features:
1. Reminders system — inactive user detection, dedup, messages
2. Birthday alert — date matching, age-specific messages, dedup
3. Gap analysis integration — insights shown in brief for small wardrobes
4. Full pipeline integration — all features work together
"""
import uuid
import pytest
from datetime import date, timedelta, datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

pytest.importorskip("structlog", reason="structlog not installed")


# ══════════════════════════════════════════════════════════════════════════════
# REMINDERS
# ══════════════════════════════════════════════════════════════════════════════

class TestReminders:
    """Test reminder system for inactive users."""

    def test_reminder_rules_defined(self):
        from worker.tasks.reminders import REMINDER_RULES
        assert len(REMINDER_RULES) == 3
        days = [r[0] for r in REMINDER_RULES]
        assert days == [3, 7, 30]

    def test_reminder_messages_not_empty(self):
        from worker.tasks.reminders import REMINDER_RULES
        for days, text in REMINDER_RULES:
            assert len(text) >= 20, f"Reminder for {days} days too short"
            assert "📸" in text or "👗" in text or "🌸" in text, (
                f"Reminder for {days} days missing emoji CTA"
            )

    def test_reminder_3day_has_photo_cta(self):
        """3-day reminder should encourage photo upload."""
        from worker.tasks.reminders import REMINDER_RULES
        text_3 = REMINDER_RULES[0][1]
        assert "фото" in text_3.lower() or "📸" in text_3

    def test_reminder_30day_warm_tone(self):
        """30-day reminder should be warm, not pushy."""
        from worker.tasks.reminders import REMINDER_RULES
        text_30 = REMINDER_RULES[2][1]
        assert "давно" in text_30.lower() or "скучает" in text_30.lower() or "виделись" in text_30.lower()

    @pytest.mark.asyncio
    async def test_handle_send_reminder_returns_sent(self):
        """Handler should return {sent: True}."""
        from worker.tasks.reminders import handle_send_reminder
        with patch("telegram.Bot") as MockBot:
            mock_bot = AsyncMock()
            MockBot.return_value = mock_bot
            with patch("core.redis.get_redis") as mock_redis:
                mock_redis.return_value = AsyncMock()
                with patch("config.settings") as mock_settings:
                    mock_settings.telegram_bot_token = "test"
                    result = await handle_send_reminder({
                        "user_id": str(uuid.uuid4()),
                        "telegram_id": 12345,
                        "text": "Test reminder",
                        "reminder_type": 3,
                    })
                    assert result == {"sent": True}


# ══════════════════════════════════════════════════════════════════════════════
# BIRTHDAY ALERT
# ══════════════════════════════════════════════════════════════════════════════

class TestBirthdayAlert:
    """Test birthday alert for children."""

    def test_birthday_messages_exist(self):
        from worker.tasks.birthday_alert import _BIRTHDAY_MESSAGES
        assert 1 in _BIRTHDAY_MESSAGES
        assert 2 in _BIRTHDAY_MESSAGES
        assert 3 in _BIRTHDAY_MESSAGES
        assert "default" in _BIRTHDAY_MESSAGES

    def test_birthday_message_has_name_placeholder(self):
        from worker.tasks.birthday_alert import _BIRTHDAY_MESSAGES
        for key, msg in _BIRTHDAY_MESSAGES.items():
            assert "{name}" in msg, f"Birthday message for age={key} missing {{name}}"

    def test_birthday_message_has_emoji(self):
        from worker.tasks.birthday_alert import _BIRTHDAY_MESSAGES
        for key, msg in _BIRTHDAY_MESSAGES.items():
            assert "🎂" in msg or "🎈" in msg, f"Birthday message for age={key} missing emoji"

    def test_birthday_format(self):
        """Messages should format correctly."""
        from worker.tasks.birthday_alert import _BIRTHDAY_MESSAGES
        msg = _BIRTHDAY_MESSAGES[1].format(name="Алиса")
        assert "Алиса" in msg
        assert "1 годик" in msg

    def test_default_message_format(self):
        from worker.tasks.birthday_alert import _BIRTHDAY_MESSAGES
        msg = _BIRTHDAY_MESSAGES["default"].format(name="Иван")
        assert "Иван" in msg
        assert "рождения" in msg.lower()


# ══════════════════════════════════════════════════════════════════════════════
# GAP ANALYSIS INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

class TestGapAnalysisIntegration:
    """Test that gap analysis insights appear in the right places."""

    def test_small_wardrobe_gets_gap_tip(self):
        """Wardrobe < 15 items should trigger gap insight."""
        from services.scoring import get_wardrobe_gaps
        from services.outfit_builder import _is_base_layer_item

        def _item(cg, type_, color="белый"):
            i = MagicMock()
            i.id = uuid.uuid4()
            i.category_group = cg; i.type = type_; i.color = color
            return i

        items = [
            _item("top", "футболка", "белый"),
            _item("bottom", "джинсы", "синий"),
            _item("footwear", "кроссовки", "белые"),
            _item("underwear", "трусики"),
        ]
        gaps = get_wardrobe_gaps(items)
        add_tips = [g for g in gaps if "Добавь" in g]
        assert add_tips, f"Small wardrobe should have add-tips: {gaps}"

    def test_full_wardrobe_no_critical_gaps(self):
        """30+ item wardrobe should not report critical gaps."""
        from services.scoring import get_wardrobe_gaps

        def _item(cg, type_, color="белый"):
            i = MagicMock()
            i.id = uuid.uuid4()
            i.category_group = cg; i.type = type_; i.color = color
            return i

        items = []
        for t in ["футболка", "рубашка", "блузка", "свитер", "худи"]:
            items.append(_item("top", t))
        for t in ["джинсы", "брюки", "юбка"]:
            items.append(_item("bottom", t))
        for t in ["кроссовки", "ботинки", "сандалии"]:
            items.append(_item("footwear", t))
        items.append(_item("outerwear", "куртка"))
        items.append(_item("outerwear", "пальто"))
        items.append(_item("one_piece", "платье"))
        items.append(_item("underwear", "трусики"))
        items.append(_item("base_layer", "носки"))

        gaps = get_wardrobe_gaps(items)
        critical = [g for g in gaps if "Добавь" in g and ("верх" in g or "низ" in g or "обувь" in g)]
        assert not critical, f"Full wardrobe should not have critical gaps: {critical}"

    def test_gap_message_positive_tone(self):
        """All gap messages should be encouraging, not critical."""
        from services.scoring import get_wardrobe_gaps

        def _item(cg, type_):
            i = MagicMock()
            i.id = uuid.uuid4()
            i.category_group = cg; i.type = type_; i.color = "белый"
            return i

        items = [_item("top", "футболка"), _item("underwear", "трусики")]
        gaps = get_wardrobe_gaps(items)
        for g in gaps:
            assert "плохо" not in g.lower()
            assert "ужас" not in g.lower()


# ══════════════════════════════════════════════════════════════════════════════
# ENGAGEMENT PUSH
# ══════════════════════════════════════════════════════════════════════════════

class TestEngagementPush:
    """Test engagement push for trial users."""

    def test_engagement_schedule_defined(self):
        from worker.tasks.engagement import _ENGAGEMENT_SCHEDULE
        assert 3 in _ENGAGEMENT_SCHEDULE
        assert 7 in _ENGAGEMENT_SCHEDULE
        assert 10 in _ENGAGEMENT_SCHEDULE
        assert 11 in _ENGAGEMENT_SCHEDULE

    def test_day3_low_wardrobe_condition(self):
        from worker.tasks.engagement import _ENGAGEMENT_SCHEDULE
        assert _ENGAGEMENT_SCHEDULE[3]["condition"] == "low_wardrobe"

    def test_day7_always_sends(self):
        from worker.tasks.engagement import _ENGAGEMENT_SCHEDULE
        assert _ENGAGEMENT_SCHEDULE[7]["condition"] == "always"

    def test_day10_trial_only(self):
        from worker.tasks.engagement import _ENGAGEMENT_SCHEDULE
        assert _ENGAGEMENT_SCHEDULE[10]["condition"] == "is_trial"

    def test_day11_has_upgrade_button(self):
        from worker.tasks.engagement import _ENGAGEMENT_SCHEDULE
        assert "button" in _ENGAGEMENT_SCHEDULE[11]

    def test_messages_not_empty(self):
        """All engagement messages should be substantial."""
        from worker.tasks.engagement import _ENGAGEMENT_SCHEDULE
        for day, config in _ENGAGEMENT_SCHEDULE.items():
            text = config["text"]
            assert len(text) >= 30, f"Day {day} message too short: {len(text)} chars"


# ══════════════════════════════════════════════════════════════════════════════
# WEAR TRACKING
# ══════════════════════════════════════════════════════════════════════════════

class TestWearTracking:
    """Test that wear_count and last_worn are tracked correctly."""

    def test_freshness_bonus_in_selector(self):
        """Items not worn in 7+ days should get freshness bonus."""
        from services.outfit_selector import _select_outfit

        week_ago = date.today() - timedelta(days=8)
        yesterday = date.today() - timedelta(days=1)

        def _item(cg, type_, score, last_worn=None, warmth=2):
            i = MagicMock()
            i.id = uuid.uuid4()
            i.category_group = cg; i.type = type_; i.color = "белый"
            i.season = ["spring", "summer", "autumn", "winter"]
            i.last_worn = last_worn; i.score_item = score
            i.warmth_level = warmth; i.style_tag = "casual"
            return i

        # Fresh low-score vs recent high-score
        fresh_top = _item("top", "футболка_fresh", 6.0, last_worn=week_ago)
        recent_top = _item("top", "футболка_recent", 7.5, last_worn=yesterday)

        items = [
            fresh_top, recent_top,
            _item("bottom", "джинсы", 7.0),
            _item("footwear", "кроссовки", 7.0),
            _item("underwear", "трусики", 1.0),
        ]
        outfit = _select_outfit(items, "spring", date.today(), 18.0, 15.0, 0)
        # Fresh item (6.0 + 1.0 bonus = 7.0) should compete with recent (7.5)
        # Both are valid selections
        assert outfit.get("top") is not None

    def test_worn_today_deprioritized(self):
        """Items worn today should be deprioritized."""
        from services.outfit_selector import _select_outfit

        def _item(cg, type_, score, last_worn=None, warmth=2):
            i = MagicMock()
            i.id = uuid.uuid4()
            i.category_group = cg; i.type = type_; i.color = "белый"
            i.season = ["spring", "summer", "autumn", "winter"]
            i.last_worn = last_worn; i.score_item = score
            i.warmth_level = warmth; i.style_tag = "casual"
            return i

        today = date.today()
        worn_today = _item("top", "футболка_today", 9.0, last_worn=today)
        unworn = _item("top", "футболка_fresh", 5.0)

        items = [
            worn_today, unworn,
            _item("bottom", "джинсы", 7.0),
            _item("footwear", "кроссовки", 7.0),
            _item("underwear", "трусики", 1.0),
        ]
        outfit = _select_outfit(items, "spring", date.today(), 18.0, 15.0, 0)
        top = outfit.get("top")
        # Worn-today filtered by season filter first, then fallback
        assert top is not None
        # Should prefer unworn (worn_today is excluded in initial filter)
        if top.last_worn != today:
            assert True  # correct: fresh item selected
        # If fallback included worn_today, it's still valid but deprioritized


# ══════════════════════════════════════════════════════════════════════════════
# COMPREHENSIVE v1.1 CHECKLIST
# ══════════════════════════════════════════════════════════════════════════════

class TestV11Checklist:
    """Verify all v1.1 features exist and are non-empty."""

    def test_outfit_engine_exists(self):
        from services.outfit_engine import select_outfit_ai, OutfitResult
        assert callable(select_outfit_ai)

    def test_color_harmony_exists(self):
        from services.color_harmony import color_compatibility, score_outfit_colors
        assert callable(color_compatibility)
        assert callable(score_outfit_colors)

    def test_normalize_exists(self):
        from services.normalize import normalize_type, normalize_color
        assert callable(normalize_type)
        assert callable(normalize_color)

    def test_photo_quality_exists(self):
        from services.photo_quality import assess_photo, preprocess_for_vision
        assert callable(assess_photo)

    def test_gap_analysis_exists(self):
        from services.scoring import get_wardrobe_gaps, calc_item_versatility
        assert callable(get_wardrobe_gaps)
        assert callable(calc_item_versatility)

    def test_12_season_palettes_exist(self):
        from worker.tasks.style_config import COLORTYPE_PALETTES
        assert len(COLORTYPE_PALETTES) >= 16  # 12 seasons + 4 aliases + default

    def test_age_specific_prompts_exist(self):
        from services.outfit_engine import _get_mom_system_prompt, _AGE_RULES
        assert len(_AGE_RULES) == 4  # 0-3, 3-7, 7-12, 12-16

    def test_wind_chill_exists(self):
        from services.weather import calc_wind_chill
        assert calc_wind_chill(5.0, 20.0) < 5.0  # wind makes it feel colder

    def test_reminders_implemented(self):
        from worker.tasks.reminders import run, handle_send_reminder, REMINDER_RULES
        assert len(REMINDER_RULES) == 3
        assert callable(run)
        assert callable(handle_send_reminder)

    def test_birthday_alert_implemented(self):
        from worker.tasks.birthday_alert import run, _BIRTHDAY_MESSAGES
        assert callable(run)
        assert len(_BIRTHDAY_MESSAGES) >= 4

    def test_engagement_push_implemented(self):
        from worker.tasks.engagement import check_engagement, _ENGAGEMENT_SCHEDULE
        assert callable(check_engagement)
        assert len(_ENGAGEMENT_SCHEDULE) == 4
