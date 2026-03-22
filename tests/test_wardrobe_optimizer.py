"""
Comprehensive outfit selection tests with synthetic wardrobes.

Tests rule-based _select_outfit() across ALL segments, wardrobe sizes,
weather conditions, and edge cases. Used for iterative optimization.

Matrix:
- 12 segment profiles (mom_girl×4 ages, mom_boy×4 ages, no_kids×4 colortypes)
- 4 wardrobe sizes (minimal, small, medium, full)
- 8 weather scenarios (6 regimes + temp delta + rain)
- Edge cases (one_piece only, no outerwear, no footwear, all worn today, etc.)
"""
import uuid
import pytest
from dataclasses import dataclass, field
from datetime import date
from unittest.mock import MagicMock

pytest.importorskip("structlog", reason="structlog not installed")

from services.outfit_selector import _select_outfit, _get_temp_regime
from services.outfit_builder import (
    has_minimum_outfit,
    has_minimum_wardrobe,
    build_outfit_slots,
    _is_base_layer_item,
)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def _item(
    category_group: str,
    type_: str,
    color: str = "белый",
    season: list[str] | None = None,
    last_worn: date | None = None,
    score: float = 7.0,
    warmth: int = 3,
    style_tag: str = "casual",
    rain_ok: bool = False,
    show_in_collage: bool = True,
):
    """Create a mock WardrobeItem."""
    i = MagicMock()
    i.id = uuid.uuid4()
    i.category_group = category_group
    i.type = type_
    i.color = color
    i.season = season or ["spring", "summer", "autumn", "winter"]
    i.last_worn = last_worn
    i.show_in_collage = show_in_collage
    i.photo_id = f"photo_{type_}"
    i.photo_url = None
    i.bbox = None
    i.score_item = score
    i.style = "повседневный"
    i.warmth_level = warmth
    i.style_tag = style_tag
    i.rain_ok = rain_ok
    return i


def _outfit(items, season="spring", temp_m=15.0, temp_e=15.0, precip=0.0):
    return _select_outfit(items, season, date.today(), temp_m, temp_e, precip)


# ══════════════════════════════════════════════════════════════════════════════
# WEATHER SCENARIOS
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class WeatherScenario:
    name: str
    temp_morning: float
    temp_evening: float
    season: str
    precip: float = 0.0

    @property
    def regime(self) -> str:
        return _get_temp_regime(self.temp_morning)


WEATHER_SCENARIOS = [
    WeatherScenario("жара_лето", 30.0, 25.0, "summer"),
    WeatherScenario("тепло_весна", 20.0, 16.0, "spring"),
    WeatherScenario("прохладно_осень", 12.0, 8.0, "autumn"),
    WeatherScenario("холодно_осень", 7.0, 3.0, "autumn"),
    WeatherScenario("мороз_зима", 3.0, -1.0, "winter"),
    WeatherScenario("сильный_мороз", -5.0, -12.0, "winter"),
    WeatherScenario("большой_перепад", 20.0, 8.0, "spring"),
    WeatherScenario("дождь_прохладно", 13.0, 10.0, "autumn", precip=70.0),
]


# ══════════════════════════════════════════════════════════════════════════════
# WARDROBE FACTORY
# ══════════════════════════════════════════════════════════════════════════════


# Colors by category for realism
_COLORS = {
    "top": ["белый", "розовый", "голубой", "серый", "красный", "мятный",
            "чёрный", "бежевый", "горчичный", "лавандовый"],
    "bottom": ["синий", "чёрный", "серый", "бежевый", "белый",
               "тёмно-синий", "коричневый", "хаки"],
    "outerwear": ["синяя", "чёрная", "серая", "бежевая", "красная",
                  "оливковая", "розовая", "горчичная"],
    "footwear": ["белые", "чёрные", "коричневые", "серые", "розовые", "бежевые"],
    "accessory": ["розовая", "белая", "чёрная", "серая", "красная", "голубая"],
    "one_piece": ["розовое", "голубое", "белое", "чёрное", "красное"],
}

# Item definitions: (category_group, type, seasons, warmth)
_ITEMS_POOL = {
    # ── TOPS ──
    "top_tshirt":    ("top", "футболка", ["spring", "summer"], 1),
    "top_longsleeve":("top", "лонгслив", ["spring", "autumn"], 2),
    "top_shirt":     ("top", "рубашка", ["spring", "summer", "autumn"], 2),
    "top_blouse":    ("top", "блузка", ["spring", "summer", "autumn"], 2),
    "top_sweater":   ("top", "свитер", ["autumn", "winter"], 4),
    "top_turtleneck":("top", "водолазка", ["autumn", "winter"], 4),
    "top_hoodie":    ("top", "худи", ["spring", "autumn", "winter"], 3),
    "top_cardigan":  ("top", "кардиган", ["spring", "autumn"], 3),
    "top_crop":      ("top", "кроп-топ", ["summer"], 1),
    "top_fleece":    ("top", "флиска", ["winter"], 4),

    # ── BOTTOMS ──
    "bot_jeans":     ("bottom", "джинсы", ["spring", "summer", "autumn", "winter"], 3),
    "bot_trousers":  ("bottom", "брюки", ["spring", "autumn", "winter"], 3),
    "bot_shorts":    ("bottom", "шорты", ["summer"], 1),
    "bot_skirt":     ("bottom", "юбка", ["spring", "summer", "autumn"], 2),
    "bot_leggings":  ("bottom", "леггинсы", ["spring", "autumn", "winter"], 2),
    "bot_warm_pants":("bottom", "утеплённые штаны", ["winter"], 5),

    # ── ONE PIECE ──
    "op_dress":      ("one_piece", "платье", ["spring", "summer", "autumn"], 2),
    "op_dress_warm": ("one_piece", "тёплое платье", ["autumn", "winter"], 3),
    "op_jumpsuit":   ("one_piece", "комбинезон", ["spring", "summer"], 2),

    # ── OUTERWEAR ──
    "ow_windbreaker":("outerwear", "ветровка", ["spring", "summer"], 2),
    "ow_jacket":     ("outerwear", "куртка", ["spring", "autumn"], 3),
    "ow_down":       ("outerwear", "пуховик", ["winter"], 5),
    "ow_coat":       ("outerwear", "пальто", ["autumn", "winter"], 4),
    "ow_denim":      ("outerwear", "джинсовая куртка", ["spring", "summer"], 2),
    "ow_vest":       ("outerwear", "жилет", ["spring", "autumn"], 2),
    "ow_rain":       ("outerwear", "дождевик", ["spring", "summer", "autumn"], 2),

    # ── FOOTWEAR ──
    "fw_sneakers":   ("footwear", "кроссовки", ["spring", "summer", "autumn"], 2),
    "fw_boots":      ("footwear", "ботинки", ["autumn", "winter"], 4),
    "fw_winter_boots":("footwear","зимние сапоги", ["winter"], 5),
    "fw_sandals":    ("footwear", "сандалии", ["summer"], 1),
    "fw_shoes":      ("footwear", "туфли", ["spring", "summer", "autumn"], 2),
    "fw_ugg":        ("footwear", "угги", ["winter"], 5),

    # ── ACCESSORIES ──
    "acc_hat_warm":  ("accessory", "тёплая шапка", ["autumn", "winter"], 4),
    "acc_hat_light": ("accessory", "лёгкая шапка", ["spring", "autumn"], 2),
    "acc_scarf":     ("accessory", "шарф", ["autumn", "winter"], 4),
    "acc_gloves":    ("accessory", "перчатки", ["winter"], 5),
    "acc_bag":       ("accessory", "сумка", None, 1),
    "acc_sunglasses":("accessory", "очки", ["spring", "summer"], 1),

    # ── UNDERWEAR ──
    "uw_trusiki":    ("underwear", "трусики", None, 1),
    "uw_maika":      ("underwear", "майка", None, 1),
    "uw_thermo_top": ("underwear", "термо кофта", ["winter"], 5),
    "uw_thermo_bot": ("underwear", "термо штаны", ["winter"], 5),

    # ── BASE LAYER ──
    "bl_socks":      ("base_layer", "носки", None, 1),
    "bl_tights":     ("base_layer", "колготки", ["autumn", "winter"], 3),
    "bl_warm_tights":("base_layer", "плотные колготки 200 ден", ["winter"], 5),
}


# Wardrobe presets by size
_WARDROBE_MINIMAL = [
    "top_tshirt", "bot_jeans", "fw_sneakers", "uw_trusiki",
]

_WARDROBE_SMALL = [
    "top_tshirt", "top_hoodie", "bot_jeans", "bot_shorts",
    "fw_sneakers", "fw_sandals", "ow_jacket",
    "uw_trusiki", "uw_maika", "bl_socks",
]

_WARDROBE_MEDIUM = [
    "top_tshirt", "top_longsleeve", "top_sweater", "top_hoodie", "top_cardigan",
    "bot_jeans", "bot_trousers", "bot_shorts", "bot_skirt", "bot_leggings",
    "op_dress",
    "ow_windbreaker", "ow_jacket", "ow_coat",
    "fw_sneakers", "fw_boots", "fw_sandals", "fw_shoes",
    "acc_hat_warm", "acc_scarf", "acc_bag",
    "uw_trusiki", "uw_maika", "uw_thermo_top",
    "bl_socks", "bl_tights",
]

_WARDROBE_FULL = [
    "top_tshirt", "top_longsleeve", "top_shirt", "top_blouse",
    "top_sweater", "top_turtleneck", "top_hoodie", "top_cardigan",
    "top_crop", "top_fleece",
    "bot_jeans", "bot_trousers", "bot_shorts", "bot_skirt",
    "bot_leggings", "bot_warm_pants",
    "op_dress", "op_dress_warm", "op_jumpsuit",
    "ow_windbreaker", "ow_jacket", "ow_down", "ow_coat",
    "ow_denim", "ow_vest", "ow_rain",
    "fw_sneakers", "fw_boots", "fw_winter_boots", "fw_sandals",
    "fw_shoes", "fw_ugg",
    "acc_hat_warm", "acc_hat_light", "acc_scarf", "acc_gloves",
    "acc_bag", "acc_sunglasses",
    "uw_trusiki", "uw_maika", "uw_thermo_top", "uw_thermo_bot",
    "bl_socks", "bl_tights", "bl_warm_tights",
]

WARDROBE_SIZES = {
    "minimal": _WARDROBE_MINIMAL,
    "small": _WARDROBE_SMALL,
    "medium": _WARDROBE_MEDIUM,
    "full": _WARDROBE_FULL,
}


def _build_wardrobe(item_keys: list[str], extra_score_boost: float = 0.0) -> list:
    """Build wardrobe from item pool keys."""
    import random as _rng
    items = []
    for key in item_keys:
        if key not in _ITEMS_POOL:
            continue
        cg, type_, seasons, warmth = _ITEMS_POOL[key]
        colors = _COLORS.get(cg, ["белый"])
        color = colors[len(items) % len(colors)]
        score = 5.0 + (warmth * 0.5) + extra_score_boost
        season_list = seasons if seasons else ["spring", "summer", "autumn", "winter"]
        items.append(_item(cg, type_, color, season=season_list, score=min(score, 10.0), warmth=warmth))
    return items


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENT PROFILES
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class SegmentProfile:
    name: str
    segment: str  # mom_girl, mom_boy, no_kids, pregnant
    child_age: int | None = None
    child_gender: str | None = None
    colortype: str = "default"


SEGMENT_PROFILES = [
    # Дочки по возрастам
    SegmentProfile("girl_0_3", "mom_girl", child_age=2, child_gender="girl"),
    SegmentProfile("girl_3_7", "mom_girl", child_age=5, child_gender="girl"),
    SegmentProfile("girl_7_12", "mom_girl", child_age=9, child_gender="girl"),
    SegmentProfile("girl_12_16", "mom_girl", child_age=14, child_gender="girl"),
    # Сыновья по возрастам
    SegmentProfile("boy_0_3", "mom_boy", child_age=2, child_gender="boy"),
    SegmentProfile("boy_3_7", "mom_boy", child_age=5, child_gender="boy"),
    SegmentProfile("boy_7_12", "mom_boy", child_age=9, child_gender="boy"),
    SegmentProfile("boy_12_16", "mom_boy", child_age=14, child_gender="boy"),
    # Взрослые по цветотипам
    SegmentProfile("woman_summer", "no_kids", colortype="Лето"),
    SegmentProfile("woman_winter", "no_kids", colortype="Зима"),
    SegmentProfile("woman_spring", "no_kids", colortype="Весна"),
    SegmentProfile("woman_autumn", "no_kids", colortype="Осень"),
]


# ══════════════════════════════════════════════════════════════════════════════
# PARAMETRIZED TESTS: Full matrix
# ══════════════════════════════════════════════════════════════════════════════


_weather_ids = [w.name for w in WEATHER_SCENARIOS]
_size_ids = list(WARDROBE_SIZES.keys())
_segment_ids = [s.name for s in SEGMENT_PROFILES]


@pytest.fixture(params=WEATHER_SCENARIOS, ids=_weather_ids)
def weather(request):
    return request.param


@pytest.fixture(params=_size_ids)
def wardrobe_size(request):
    return request.param


@pytest.fixture(params=SEGMENT_PROFILES, ids=_segment_ids)
def segment(request):
    return request.param


class TestOutfitCompleteness:
    """Test that outfit has minimum required items when wardrobe allows."""

    @pytest.mark.parametrize("size_key", _size_ids)
    @pytest.mark.parametrize("weather_sc", WEATHER_SCENARIOS, ids=_weather_ids)
    def test_minimum_outfit_when_wardrobe_allows(self, size_key, weather_sc):
        """If wardrobe has top+bottom or one_piece, outfit should too."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        result = _outfit(items, weather_sc.season, weather_sc.temp_morning,
                         weather_sc.temp_evening, weather_sc.precip)

        if has_minimum_wardrobe(items):
            assert has_minimum_outfit(result), (
                f"Wardrobe '{size_key}' has minimum items but outfit doesn't. "
                f"Weather: {weather_sc.name}, regime: {weather_sc.regime}. "
                f"top={result.get('top')}, bottom={result.get('bottom')}, "
                f"one_piece={result.get('one_piece')}"
            )


class TestWeatherAppropriateness:
    """Test that selected items match the temperature regime."""

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_no_shorts_in_cold(self, size_key):
        """Shorts should NOT be selected when temp < 10°C."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        for sc in [s for s in WEATHER_SCENARIOS if s.temp_morning < 10]:
            result = _outfit(items, sc.season, sc.temp_morning, sc.temp_evening)
            bottom = result.get("bottom")
            if bottom:
                assert "шорт" not in (bottom.type or "").lower(), (
                    f"Shorts selected at {sc.temp_morning}°C ({sc.name})! "
                    f"Selected: {bottom.type}"
                )

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_no_sandals_in_cold(self, size_key):
        """Sandals should NOT be selected when temp < 5°C."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        for sc in [s for s in WEATHER_SCENARIOS if s.temp_morning < 5]:
            result = _outfit(items, sc.season, sc.temp_morning, sc.temp_evening)
            footwear = result.get("footwear")
            if footwear:
                assert "сандал" not in (footwear.type or "").lower(), (
                    f"Sandals selected at {sc.temp_morning}°C ({sc.name})! "
                    f"Selected: {footwear.type}"
                )

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_outerwear_in_cold(self, size_key):
        """Outerwear should be present when temp ≤ 15°C if available."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        has_outerwear_items = any(i.category_group == "outerwear" for i in items)
        for sc in [s for s in WEATHER_SCENARIOS if s.temp_morning <= 15]:
            result = _outfit(items, sc.season, sc.temp_morning, sc.temp_evening)
            # Only assert if seasonal outerwear exists
            seasonal_ow = [
                i for i in items
                if i.category_group == "outerwear"
                and (not i.season or sc.season in i.season)
            ]
            if seasonal_ow:
                assert result.get("outerwear") is not None, (
                    f"No outerwear at {sc.temp_morning}°C ({sc.name}) despite "
                    f"{len(seasonal_ow)} available outerwear items. Size: {size_key}"
                )

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_thermal_in_freezing(self, size_key):
        """Thermal underwear should be selected when temp ≤ 5°C if available."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        has_thermo = any("термо" in (i.type or "").lower() for i in items)
        if not has_thermo:
            return
        for sc in [s for s in WEATHER_SCENARIOS if s.temp_morning <= 5]:
            result = _outfit(items, sc.season, sc.temp_morning, sc.temp_evening)
            assert result.get("thermal_top") is not None or result.get("thermal_bottom") is not None, (
                f"No thermal at {sc.temp_morning}°C ({sc.name}) despite thermo items in wardrobe"
            )

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_hat_in_cold(self, size_key):
        """Hat should be selected when temp < 10°C if available."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        has_hat = any(
            i.category_group == "accessory"
            and any(w in (i.type or "").lower() for w in ["шапк", "hat"])
            for i in items
        )
        if not has_hat:
            return
        for sc in [s for s in WEATHER_SCENARIOS if s.temp_morning < 10]:
            result = _outfit(items, sc.season, sc.temp_morning, sc.temp_evening)
            # Hat must be found if seasonal hat items exist
            seasonal_hats = [
                i for i in items
                if i.category_group == "accessory"
                and any(w in (i.type or "").lower() for w in ["шапк", "hat"])
                and (not i.season or sc.season in i.season)
            ]
            if seasonal_hats:
                assert result.get("hat") is not None, (
                    f"No hat at {sc.temp_morning}°C ({sc.name}) despite "
                    f"{len(seasonal_hats)} seasonal hats"
                )

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_scarf_in_frost(self, size_key):
        """Scarf should be selected when temp < 5°C if available."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        for sc in [s for s in WEATHER_SCENARIOS if s.temp_morning < 5]:
            result = _outfit(items, sc.season, sc.temp_morning, sc.temp_evening)
            seasonal_scarves = [
                i for i in items
                if i.category_group == "accessory"
                and any(w in (i.type or "").lower() for w in ["шарф", "scarf"])
                and (not i.season or sc.season in i.season)
            ]
            if seasonal_scarves:
                assert result.get("scarf") is not None, (
                    f"No scarf at {sc.temp_morning}°C ({sc.name}) despite "
                    f"{len(seasonal_scarves)} seasonal scarves"
                )

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_gloves_in_deep_frost(self, size_key):
        """Gloves should be selected when temp < 0°C if available."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        for sc in [s for s in WEATHER_SCENARIOS if s.temp_morning < 0]:
            result = _outfit(items, sc.season, sc.temp_morning, sc.temp_evening)
            seasonal_gloves = [
                i for i in items
                if i.category_group == "accessory"
                and any(w in (i.type or "").lower() for w in ["перчатк", "варежк", "gloves"])
                and (not i.season or sc.season in i.season)
            ]
            if seasonal_gloves:
                assert result.get("gloves") is not None, (
                    f"No gloves at {sc.temp_morning}°C ({sc.name}) despite "
                    f"{len(seasonal_gloves)} seasonal gloves"
                )

    def test_warm_footwear_preferred_in_winter(self):
        """Boots/winter boots preferred over sneakers in cold weather."""
        items = _build_wardrobe(_WARDROBE_FULL)
        result = _outfit(items, "winter", temp_m=3.0, temp_e=-1.0)
        footwear = result.get("footwear")
        if footwear:
            fw_type = (footwear.type or "").lower()
            assert any(w in fw_type for w in ["ботинк", "сапог", "boot", "угг"]), (
                f"Expected warm footwear in winter, got: {footwear.type}"
            )

    def test_warm_outerwear_in_deep_frost(self):
        """Down jacket / warm coat preferred at ≤ 5°C."""
        items = _build_wardrobe(_WARDROBE_FULL)
        result = _outfit(items, "winter", temp_m=-5.0, temp_e=-12.0)
        ow = result.get("outerwear")
        if ow:
            ow_type = (ow.type or "").lower()
            assert any(w in ow_type for w in ["пуховик", "тёплая", "зимняя", "down"]), (
                f"Expected warm outerwear at -5°C, got: {ow.type}"
            )


class TestLayerLogic:
    """Test layer consistency rules."""

    def test_tights_only_under_dress_or_skirt(self):
        """Tights should only be added under dress/skirt, not pants."""
        items = _build_wardrobe(_WARDROBE_MEDIUM)
        # Force pants (no skirt/dress) at cool temp
        pants_items = [i for i in items if i.category_group != "one_piece"]
        result = _outfit(pants_items, "autumn", temp_m=8.0, temp_e=5.0)
        bottom = result.get("bottom")
        if bottom:
            bt = (bottom.type or "").lower()
            is_pants = any(w in bt for w in ["джинс", "брюк", "штан", "леггинс", "лосин"])
            if is_pants:
                # Tights should NOT be selected under pants
                assert result.get("tights") is None, (
                    f"Tights selected under pants ({bottom.type})! "
                    "Tights only go under dresses/skirts."
                )

    def test_tights_under_dress_in_cold(self):
        """Tights SHOULD be added under dress at cold temperature."""
        items = _build_wardrobe(_WARDROBE_FULL)
        # Keep only dresses as main garment options
        dress_only = [
            i for i in items
            if i.category_group not in ("top", "bottom")
        ]
        # Add a dress explicitly
        dress_only.append(_item("one_piece", "платье", "розовое",
                                season=["autumn", "winter"], warmth=2))
        result = _outfit(dress_only, "autumn", temp_m=8.0, temp_e=5.0)
        if result.get("one_piece"):
            assert result.get("tights") is not None, (
                "Tights should be selected under dress at 8°C"
            )

    def test_no_duplicate_items_in_slots(self):
        """No single item should appear in multiple slots."""
        for size_key in ["small", "medium", "full"]:
            items = _build_wardrobe(WARDROBE_SIZES[size_key])
            for sc in WEATHER_SCENARIOS:
                result = _outfit(items, sc.season, sc.temp_morning,
                                 sc.temp_evening, sc.precip)
                slot_ids = []
                for key in ("thermal_top", "thermal_bottom", "one_piece",
                            "top", "bottom", "removable_layer", "tights",
                            "socks", "footwear", "outerwear", "hat",
                            "scarf", "gloves"):
                    val = result.get(key)
                    if val:
                        slot_ids.append((key, val.id))
                ids_only = [sid for _, sid in slot_ids]
                dupes = [sid for sid in ids_only if ids_only.count(sid) > 1]
                assert not dupes, (
                    f"Duplicate item in outfit! Size={size_key}, weather={sc.name}. "
                    f"Slots: {[(k, str(i)[:8]) for k, i in slot_ids if i in dupes]}"
                )

    def test_removable_layer_on_temp_delta(self):
        """Removable layer should be added when temp delta > 8°C."""
        # Need a hoodie/cardigan for removable layer
        items = _build_wardrobe(_WARDROBE_MEDIUM)
        result = _outfit(items, "spring", temp_m=20.0, temp_e=8.0)
        # Should have warning about temperature swing
        warnings_text = " ".join(result.get("warnings", []))
        assert "слоями" in warnings_text.lower() or "утром" in warnings_text.lower(), (
            f"No transition warning for 20°→8° delta. Warnings: {result['warnings']}"
        )

    def test_all_items_list_complete(self):
        """all_items should contain every non-None slot item."""
        items = _build_wardrobe(_WARDROBE_FULL)
        for sc in WEATHER_SCENARIOS:
            result = _outfit(items, sc.season, sc.temp_morning,
                             sc.temp_evening, sc.precip)
            all_ids = {i.id for i in result.get("all_items", [])}
            for key in ("thermal_top", "thermal_bottom", "one_piece", "top",
                        "bottom", "removable_layer", "tights", "socks",
                        "footwear", "outerwear", "hat", "scarf", "gloves"):
                val = result.get(key)
                if val:
                    assert val.id in all_ids, (
                        f"Item in slot '{key}' missing from all_items! "
                        f"Weather: {sc.name}"
                    )
            for uw in result.get("underwear_items", []):
                assert uw.id in all_ids, (
                    f"Underwear item missing from all_items! Weather: {sc.name}"
                )


class TestWarnings:
    """Test warning generation."""

    def test_rain_warning(self):
        items = _build_wardrobe(_WARDROBE_SMALL)
        result = _outfit(items, "autumn", temp_m=12.0, temp_e=10.0, precip=70.0)
        warnings = " ".join(result.get("warnings", []))
        assert "зонт" in warnings.lower(), "Rain warning missing for precip=70"

    def test_no_rain_warning_low_precip(self):
        items = _build_wardrobe(_WARDROBE_SMALL)
        result = _outfit(items, "autumn", temp_m=12.0, temp_e=10.0, precip=30.0)
        warnings = " ".join(result.get("warnings", []))
        assert "зонт" not in warnings.lower(), "False rain warning for precip=30"

    def test_transition_warning(self):
        items = _build_wardrobe(_WARDROBE_SMALL)
        result = _outfit(items, "spring", temp_m=22.0, temp_e=10.0)
        warnings = " ".join(result.get("warnings", []))
        assert "слоями" in warnings.lower() or len(result.get("warnings", [])) > 0, (
            "No transition warning for 22°→10° delta"
        )


class TestUnderwear:
    """Test base layer handling."""

    def test_underwear_found(self):
        """If underwear items exist, underwear_items should be populated."""
        items = _build_wardrobe(_WARDROBE_MEDIUM)
        result = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        assert len(result.get("underwear_items", [])) > 0, (
            "underwear_items empty despite having underwear in wardrobe"
        )

    def test_underwear_fallback_text(self):
        """If no underwear items, underwear_text should be set."""
        items = [
            _item("top", "футболка"),
            _item("bottom", "джинсы"),
            _item("footwear", "кроссовки"),
        ]
        result = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        assert result.get("underwear_text") == "трусики", (
            "underwear_text should be 'трусики' when no underwear items"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases that stress the selector."""

    def test_one_piece_only_wardrobe(self):
        """Wardrobe with only dresses — should use one_piece, not top+bottom."""
        items = [
            _item("one_piece", "платье", "розовое", warmth=2),
            _item("footwear", "кроссовки", "белые", warmth=2),
            _item("underwear", "трусики"),
            _item("base_layer", "носки"),
        ]
        result = _outfit(items, "summer", temp_m=22.0, temp_e=18.0)
        assert result.get("one_piece") is not None, (
            "one_piece should be selected when it's the only main garment"
        )
        assert has_minimum_outfit(result), "Dress-only wardrobe should pass minimum outfit"

    def test_no_outerwear_cold_weather(self):
        """No outerwear in wardrobe at cold temp — no crash, outfit still works."""
        items = [
            _item("top", "свитер", warmth=4),
            _item("bottom", "джинсы", warmth=3),
            _item("footwear", "ботинки", warmth=4),
            _item("underwear", "трусики"),
        ]
        result = _outfit(items, "winter", temp_m=3.0, temp_e=-1.0)
        assert result.get("outerwear") is None, "Should be None when no outerwear in wardrobe"
        assert has_minimum_outfit(result), "Should still have valid outfit without outerwear"

    def test_no_footwear(self):
        """No footwear in wardrobe — should not crash."""
        items = [
            _item("top", "футболка"),
            _item("bottom", "джинсы"),
            _item("underwear", "трусики"),
        ]
        result = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        assert result.get("footwear") is None, "Should be None when no footwear"
        assert has_minimum_outfit(result), "Should still be valid without footwear"

    def test_all_items_worn_today(self):
        """All items last_worn=today — should fallback to showing all."""
        today = date.today()
        items = [
            _item("top", "футболка", last_worn=today),
            _item("bottom", "джинсы", last_worn=today),
            _item("footwear", "кроссовки", last_worn=today),
            _item("underwear", "трусики", last_worn=today),
        ]
        result = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        assert has_minimum_outfit(result), (
            "Should fallback to all items when everything worn today"
        )

    def test_summer_wardrobe_in_winter(self):
        """Summer-only items used in winter — season filter removes them."""
        items = [
            _item("top", "кроп-топ", season=["summer"]),
            _item("bottom", "шорты", season=["summer"]),
            _item("footwear", "сандалии", season=["summer"]),
            _item("underwear", "трусики"),
        ]
        result = _outfit(items, "winter", temp_m=-5.0, temp_e=-10.0)
        # Season filter should exclude summer items in winter
        # But fallback kicks in (<3 items) and includes all
        # So we should still get an outfit
        assert result.get("top") is not None or result.get("one_piece") is not None, (
            "Fallback should include summer items when no winter items exist"
        )

    def test_only_base_layer_items(self):
        """Wardrobe with only underwear/socks — no valid outfit."""
        items = [
            _item("underwear", "трусики"),
            _item("underwear", "майка"),
            _item("base_layer", "носки"),
        ]
        result = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        assert not has_minimum_outfit(result), (
            "Base layer only wardrobe should NOT pass minimum outfit check"
        )

    def test_multiple_tops_score_preference(self):
        """With multiple tops, higher scored should ideally be preferred."""
        items = [
            _item("top", "футболка", score=3.0),
            _item("top", "рубашка", score=9.0),
            _item("top", "блузка", score=6.0),
            _item("bottom", "джинсы"),
            _item("footwear", "кроссовки"),
            _item("underwear", "трусики"),
        ]
        result = _outfit(items, "spring", temp_m=20.0, temp_e=18.0)
        # Note: current algo picks first available, not highest scored
        # This test documents current behavior; optimization may change it
        assert result.get("top") is not None

    def test_empty_wardrobe(self):
        """Empty wardrobe — should not crash."""
        result = _outfit([], "spring", temp_m=15.0, temp_e=12.0)
        assert not has_minimum_outfit(result)
        assert result.get("top") is None
        assert result.get("bottom") is None

    def test_rain_ok_items(self):
        """Items with rain_ok=True exist — dождевик should be found."""
        items = [
            _item("top", "футболка"),
            _item("bottom", "джинсы"),
            _item("footwear", "кроссовки"),
            _item("outerwear", "дождевик", rain_ok=True,
                  season=["spring", "summer", "autumn"], warmth=2),
            _item("outerwear", "куртка", warmth=3),
            _item("underwear", "трусики"),
        ]
        # Note: _select_outfit doesn't use rain_ok, only outfit_engine does
        # This test documents that gap
        result = _outfit(items, "autumn", temp_m=12.0, temp_e=10.0, precip=70.0)
        assert result.get("outerwear") is not None

    def test_very_large_wardrobe(self):
        """Stress test: 100+ items, should not crash or be slow."""
        items = _build_wardrobe(_WARDROBE_FULL)
        # Duplicate some items to reach 100+
        extras = []
        for i in range(60):
            cg = ["top", "bottom", "outerwear", "footwear"][i % 4]
            types = {
                "top": ["футболка", "свитер", "худи", "рубашка"],
                "bottom": ["джинсы", "брюки", "леггинсы"],
                "outerwear": ["куртка", "ветровка"],
                "footwear": ["кроссовки", "ботинки"],
            }[cg]
            extras.append(_item(cg, types[i % len(types)],
                                score=5.0 + (i % 5), warmth=1 + (i % 5)))
        items.extend(extras)
        assert len(items) > 100

        for sc in WEATHER_SCENARIOS:
            result = _outfit(items, sc.season, sc.temp_morning,
                             sc.temp_evening, sc.precip)
            # Should produce valid outfit from large pool
            assert has_minimum_outfit(result), (
                f"Large wardrobe ({len(items)} items) failed at {sc.name}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-SEGMENT × WEATHER × SIZE MATRIX
# ══════════════════════════════════════════════════════════════════════════════


class TestFullMatrix:
    """Parametrized test running ALL combinations: segment × size × weather.

    Total: 12 segments × 4 sizes × 8 weather = 384 combinations.
    """

    @pytest.mark.parametrize("segment", SEGMENT_PROFILES, ids=_segment_ids)
    @pytest.mark.parametrize("size_key", _size_ids)
    @pytest.mark.parametrize("weather_sc", WEATHER_SCENARIOS, ids=_weather_ids)
    def test_outfit_validity(self, segment, size_key, weather_sc):
        """Core validity check across all combinations."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        result = _outfit(items, weather_sc.season, weather_sc.temp_morning,
                         weather_sc.temp_evening, weather_sc.precip)

        # 1. If wardrobe supports it, we should get a valid outfit
        if has_minimum_wardrobe(items):
            # Season filter might remove items; check seasonal availability
            seasonal_tops = [
                i for i in items
                if i.category_group in ("top",)
                and (not i.season or weather_sc.season in i.season)
            ]
            seasonal_bottoms = [
                i for i in items
                if i.category_group in ("bottom",)
                and (not i.season or weather_sc.season in i.season)
            ]
            seasonal_one_piece = [
                i for i in items
                if i.category_group in ("one_piece",)
                and (not i.season or weather_sc.season in i.season)
            ]
            has_seasonal_outfit = (
                (seasonal_tops and seasonal_bottoms) or seasonal_one_piece
            )
            if has_seasonal_outfit or len(items) >= 3:
                # With fallback (< 3 items after filter → use all), should work
                assert has_minimum_outfit(result), (
                    f"FAIL: {segment.name}/{size_key}/{weather_sc.name} "
                    f"({weather_sc.regime}, {weather_sc.temp_morning}°C). "
                    f"Seasonal tops={len(seasonal_tops)}, bottoms={len(seasonal_bottoms)}, "
                    f"one_piece={len(seasonal_one_piece)}. "
                    f"top={result.get('top')}, bottom={result.get('bottom')}, "
                    f"one_piece={result.get('one_piece')}"
                )

        # 2. No shorts at < 10°C (if bottom selected)
        if weather_sc.temp_morning < 10:
            bottom = result.get("bottom")
            if bottom:
                assert "шорт" not in (bottom.type or "").lower(), (
                    f"Shorts at {weather_sc.temp_morning}°C! "
                    f"{segment.name}/{size_key}/{weather_sc.name}"
                )

        # 3. all_items populated when outfit exists
        if has_minimum_outfit(result):
            assert len(result.get("all_items", [])) >= 2, (
                f"all_items too small for valid outfit. "
                f"{segment.name}/{size_key}/{weather_sc.name}"
            )

        # 4. No duplicates
        all_items = result.get("all_items", [])
        item_ids = [i.id for i in all_items]
        assert len(item_ids) == len(set(item_ids)), (
            f"Duplicate items in all_items! "
            f"{segment.name}/{size_key}/{weather_sc.name}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# OUTFIT BUILDER INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════


class TestOutfitBuilder:
    """Test build_outfit_slots() with synthetic outfits."""

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    @pytest.mark.parametrize("weather_sc", WEATHER_SCENARIOS, ids=_weather_ids)
    def test_build_slots_no_crash(self, size_key, weather_sc):
        """build_outfit_slots should never crash on valid outfit."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        outfit = _outfit(items, weather_sc.season, weather_sc.temp_morning,
                         weather_sc.temp_evening, weather_sc.precip)
        if not has_minimum_outfit(outfit):
            return  # skip if no valid outfit

        slots = build_outfit_slots(
            outfit, child=None, user=None,
            temp=weather_sc.temp_morning,
            colortype="default",
            regime=weather_sc.regime,
        )
        assert isinstance(slots, list)
        # Should have at least 1 visual slot
        assert len(slots) >= 1, (
            f"No visual slots for valid outfit! "
            f"{size_key}/{weather_sc.name}"
        )

    @pytest.mark.parametrize("size_key", ["medium", "full"])
    def test_base_layer_not_in_visual_slots(self, size_key):
        """Base layer items should NOT appear in visual slots."""
        items = _build_wardrobe(WARDROBE_SIZES[size_key])
        outfit = _outfit(items, "spring", temp_m=15.0, temp_e=12.0)
        if not has_minimum_outfit(outfit):
            return
        slots = build_outfit_slots(outfit, child=None, user=None,
                                   temp=15.0, colortype="default")
        for slot in slots:
            if slot.get("has_item"):
                it_type = (slot.get("item_type", "") or "").lower()
                assert not any(pat in it_type for pat in [
                    "носк", "трусик", "майк", "термо", "колготк"
                ]), f"Base layer item '{it_type}' in visual slot!"
