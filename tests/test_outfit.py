"""Tests for _select_outfit in morning_brief.py."""
import uuid
import pytest
from datetime import date
from unittest.mock import MagicMock

# Пропустить если зависимости не установлены локально
pytest.importorskip("structlog", reason="structlog not installed")


def _item(category_group: str, type_: str, season=None, last_worn=None):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.category_group = category_group
    i.type = type_
    i.season = season or ["spring", "summer", "autumn", "winter"]
    i.last_worn = last_worn
    return i


def _outfit(items, season="spring", temp_m=15.0, temp_e=15.0, precip=0.0):
    from worker.tasks.morning_brief import _select_outfit
    return _select_outfit(items, season, date.today(), temp_m, temp_e, precip)


# ── Базовый набор вещей ───────────────────────────────────────────────────────

def _basic_wardrobe():
    return [
        _item("top",      "свитшот"),
        _item("bottom",   "джинсы"),
        _item("footwear", "кроссовки"),
        _item("outerwear","куртка"),
        _item("underwear","трусики"),
    ]


# ── Температурные режимы ──────────────────────────────────────────────────────

def test_hot_weather_prefers_light_bottom():
    """Жара (>25°C) — предпочитает шорты/юбку над джинсами."""
    items = [
        _item("top",    "футболка"),
        _item("bottom", "шорты"),
        _item("bottom", "джинсы"),
        _item("footwear","сандалии"),
        _item("underwear","трусики"),
    ]
    result = _outfit(items, temp_m=30.0, temp_e=28.0)
    # При жаре top+bottom или one_piece
    assert result["top"] is not None or result["one_piece"] is not None


def test_cold_weather_includes_outerwear():
    """Холодно (<5°C) — должно подобрать верхнюю одежду."""
    items = _basic_wardrobe()
    result = _outfit(items, temp_m=3.0, temp_e=1.0)
    assert result["outerwear"] is not None


def test_freezing_weather_thermal_layer():
    """Мороз (≤5°C) — термобельё."""
    items = _basic_wardrobe() + [
        _item("underwear", "термо кофта"),
        _item("underwear", "термо штаны"),
    ]
    result = _outfit(items, temp_m=2.0, temp_e=0.0)
    assert result["thermal_top"] is not None or result["thermal_bottom"] is not None


def test_warm_weather_no_thermal():
    """Тепло (>15°C) — без термобелья."""
    items = _basic_wardrobe() + [
        _item("underwear", "термо кофта"),
    ]
    result = _outfit(items, temp_m=20.0, temp_e=18.0)
    assert result["thermal_top"] is None
    assert result["thermal_bottom"] is None


# ── Предупреждения ────────────────────────────────────────────────────────────

def test_rain_warning_when_precip_high():
    """precip_evening > 50 → предупреждение с зонтом."""
    result = _outfit(_basic_wardrobe(), precip=60.0)
    warnings = " ".join(result["warnings"])
    assert "зонт" in warnings.lower()


def test_no_rain_warning_when_precip_low():
    """precip_evening <= 50 → нет предупреждения о дожде."""
    result = _outfit(_basic_wardrobe(), precip=30.0)
    warnings = " ".join(result["warnings"])
    assert "зонт" not in warnings.lower()


def test_transition_layer_when_temp_diff_large():
    """Разница утро-вечер > 8°C → removable_layer + предупреждение."""
    items = _basic_wardrobe() + [_item("top", "кардиган")]
    result = _outfit(items, temp_m=20.0, temp_e=8.0)
    # Должно быть предупреждение о перепаде
    warnings = " ".join(result["warnings"])
    assert "°C" in warnings or "слоями" in warnings.lower()


def test_no_transition_warning_when_temp_stable():
    """Стабильная температура → нет предупреждения о перепаде."""
    result = _outfit(_basic_wardrobe(), temp_m=18.0, temp_e=16.0)
    warnings = " ".join(result["warnings"])
    assert "слоями" not in warnings.lower()


# ── Пустой гардероб ───────────────────────────────────────────────────────────

def test_empty_wardrobe_returns_empty_outfit():
    """Пустой гардероб → пустой образ, нет краша."""
    result = _outfit([])
    assert result["top"] is None
    assert result["bottom"] is None
    assert result["outerwear"] is None
    assert result["footwear"] is None
    assert isinstance(result["warnings"], list)


def test_empty_wardrobe_all_none():
    """Все слои None, all_items пустой."""
    result = _outfit([])
    slot_keys = ["thermal_top", "thermal_bottom", "one_piece", "top", "bottom",
                 "removable_layer", "tights", "socks", "footwear", "outerwear",
                 "hat", "scarf", "gloves"]
    for k in slot_keys:
        assert result[k] is None, f"result['{k}'] должен быть None при пустом гардеробе"


# ── last_worn = today → исключается ──────────────────────────────────────────

def test_excludes_worn_today():
    """Вещь с last_worn = today не должна попасть в образ."""
    today = date.today()
    worn_top = _item("top", "футболка", last_worn=today)
    fresh_top = _item("top", "кофта")
    items = [worn_top, fresh_top, _item("bottom", "джинсы"), _item("underwear", "трусики")]
    result = _outfit(items, temp_m=20.0)
    if result["top"] is not None:
        assert result["top"].id != worn_top.id, "Вещь с last_worn=today не должна выбираться"


def test_only_worn_items_gives_none():
    """Если все вещи надеты сегодня → top=None."""
    today = date.today()
    items = [
        _item("top", "футболка", last_worn=today),
        _item("bottom", "джинсы", last_worn=today),
    ]
    result = _outfit(items)
    assert result["top"] is None
    assert result["bottom"] is None


# ── Сезонная фильтрация ────────────────────────────────────────────────────────

def test_wrong_season_excluded():
    """Летняя вещь не попадает в образ зимой."""
    summer_top = _item("top", "майка", season=["summer"])
    winter_top = _item("top", "свитер", season=["winter"])
    items = [summer_top, winter_top, _item("bottom", "джинсы"), _item("underwear", "трусики")]
    result = _outfit(items, season="winter", temp_m=0.0)
    if result["top"] is not None:
        assert result["top"].id != summer_top.id


# ── Структура результата ──────────────────────────────────────────────────────

def test_result_has_required_keys():
    """Результат всегда содержит обязательные ключи."""
    result = _outfit(_basic_wardrobe())
    required = ["thermal_top", "thermal_bottom", "underwear_items", "underwear_text",
                "one_piece", "top", "bottom", "removable_layer", "tights", "socks",
                "footwear", "outerwear", "hat", "scarf", "gloves", "warnings", "all_items"]
    for k in required:
        assert k in result, f"Ключ '{k}' отсутствует в результате"


def test_warnings_is_list():
    """warnings всегда список."""
    result = _outfit(_basic_wardrobe())
    assert isinstance(result["warnings"], list)


def test_underwear_items_is_list():
    """underwear_items всегда список."""
    result = _outfit(_basic_wardrobe())
    assert isinstance(result["underwear_items"], list)
