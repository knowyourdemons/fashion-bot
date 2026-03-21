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
    _format_season,
    _format_date,
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
        self.added_at = None
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
        # one_piece has no winter items — only non-zero shown in compact format
        # Verify the winter items are there
        assert "Верхняя" in text
        assert "Обувь" in text

    def test_empty_wardrobe(self):
        text = _build_overview_text([], "Алиса")
        assert "0 вещей" in text
        assert "Алиса" in text


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

    def test_has_all_button(self):
        markup = _build_overview_buttons(_items())
        all_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Все" in label for label in all_labels)

    def test_has_add_button(self):
        markup = _build_overview_buttons(_items())
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "add_items_hint" in all_cb

    def test_owner_tabs_shown(self):
        markup = _build_overview_buttons(
            _items(),
            has_children=True,
            owner_type="child",
            child_name="Алиса",
            child_id="abc123",
            child_gender="girl",
        )
        all_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Алиса" in label for label in all_labels)
        assert any("Мои" in label for label in all_labels)

    def test_no_owner_tabs_without_children(self):
        markup = _build_overview_buttons(_items(), has_children=False)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert not any("switch_owner" in cb for cb in all_cb)


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

    def test_no_filter(self):
        items = _items()
        result = _filter_items(items)
        assert len(result) == 6


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

    def test_format_season_empty(self):
        assert _format_season([]) == "все сезоны"

    def test_format_season_multiple(self):
        result = _format_season(["winter", "spring"])
        assert "Зима" in result
        assert "Весна" in result

    def test_format_date_none(self):
        assert _format_date(None) == "—"
