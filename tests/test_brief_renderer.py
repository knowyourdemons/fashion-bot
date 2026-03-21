"""Tests for brief_renderer (Jinja2 templates) and brief_card (card builder)."""
import asyncio
import os
import pytest
from unittest.mock import patch, AsyncMock


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── brief_renderer unit tests ────────────────────────────────────────────────


class TestGetSegment:
    def test_mom_girl(self):
        from services.brief_renderer import get_segment

        class U:
            segment = "mom_girl"
        assert get_segment(U()) == "mom"

    def test_mom_boy(self):
        from services.brief_renderer import get_segment

        class U:
            segment = "mom_boy"
        assert get_segment(U()) == "mom"

    def test_no_kids(self):
        from services.brief_renderer import get_segment

        class U:
            segment = "no_kids"
        assert get_segment(U()) == "woman"

    def test_pregnant(self):
        from services.brief_renderer import get_segment

        class U:
            segment = "pregnant"
        assert get_segment(U()) == "woman"

    def test_none(self):
        from services.brief_renderer import get_segment

        class U:
            segment = None
        assert get_segment(U()) == "woman"


class TestGetTheme:
    def test_mom_theme(self):
        from services.brief_renderer import get_theme
        t = get_theme("mom")
        assert t["css_class"] == "mom"
        assert "#F5EDE8" in t["bg_start"]

    def test_woman_theme(self):
        from services.brief_renderer import get_theme
        t = get_theme("woman")
        assert t["css_class"] == "woman"
        assert "#E8EDF5" in t["bg_start"]


class TestColorMapping:
    def test_get_color_bg(self):
        from services.brief_renderer import get_color_bg
        assert get_color_bg("розовый") == "bg-pink"
        assert get_color_bg("синий") == "bg-blue"
        assert get_color_bg("") == "bg-grey"
        assert get_color_bg("неизвестный") == "bg-grey"

    def test_get_color_bg_compound(self):
        from services.brief_renderer import get_color_bg
        assert get_color_bg("тёмно-синий") == "bg-navy"
        assert get_color_bg("пыльно-розовый") == "bg-pink"

    def test_get_color_hex(self):
        from services.brief_renderer import get_color_hex
        assert get_color_hex("розовый") == "#E0A0B0"
        assert get_color_hex("") == "#C0C0C0"
        assert get_color_hex("неизвестный") == "#C0C0C0"


class TestFormatTemp:
    def test_positive(self):
        from services.brief_renderer import format_temp
        assert format_temp(4.2) == "+4°"

    def test_negative(self):
        from services.brief_renderer import format_temp
        assert format_temp(-3.7) == "-4°"

    def test_zero(self):
        from services.brief_renderer import format_temp
        assert format_temp(0.0) == "+0°"

    def test_none(self):
        from services.brief_renderer import format_temp
        assert format_temp(None) == ""


class TestPrepareWeatherData:
    def test_basic(self):
        from services.brief_renderer import prepare_weather_data
        w = {
            "temp_morning": 4.0,
            "temp_day": 7.0,
            "temp_evening": 2.0,
            "wmo_morning": 0,
            "wmo_day": 2,
            "wmo_evening": 61,
        }
        result = prepare_weather_data(w)
        assert result["temp_morning_str"] == "+4°"
        assert result["temp_day_str"] == "+7°"
        assert result["temp_evening_str"] == "+2°"
        assert result["icon_morning"] == "☀️"
        assert result["icon_evening"] == "🌧"
        # 2 < 4 - 3 = 1 → false
        assert result["evening_warn"] is False

    def test_evening_warn(self):
        from services.brief_renderer import prepare_weather_data
        w = {"temp_morning": 10.0, "temp_evening": 2.0}
        result = prepare_weather_data(w)
        assert result["evening_warn"] is True  # 2 < 10-3=7

    def test_empty(self):
        from services.brief_renderer import prepare_weather_data
        assert prepare_weather_data({}) == {}
        assert prepare_weather_data(None) == {}


class TestPrepareItemsHybrid:
    def test_basic_items(self):
        from services.brief_renderer import prepare_items_hybrid
        slots = [
            {"slot": "top", "has_item": True, "item_type": "Кофта", "item_color": "розовый", "_photo_bytes": b"fake"},
            {"slot": "bottom", "has_item": True, "item_type": "Джинсы", "item_color": "синий"},
            {"slot": "outerwear", "has_item": False, "slot": "outerwear"},
        ]
        with patch("services.image_builder._auto_trim", return_value=b"\x89PNG"):
            items, missing = prepare_items_hybrid(slots)
        assert len(items) == 2
        assert items[0]["bg_class"] == "bg-pink"
        assert items[0]["size_class"] == "w50"
        assert len(missing) == 1
        assert missing[0]["name_ru"] == "Куртка"

    def test_single_item_w100(self):
        from services.brief_renderer import prepare_items_hybrid
        slots = [
            {"slot": "top", "has_item": True, "item_type": "Кофта", "item_color": "белый"},
        ]
        items, missing = prepare_items_hybrid(slots)
        assert len(items) == 1
        assert items[0]["size_class"] == "w100"


class TestPrepareLayers:
    def test_basic_layers(self):
        from services.brief_renderer import prepare_layers
        weather = {"temp_morning": 5.0, "precip_max": 70}
        slots = [
            {"slot": "top", "has_item": True, "item_type": "Кофта"},
            {"slot": "bottom", "has_item": True, "item_type": "Штаны"},
            {"slot": "outerwear", "has_item": True, "item_type": "Куртка"},
        ]
        layers = prepare_layers(weather, slots)
        # base + top + bottom + outerwear + umbrella
        assert any(l["emoji"] == "🩲" for l in layers)
        assert any(l["emoji"] == "🧥" for l in layers)
        assert any(l["emoji"] == "🌂" for l in layers)

    def test_no_rain(self):
        from services.brief_renderer import prepare_layers
        weather = {"temp_morning": 20.0, "precip_max": 10}
        slots = [{"slot": "top", "has_item": True}]
        layers = prepare_layers(weather, slots)
        assert not any(l["emoji"] == "🌂" for l in layers)


class TestCollectPalette:
    def test_unique_colors(self):
        from services.brief_renderer import collect_palette
        items = [
            {"color_hex": "#E0A0B0"},
            {"color_hex": "#4060C0"},
            {"color_hex": "#E0A0B0"},  # duplicate
        ]
        palette = collect_palette(items)
        assert palette == ["#E0A0B0", "#4060C0"]

    def test_max_5(self):
        from services.brief_renderer import collect_palette
        items = [{"color_hex": f"#{i:06x}"} for i in range(10)]
        assert len(collect_palette(items)) == 5


class TestPrepareUnderwearLine:
    def test_with_underwear(self):
        from services.brief_renderer import prepare_underwear_line
        outfit = {"underwear_text": "колготки · майка"}
        result = prepare_underwear_line(outfit)
        assert "колготки" in result
        assert result.startswith("🩲")

    def test_empty(self):
        from services.brief_renderer import prepare_underwear_line
        assert prepare_underwear_line({}) == ""


class TestPrepareDateContext:
    def test_with_child(self):
        from services.brief_renderer import prepare_date_context

        class U:
            segment = "mom_girl"

        class C:
            name = "Алиса"

        date_str, ctx = prepare_date_context(U(), C())
        assert ctx in ("САДИК", "ПРОГУЛКА")
        assert date_str  # non-empty

    def test_no_child(self):
        from services.brief_renderer import prepare_date_context

        class U:
            segment = "no_kids"

        date_str, ctx = prepare_date_context(U(), None)
        assert ctx == ""


# ── Jinja2 template rendering tests ──────────────────────────────────────────


class TestRenderTemplate:
    def test_weather_template(self):
        from services.brief_renderer import render_template
        html = render_template(
            "tpl_weather.html",
            css_class="mom",
            name="Алиса",
            context="САДИК",
            date_str="ПТ, 21 МАРТА",
            weather={
                "temp_morning": 4, "temp_day": 7, "temp_evening": 2,
                "temp_morning_str": "+4°", "temp_day_str": "+7°",
                "temp_evening_str": "+2°",
                "icon_day": "☀️", "icon_evening": "🌧",
                "evening_warn": True,
            },
            layers=[
                {"emoji": "🩲", "name": "базовый", "css_class": "base"},
                {"emoji": "👚", "name": "кофта", "css_class": "base"},
                {"emoji": "🧥", "name": "куртка!", "css_class": "accent"},
            ],
            kassi_comment="К вечеру дождь — зонт на забирание!",
        )
        assert "Алиса" in html
        assert "САДИК" in html
        assert "+4°" in html
        assert "куртка!" in html
        assert "Касси" in html
        assert "class=\"mom\"" in html

    def test_hybrid_template(self):
        from services.brief_renderer import render_template
        html = render_template(
            "tpl_hybrid.html",
            css_class="mom",
            name="Алиса",
            context="САДИК",
            date_str="ПТ, 21 МАРТА",
            weather={
                "temp_morning_str": "+4°",
                "temp_evening_str": "+2°",
                "icon_morning": "☀️",
                "icon_evening": "🌧",
                "evening_warn": True,
            },
            items=[
                {"size_class": "w50", "bg_class": "bg-pink", "photo_base64": "",
                 "emoji": "👚", "label": "Кофта розовая"},
                {"size_class": "w50", "bg_class": "bg-blue", "photo_base64": "",
                 "emoji": "👖", "label": "Джинсы синие"},
            ],
            missing=[
                {"miss_css": "miss-outer", "emoji": "🧥", "name_ru": "Куртка"},
            ],
            palette=["#E0A0B0", "#4060C0"],
            base_layer="🩲 колготки · майка",
            kassi_comment="Розовая кофта + синие джинсы — классная пара!",
            progress_pct=25,
            progress_text="2/8 · 📸 Сфоткай куртку!",
        )
        assert "Кофта розовая" in html
        assert "bg-pink" in html
        assert "miss-outer" in html
        assert "Куртка" in html
        assert "25%" in html  # progress bar
        assert "Касси" in html

    def test_full_template(self):
        from services.brief_renderer import render_template
        html = render_template(
            "tpl_full.html",
            css_class="woman",
            name="Мария",
            context="",
            date_str="ПТ, 21 МАРТА",
            weather={"temp_morning_str": "+10°", "temp_evening_str": "+8°"},
            items=[
                {"fi_class": "outer", "bg_class": "bg-navy", "photo_base64": "",
                 "emoji": "🧥", "emoji_size": None, "label": "Куртка синяя", "extra_style": ""},
                {"fi_class": "top", "bg_class": "bg-pink", "photo_base64": "",
                 "emoji": "👚", "emoji_size": None, "label": "Кофта розовая", "extra_style": ""},
            ],
            palette=["#4070B0", "#E0A0B0"],
            base_layer="",
            kassi_comment="Отличный образ!",
        )
        assert "Мария" in html
        assert 'class="woman"' in html
        assert "fi-outer" in html
        assert "fi-top" in html

    def test_morning_template_changed(self):
        from services.brief_renderer import render_template
        html = render_template(
            "tpl_morning.html",
            css_class="mom",
            name="Алиса",
            context="САДИК",
            date_str="ПТ, 21 МАР",
            weather_now={"icon": "🌤️", "temp_str": "+8°", "is_good": False},
            changed=True,
            change_text="Потеплело до +8°. Куртку замени на ветровку.",
            items=[
                {"fi_class": "outer", "bg_class": "bg-green", "photo_base64": "", "emoji": "🧥"},
                {"fi_class": "top", "bg_class": "bg-pink", "photo_base64": "", "emoji": "👚"},
            ],
            kassi_comment="Остальное как вчера. Хорошего дня!",
        )
        assert "alert-warn" in html
        assert "Потеплело" in html
        # alert-ok class is in CSS but should not be in body when changed=True
        body_start = html.find("<body")
        assert 'class="alert alert-ok"' not in html[body_start:]

    def test_morning_template_unchanged(self):
        from services.brief_renderer import render_template
        html = render_template(
            "tpl_morning.html",
            css_class="mom",
            name="Алиса",
            context="САДИК",
            date_str="ПТ, 21 МАР",
            weather_now={"icon": "☀️", "temp_str": "+5°", "is_good": True},
            changed=False,
            change_text="",
            items=[],
            kassi_comment="Хорошего дня!",
        )
        assert "alert-ok" in html
        assert "Всё как вчера" in html

    def test_woman_theme_applied(self):
        from services.brief_renderer import render_template
        html = render_template(
            "tpl_weather.html",
            css_class="woman",
            name="Мария",
            context="",
            date_str="ПТ, 21 МАРТА",
            weather={
                "temp_morning_str": "+10°",
                "temp_day_str": "+14°",
                "temp_evening_str": "+8°",
                "temp_morning": 10,
                "temp_day": 14,
                "temp_evening": 8,
                "icon_day": "☀️",
                "evening_warn": False,
            },
            layers=[],
            kassi_comment="Лёгкий день!",
        )
        assert 'class="woman"' in html
        assert "Мария" in html


# ── brief_card integration tests ─────────────────────────────────────────────


class TestBuildBriefCard:
    """Test build_brief_card with mocked renderer."""

    def _make_user(self, segment="mom_girl", name="Стас"):
        class U:
            pass
        u = U()
        u.segment = segment
        u.name = name
        u.city = "Vilnius"
        return u

    def _make_child(self, name="Алиса"):
        class C:
            pass
        c = C()
        c.name = name
        c.colortype = "Лето"
        return c

    def test_weather_card_0_photos(self):
        from services.brief_card import build_brief_card
        user = self._make_user()
        child = self._make_child()
        weather = {"temp_morning": 4.0, "temp_day": 7.0, "temp_evening": 2.0}

        with patch("services.brief_card.render_html_to_png", new_callable=AsyncMock) as mock_render:
            mock_render.return_value = b"\x89PNG_FAKE"
            result = _run(build_brief_card(user, child, {}, weather, [], advice_text="Тепло!"))

        assert result == b"\x89PNG_FAKE"
        mock_render.assert_called_once()
        html = mock_render.call_args[0][0]
        assert "Алиса" in html
        assert "Тепло!" in html

    def test_hybrid_card_2_photos(self):
        from services.brief_card import build_brief_card
        user = self._make_user()
        child = self._make_child()
        weather = {"temp_morning": 4.0}
        slots = [
            {"slot": "top", "has_item": True, "item_type": "Кофта", "item_color": "розовый",
             "photo_id": "abc", "_photo_bytes": b"img1"},
            {"slot": "bottom", "has_item": True, "item_type": "Джинсы", "item_color": "синий",
             "photo_id": "def", "_photo_bytes": b"img2"},
            {"slot": "outerwear", "has_item": False},
        ]

        with patch("services.brief_card.render_html_to_png", new_callable=AsyncMock) as mock_render, \
             patch("services.image_builder._auto_trim", return_value=b"\x89PNG"):
            mock_render.return_value = b"\x89PNG_HYBRID"
            result = _run(build_brief_card(user, child, {}, weather, slots))

        assert result == b"\x89PNG_HYBRID"
        html = mock_render.call_args[0][0]
        assert "bg-pink" in html
        assert "Куртка" in html  # missing item

    def test_full_card_8_photos(self):
        from services.brief_card import build_brief_card
        user = self._make_user()
        child = self._make_child()
        weather = {"temp_morning": 4.0}
        slots = [
            {"slot": f"top", "has_item": True, "item_type": f"Item{i}", "item_color": "серый",
             "photo_id": f"id{i}", "_photo_bytes": b"img"}
            for i in range(8)
        ]

        with patch("services.brief_card.render_html_to_png", new_callable=AsyncMock) as mock_render, \
             patch("services.image_builder._auto_trim", return_value=b"\x89PNG"):
            mock_render.return_value = b"\x89PNG_FULL"
            result = _run(build_brief_card(user, child, {}, weather, slots))

        assert result == b"\x89PNG_FULL"
        html = mock_render.call_args[0][0]
        assert "fi-top" in html  # flat lay positioning

    def test_woman_segment(self):
        from services.brief_card import build_brief_card
        user = self._make_user(segment="no_kids", name="Мария")
        weather = {"temp_morning": 15.0}

        with patch("services.brief_card.render_html_to_png", new_callable=AsyncMock) as mock_render:
            mock_render.return_value = b"\x89PNG"
            result = _run(build_brief_card(user, None, {}, weather, []))

        html = mock_render.call_args[0][0]
        assert 'class="woman"' in html
        assert "Мария" in html

    def test_render_failure_returns_none(self):
        from services.brief_card import build_brief_card
        user = self._make_user()

        with patch("services.brief_card.render_html_to_png", new_callable=AsyncMock) as mock_render:
            mock_render.return_value = None
            result = _run(build_brief_card(user, None, {}, {}, []))

        assert result is None


# ── Button tests ─────────────────────────────────────────────────────────────


class TestGetBriefButtons:
    def test_0_photos(self):
        from services.brief_card import get_brief_buttons
        btn = get_brief_buttons("mom", 0, "abc123")
        kb = btn["inline_keyboard"]
        assert len(kb) == 1
        assert "Сфоткать" in kb[0][0]["text"]

    def test_hybrid_mom(self):
        from services.brief_card import get_brief_buttons
        btn = get_brief_buttons("mom", 3, "abc", first_missing_slot="Куртка")
        kb = btn["inline_keyboard"]
        assert any("Надели" in b["text"] for b in kb[0])
        assert any("Куртка" in b["text"] for b in kb[0])

    def test_full_mom(self):
        from services.brief_card import get_brief_buttons
        btn = get_brief_buttons("mom", 10, "abc")
        kb = btn["inline_keyboard"]
        assert any("Переслать" in b["text"] for row in kb for b in row)

    def test_full_woman(self):
        from services.brief_card import get_brief_buttons
        btn = get_brief_buttons("woman", 10, "abc")
        kb = btn["inline_keyboard"]
        assert any("Stories" in b["text"] for row in kb for b in row)
        assert any("Нравится" in b["text"] for row in kb for b in row)

    def test_hybrid_woman(self):
        from services.brief_card import get_brief_buttons
        btn = get_brief_buttons("woman", 3, "abc")
        kb = btn["inline_keyboard"]
        assert any("Другой вариант" in b["text"] for b in kb[0])


# ── Playwright integration tests ─────────────────────────────────────────────


class TestRendererIntegration:
    """Live Playwright renderer integration (needs running renderer)."""

    def _renderer_available(self) -> bool:
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                "http://renderer:3100/render",
                data=json.dumps({"html": "<b>ok</b>", "width": 100}).encode(),
                headers={"Content-Type": "application/json"},
            )
            r = urllib.request.urlopen(req, timeout=5)
            return r.status == 200 and r.read(4) == b"\x89PNG"
        except Exception:
            return False

    def test_weather_card_renders_png(self):
        if not self._renderer_available():
            pytest.skip("Renderer not available")

        from services.brief_renderer import render_template, render_html_to_png
        html = render_template(
            "tpl_weather.html",
            css_class="mom",
            name="Тест",
            context="САДИК",
            date_str="ПТ, 21 МАРТА",
            weather={
                "temp_morning": 4, "temp_day": 7, "temp_evening": 2,
                "temp_morning_str": "+4°", "temp_day_str": "+7°",
                "temp_evening_str": "+2°",
                "icon_day": "☀️", "evening_warn": False,
            },
            layers=[
                {"emoji": "🩲", "name": "базовый", "css_class": "base"},
                {"emoji": "👚", "name": "кофта", "css_class": "base"},
            ],
            kassi_comment="Тест рендеринга!",
        )
        result = _run(render_html_to_png(html))
        assert result is not None
        assert result[:4] == b"\x89PNG"
        assert len(result) > 1000

    def test_hybrid_card_renders_png(self):
        if not self._renderer_available():
            pytest.skip("Renderer not available")

        from services.brief_renderer import render_template, render_html_to_png
        html = render_template(
            "tpl_hybrid.html",
            css_class="woman",
            name="Мария",
            context="",
            date_str="СР, 19 МАРТА",
            weather={"temp_morning_str": "+10°", "icon_morning": "☀️"},
            items=[
                {"size_class": "w50", "bg_class": "bg-pink", "photo_base64": "",
                 "emoji": "👚", "label": "Кофта"},
                {"size_class": "w50", "bg_class": "bg-blue", "photo_base64": "",
                 "emoji": "👖", "label": "Джинсы"},
            ],
            missing=[],
            palette=["#E0A0B0"],
            base_layer="",
            kassi_comment="Красиво!",
            progress_pct=50,
            progress_text="4/8",
        )
        result = _run(render_html_to_png(html))
        assert result is not None
        assert result[:4] == b"\x89PNG"

    def test_full_card_renders_png(self):
        if not self._renderer_available():
            pytest.skip("Renderer not available")

        from services.brief_renderer import render_template, render_html_to_png
        html = render_template(
            "tpl_full.html",
            css_class="mom",
            name="Алиса",
            context="САДИК",
            date_str="ПТ, 21 МАР",
            weather={"temp_morning_str": "+4°"},
            items=[
                {"fi_class": "outer", "bg_class": "bg-navy", "photo_base64": "",
                 "emoji": "🧥", "emoji_size": None, "label": "Куртка", "extra_style": ""},
                {"fi_class": "top", "bg_class": "bg-pink", "photo_base64": "",
                 "emoji": "👚", "emoji_size": None, "label": "Кофта", "extra_style": ""},
                {"fi_class": "bottom", "bg_class": "bg-blue", "photo_base64": "",
                 "emoji": "👖", "emoji_size": None, "label": "Джинсы", "extra_style": ""},
            ],
            palette=["#4070B0", "#E0A0B0"],
            base_layer="🩲 колготки",
            kassi_comment="Супер!",
        )
        result = _run(render_html_to_png(html))
        assert result is not None
        assert result[:4] == b"\x89PNG"

    def test_morning_card_renders_png(self):
        if not self._renderer_available():
            pytest.skip("Renderer not available")

        from services.brief_renderer import render_template, render_html_to_png
        html = render_template(
            "tpl_morning.html",
            css_class="mom",
            name="Алиса",
            context="САДИК",
            date_str="ПТ, 21 МАР",
            weather_now={"icon": "🌤️", "temp_str": "+8°", "is_good": True},
            changed=False,
            change_text="",
            items=[],
            kassi_comment="Хорошего дня!",
        )
        result = _run(render_html_to_png(html))
        assert result is not None
        assert result[:4] == b"\x89PNG"
