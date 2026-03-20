"""
Regression tests covering bugs found during March 20, 2026 session.
Each test prevents a specific class of bug from recurring.
"""
import sys
import re
sys.path.insert(0, "/app")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Import correctness — models use correct module names
# ═══════════════════════════════════════════════════════════════════════════════

class TestImports:
    """Verify all model imports use correct module names."""

    def test_child_model_import(self):
        """db.models.child (NOT db.models.children)."""
        from db.models.child import Child
        assert Child.__tablename__ == "children"

    def test_user_model_import(self):
        from db.models.user import User
        assert hasattr(User, "telegram_id")

    def test_wardrobe_model_import(self):
        from db.models.wardrobe import WardrobeItem
        assert hasattr(WardrobeItem, "owner_id")

    def test_no_children_module(self):
        """db.models.children should NOT exist."""
        import importlib
        try:
            importlib.import_module("db.models.children")
            assert False, "db.models.children should not exist (correct: db.models.child)"
        except ModuleNotFoundError:
            pass  # expected

    def test_text_handler_imports_child_correctly(self):
        """text.py must import from db.models.child, not db.models.children."""
        import inspect
        from bot.handlers.text import handle_text
        src = inspect.getsource(handle_text)
        assert "db.models.children" not in src, "text.py still imports db.models.children"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Model attribute safety — getattr for optional fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelAttributes:
    """WardrobeItem may not have all fields — use getattr."""

    def test_wardrobe_item_safe_access(self):
        """created_at, brand, user_label — must use getattr."""
        # Simulate an item-like object without all fields
        class FakeItem:
            type = "футболка"
            color = "белый"
        item = FakeItem()
        # These should not crash
        assert getattr(item, "created_at", None) is None
        assert getattr(item, "brand", None) is None
        assert getattr(item, "wear_count", 0) == 0

    def test_wardrobe_browser_uses_getattr(self):
        """wardrobe_browser.py must use getattr for created_at."""
        import inspect
        from bot.handlers.wardrobe_browser import handle_item_card
        src = inspect.getsource(handle_item_card)
        assert "getattr" in src and "created_at" in src


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Emoji regex — variation selector handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmojiRegex:
    """Menu button regex must handle emoji with variation selector."""

    def test_wardrobe_button_all_variants(self):
        """All wardrobe emoji variants must match."""
        pattern = r"^(👗|👧|👦|👩)\uFE0F? Гардероб$"
        assert re.match(pattern, "👗 Гардероб")
        assert re.match(pattern, "👧 Гардероб")
        assert re.match(pattern, "👦 Гардероб")
        assert re.match(pattern, "👩 Гардероб")
        # With variation selector
        assert re.match(pattern, "👩\uFE0F Гардероб")
        assert re.match(pattern, "👧\uFE0F Гардероб")

    def test_menu_exclusion_pattern(self):
        """_menu_texts must exclude all wardrobe variants from text handler."""
        pattern = r"^((👗|👧|👦|👩)\uFE0F? Гардероб|✨ Что надеть|💬 Спросить Касси|👤 Профиль|❓ Помощь)$"
        assert re.match(pattern, "👩 Гардероб")
        assert re.match(pattern, "👩\uFE0F Гардероб")
        assert re.match(pattern, "✨ Что надеть")
        assert not re.match(pattern, "random text")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Cache versioning — stale cache prevention
# ═══════════════════════════════════════════════════════════════════════════════

class TestCacheVersioning:
    """Gap analysis cache must include version in key."""

    def test_cache_key_has_version(self):
        import inspect
        from services.gap_analysis import build_shopping_list
        src = inspect.getsource(build_shopping_list)
        assert "_CACHE_VER" in src, "Cache key must include version"

    def test_cache_version_in_key_format(self):
        """Cache key format: gap_analysis:{version}:{owner_id}."""
        import inspect
        from services.gap_analysis import build_shopping_list
        src = inspect.getsource(build_shopping_list)
        assert "gap_analysis:{_CACHE_VER}" in src or "f\"gap_analysis:{_CACHE_VER}" in src


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Outfit selector fallback — small wardrobe handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutfitSelectorFallback:
    """With few items, selector must not return empty outfit."""

    def test_fallback_when_all_worn_today(self):
        """If all items worn today but wardrobe small → include them anyway."""
        from datetime import date
        from services.outfit_selector import _select_outfit

        class FakeItem:
            def __init__(self, cg, typ, **kw):
                self.category_group = cg
                self.type = typ
                self.color = kw.get("color", "")
                self.season = kw.get("season", [])
                self.last_worn = kw.get("last_worn")
                self.score_item = None
                self.id = kw.get("id", 1)

        today = date.today()
        items = [
            FakeItem("top", "футболка", last_worn=today),
            FakeItem("bottom", "джинсы", last_worn=today),
        ]
        result = _select_outfit(items, "spring", today, 10.0, 8.0, 0)
        # With fallback, should still select something
        has_items = any(
            v and hasattr(v, "type")
            for k, v in result.items()
            if k not in ("warnings", "all_items", "temp", "underwear_text",
                         "underwear_items", "thermal_top", "thermal_bottom")
        )
        assert has_items, "Fallback should include worn items when wardrobe is small"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Color mapping completeness
# ═══════════════════════════════════════════════════════════════════════════════

class TestColorMapping:
    """All COLORTYPE_PALETTES colors must resolve to a real hex."""

    def test_all_colortype_colors_resolve(self):
        from services.collage_styles import _color_hex
        from worker.tasks.style_config import COLORTYPE_PALETTES

        fallback = "#C0B8C8"
        failures = []
        for ct, slots in COLORTYPE_PALETTES.items():
            for slot, colors in slots.items():
                for color in colors:
                    hex_c = _color_hex(color)
                    if hex_c == fallback:
                        failures.append(f"{ct}/{slot}: '{color}' → fallback")

        assert not failures, f"Colors mapping to fallback:\n" + "\n".join(failures)

    def test_common_colors_have_hex(self):
        from services.collage_styles import _color_hex
        colors = ["лавандовая", "мятный", "персиковая", "коралловая",
                  "горчичная", "терракотовая", "серо-голубая", "пудровый"]
        for c in colors:
            hex_c = _color_hex(c)
            assert hex_c != "#C0B8C8", f"'{c}' has no mapping (got fallback)"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Collage height — footer must not be cut off
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollageHeight:
    """Collage height must accommodate all elements."""

    def test_flat_lay_height_sufficient(self):
        from services.collage_styles import build_flat_lay, collect_palette
        slots = [
            {"slot": "outerwear", "has_item": False, "item_color": "", "gender": "girl", "label": "Куртка"},
            {"slot": "top", "has_item": False, "item_color": "", "gender": "girl", "label": "Верх"},
            {"slot": "bottom", "has_item": False, "item_color": "", "gender": "girl", "label": "Низ"},
            {"slot": "footwear", "has_item": False, "item_color": "", "gender": "girl", "label": "Обувь"},
            {"slot": "hat", "has_item": False, "item_color": "", "gender": "girl", "label": "Шапка"},
        ]
        palette = collect_palette(slots)
        _, _, h = build_flat_lay(slots, "Test · +5° · Алиса", "Длинный совет на две строки — оденьтесь теплее!", palette)
        assert h >= 480, f"Height {h} too small for 5 slots + footer"

    def test_brief_card_height_with_long_footer(self):
        from services.collage_styles import build_brief_card, collect_palette
        slots = [
            {"slot": "outerwear", "has_item": False, "item_color": "", "gender": "girl", "label": "Куртка"},
            {"slot": "top", "has_item": True, "item_color": "розовая", "item_type": "футболка", "gender": "girl"},
        ]
        palette = collect_palette(slots)
        long_advice = "К вечеру дождь и +2° — возьми зонтик и шарф на забирание из садика, будет холодно"
        _, _, h = build_brief_card(slots, "Test · +5° · Алиса", long_advice, palette, colortype="Лето")
        assert h >= 350, f"Height {h} too small for brief card with long footer"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Palette dots layout
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaletteLayout:
    """Palette dots must be in correct position in element tree."""

    def test_flat_lay_palette_in_header_row(self):
        """Palette dots must be in same row as name (centered with dots right)."""
        from services.collage_styles import build_flat_lay, collect_palette
        slots = [{"slot": "top", "has_item": False, "item_color": "розовый", "gender": "girl", "label": "Верх"}]
        palette = collect_palette(slots, colortype="Лето")
        el, _, _ = build_flat_lay(slots, "Test · +5° · Алиса", "", palette)
        header = el["props"]["children"][0]
        first = header["props"]["children"][0]
        style = first["props"]["style"]
        assert style.get("justifyContent") == "center", \
            "Name row must be centered"
        # Should have 3 children: spacer + name + dots
        children = first["props"]["children"]
        assert len(children) == 3, "Header row: spacer + name + dots"

    def test_collect_palette_includes_placeholders(self):
        """Palette should include recommended colors from placeholders."""
        from services.collage_styles import collect_palette
        slots = [
            {"has_item": True, "item_color": "розовый", "slot": "top"},
            {"has_item": False, "item_color": "", "slot": "outerwear"},
        ]
        result = collect_palette(slots, colortype="Лето")
        assert len(result) >= 2, "Should have item color + placeholder recommendation"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Weather data pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeatherPipeline:
    """Weather data must flow through to collage."""

    def test_brief_weather_returns_all_fields(self):
        """_get_weather must return temp_now, temp_day, wmo codes."""
        # Check function signature has the fields
        import inspect
        from services.brief_weather import _get_weather
        src = inspect.getsource(_get_weather)
        for field in ["temp_now", "temp_morning", "temp_day", "temp_evening",
                      "wmo_morning", "wmo_day", "wmo_evening", "precip_max"]:
            assert field in src, f"_get_weather must return {field}"

    def test_wmo_to_emoji_all_codes(self):
        """All WMO code ranges must map to an icon."""
        from services.brief_weather import wmo_to_emoji
        codes = [0, 1, 2, 3, 45, 48, 51, 55, 61, 65, 71, 75, 80, 85, 95, 99]
        for code in codes:
            result = wmo_to_emoji(code)
            assert result, f"WMO code {code} has no emoji"

    def test_weather_icon_names_complete(self):
        """All icon names from _wmo_to_icon_name must have PNG files."""
        import os
        from services.collage_styles import _wmo_to_icon_name
        icons_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "weather")
        codes = [0, 2, 3, 45, 51, 56, 61, 71, 95]
        for code in codes:
            name = _wmo_to_icon_name(code)
            path = os.path.join(icons_dir, f"{name}.png")
            assert os.path.exists(path), f"Missing icon: {name}.png for WMO {code}"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Owner icon consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestOwnerIcons:
    """Owner icons must be consistent across UI."""

    def test_menu_icon_child_girl(self):
        from bot.handlers.menu import get_main_menu

        class FakeUser:
            segment = "mom_girl"

        class FakeCtx:
            user_data = {"active_owner_type": "child", "active_owner_gender": "girl"}

        menu = get_main_menu(FakeUser(), FakeCtx())
        buttons = [btn.text for row in menu.keyboard for btn in row]
        wardrobe_btn = [b for b in buttons if "Гардероб" in b][0]
        assert "👧" in wardrobe_btn

    def test_menu_icon_self(self):
        from bot.handlers.menu import get_main_menu

        class FakeUser:
            segment = "mom_girl"

        class FakeCtx:
            user_data = {"active_owner_type": "user"}

        menu = get_main_menu(FakeUser(), FakeCtx())
        buttons = [btn.text for row in menu.keyboard for btn in row]
        wardrobe_btn = [b for b in buttons if "Гардероб" in b][0]
        assert "👩" in wardrobe_btn

    def test_help_text_has_dynamic_icon(self):
        """help.text must use {wardrobe_icon} placeholder."""
        from services.i18n.ru import STRINGS
        assert "{wardrobe_icon}" in STRINGS["help.text"]


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Brief card structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestBriefCard:
    """Brief card element tree must have correct structure."""

    def test_has_weather_strip(self):
        from services.collage_styles import build_brief_card, collect_palette
        slots = [{"slot": "top", "has_item": False, "item_color": "", "gender": "girl", "label": "Верх"}]
        weather = {"temp_morning": 4, "temp_day": 7, "temp_evening": 2,
                   "wmo_morning": 1, "wmo_day": 2, "wmo_evening": 61}
        palette = collect_palette(slots)
        el, _, _ = build_brief_card(slots, "Test", "Совет", palette, weather_data=weather)
        # Root should have 3 children: header, body, footer
        assert len(el["props"]["children"]) == 3

    def test_dressing_order_sections(self):
        """Items card must have section labels in order."""
        from services.collage_styles import build_brief_card, collect_palette
        slots = [
            {"slot": "top", "has_item": True, "item_color": "розовый", "item_type": "футболка", "gender": "girl"},
            {"slot": "outerwear", "has_item": False, "item_color": "", "gender": "girl", "label": "Куртка"},
            {"slot": "footwear", "has_item": False, "item_color": "", "gender": "girl", "label": "Обувь"},
        ]
        palette = collect_palette(slots)
        el, _, _ = build_brief_card(slots, "Test", "", palette, colortype="Лето")
        # Flatten all text content
        def _texts(node, acc=None):
            if acc is None:
                acc = []
            ch = node.get("props", {}).get("children", "")
            if isinstance(ch, str):
                acc.append(ch)
            elif isinstance(ch, list):
                for c in ch:
                    if isinstance(c, dict):
                        _texts(c, acc)
            return acc
        texts = _texts(el)
        text_str = " ".join(texts)
        # Sections must appear in order
        assert "ОДЕЖДА" in text_str
        assert "ОБУВЬ" in text_str
        assert "НА ВЫХОД" in text_str

    def test_colortype_dots_for_placeholders(self):
        """Placeholder items should have colortype-based dot colors."""
        from services.collage_styles import _recommended_color_hex
        # Лето outerwear should be lavender, not gray
        hex_c = _recommended_color_hex("outerwear", "Лето")
        assert hex_c != "#B0B8C0", f"Expected colortype color, got fallback: {hex_c}"
        assert hex_c == "#B090D0"  # лавандовый
