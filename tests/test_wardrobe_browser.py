"""Tests: wardrobe browser screens."""
import sys
sys.path.insert(0, "/app")

from bot.handlers.wardrobe_browser import (
    _build_overview_text,
    _build_overview_buttons,
    _filter_items,
    _short_color,
    _short_id,
    _CAT_ORDER,
)


class FakeItem:
    def __init__(self, **kw):
        self.id = kw.get("id", "12345678-1234-1234-1234-123456789012")
        self.category_group = kw.get("category_group", "top")
        self.type = kw.get("type", "футболка")
        self.color = kw.get("color", "белый")
        self.season = kw.get("season", ["spring", "summer"])
        self.photo_id = kw.get("photo_id", "photo123")
        self.photo_url = kw.get("photo_url", None)
        self.created_at = None
        self.wear_count = 0


def _items():
    return [
        FakeItem(category_group="outerwear", type="куртка", color="синий", season=["winter", "spring"]),
        FakeItem(category_group="top", type="футболка", color="белый", season=["summer"]),
        FakeItem(category_group="top", type="лонгслив", color="розовый", season=["spring", "autumn"]),
        FakeItem(category_group="bottom", type="джинсы", color="голубой"),
        FakeItem(category_group="footwear", type="ботинки", color="коричневый", season=["winter"]),
        FakeItem(category_group="one_piece", type="сарафан", color="серый", season=["summer"]),
    ]


class TestOverviewText:
    def test_contains_owner_name(self):
        text = _build_overview_text(_items(), "Алиса")
        assert "Алиса" in text

    def test_contains_total_count(self):
        text = _build_overview_text(_items(), "Алиса")
        assert "6 вещей" in text

    def test_contains_categories(self):
        text = _build_overview_text(_items(), "Алиса")
        assert "Верхняя" in text
        assert "Верх" in text
        assert "Обувь" in text

    def test_season_filter_changes_counts(self):
        text = _build_overview_text(_items(), "Алиса", season="winter")
        assert "Зима" in text
        # Only outerwear and footwear are winter
        assert "2 вещей" in text

    def test_season_filter_hides_empty_cats(self):
        text = _build_overview_text(_items(), "Алиса", season="winter")
        # one_piece has no winter items
        assert "Платья" not in text


class TestOverviewButtons:
    def test_has_category_buttons(self):
        markup = _build_overview_buttons(_items())
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert any("w:cat:top" in cb for cb in all_cb)

    def test_has_season_buttons(self):
        markup = _build_overview_buttons(_items())
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert any("w:sz:winter" in cb for cb in all_cb)

    def test_active_season_highlighted(self):
        markup = _build_overview_buttons(_items(), season="winter")
        all_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("[" in label and "Зима" in label for label in all_labels)

    def test_reset_button_when_filtered(self):
        markup = _build_overview_buttons(_items(), season="winter")
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "w:ov" in all_cb


class TestFilterItems:
    def test_filter_by_season(self):
        items = _items()
        winter = _filter_items(items, season="winter")
        assert len(winter) == 2

    def test_filter_by_category(self):
        items = _items()
        tops = _filter_items(items, category="top")
        assert len(tops) == 2

    def test_filter_combined(self):
        items = _items()
        result = _filter_items(items, season="summer", category="top")
        assert len(result) == 1


class TestHelpers:
    def test_short_color_no_truncation(self):
        assert _short_color("белый") == "белый"

    def test_short_color_truncation(self):
        result = _short_color("серо-зелёная клетка", 12)
        assert len(result) <= 12
        assert result.endswith(".")

    def test_short_id(self):
        uid = "12345678-1234-1234-1234-123456789012"
        assert _short_id(uid) == "12345678"
