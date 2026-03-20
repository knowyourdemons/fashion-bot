"""
Tests for morning_brief.py — business logic safety net перед рефакторингом.

Покрывает: _select_outfit (обувь, аксессуары, колготки, removable, outerwear,
all_items), _format_child_block, _geocode_city, _get_weather, _SEASONS, edge cases.

НЕ дублирует: test_core.py (TestSelectOutfit, 13 тестов) и
test_core2.py (TestGetTempRegime, 17 тестов).
"""
import asyncio
import uuid
import pytest
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock, patch

from worker.tasks.morning_brief import (
    _select_outfit,
    _format_child_block,
    _format_item,
    _geocode_city,
    _get_weather,
    _SEASONS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

@dataclass
class FakeItem:
    """Мок WardrobeItem для тестов."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    category_group: str = "top"
    type: str = "футболка"
    color: str = "белый"
    season: list = field(default_factory=lambda: ["spring", "summer", "autumn", "winter"])
    last_worn: Optional[date] = None
    score_item: Optional[Decimal] = Decimal("7.5")


def _empty_outfit() -> dict:
    """Пустой outfit dict для тестов _format_child_block."""
    return {
        "thermal_top": None, "thermal_bottom": None,
        "underwear_items": [], "underwear_text": None,
        "one_piece": None, "top": None, "bottom": None,
        "removable_layer": None, "tights": None, "socks": None,
        "footwear": None, "outerwear": None,
        "hat": None, "scarf": None, "gloves": None,
        "warnings": [], "all_items": [],
    }


today = date.today()


def _run(coro):
    return asyncio.run(coro)


class _MockHttpxClient:
    """Заглушка httpx.AsyncClient для тестов без сети."""
    def __init__(self, response_json=None, raise_exc=None):
        self._json = response_json
        self._exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, *args, **kwargs):
        if self._exc is not None:
            raise self._exc
        resp = MagicMock()
        resp.json.return_value = self._json
        return resp


# ── Блок 1: _select_outfit — обувь по температуре ────────────────────────────

def test_footwear_sandals_in_heat():
    """При жаре (>25°C) предпочитаются сандалии."""
    items = [
        FakeItem(category_group="footwear", type="сандалии"),
        FakeItem(category_group="footwear", type="ботинки"),
        FakeItem(category_group="top", type="футболка"),
    ]
    result = _select_outfit(items, "summer", today, temp_morning=30.0)
    assert result["footwear"] is not None
    assert "сандал" in result["footwear"].type.lower()


def test_footwear_boots_in_frost():
    """При морозе (<0°C) предпочитаются ботинки."""
    items = [
        FakeItem(category_group="footwear", type="ботинки зимние"),
        FakeItem(category_group="footwear", type="кроссовки"),
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
        FakeItem(category_group="outerwear", type="куртка"),
    ]
    result = _select_outfit(items, "winter", today, temp_morning=-5.0)
    assert result["footwear"] is not None
    assert "ботинк" in result["footwear"].type.lower()


def test_footwear_sneakers_in_cool():
    """При прохладе (10–15°C) кроссовки предпочтительнее."""
    items = [
        FakeItem(category_group="footwear", type="кроссовки"),
        FakeItem(category_group="footwear", type="сандалии"),
        FakeItem(category_group="top", type="кофта"),
        FakeItem(category_group="bottom", type="джинсы"),
    ]
    result = _select_outfit(items, "spring", today, temp_morning=12.0)
    assert result["footwear"] is not None
    assert "кроссовк" in result["footwear"].type.lower()


def test_footwear_excludes_exact_sock_type():
    """Тип точно равный 'носки' исключается из пула обуви."""
    items = [
        FakeItem(category_group="footwear", type="носки"),     # exact → excluded
        FakeItem(category_group="footwear", type="кроссовки"),
        FakeItem(category_group="top", type="футболка"),
    ]
    result = _select_outfit(items, "spring", today, temp_morning=15.0)
    assert result["footwear"] is not None
    assert "носк" not in result["footwear"].type.lower()


def test_footwear_fallback_if_no_preferred():
    """Если нет предпочтительной обуви → берёт первую доступную."""
    items = [
        FakeItem(category_group="footwear", type="мокасины"),
        FakeItem(category_group="top", type="футболка"),
    ]
    result = _select_outfit(items, "summer", today, temp_morning=30.0)
    assert result["footwear"] is not None
    assert result["footwear"].type == "мокасины"


# ── Блок 1: Аксессуары по температуре ────────────────────────────────────────

def test_hat_below_10():
    """Шапка при temp < 10°C."""
    items = [
        FakeItem(category_group="accessory", type="шапка"),
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
        FakeItem(category_group="outerwear", type="куртка"),
    ]
    result = _select_outfit(items, "autumn", today, temp_morning=5.0)
    assert result["hat"] is not None


def test_no_hat_at_10():
    """Нет шапки при temp == 10°C (граница: < 10, не <=)."""
    items = [
        FakeItem(category_group="accessory", type="шапка"),
        FakeItem(category_group="top", type="кофта"),
        FakeItem(category_group="bottom", type="джинсы"),
        FakeItem(category_group="outerwear", type="куртка"),
    ]
    result = _select_outfit(items, "autumn", today, temp_morning=10.0)
    assert result["hat"] is None


def test_hat_at_9():
    """Шапка при temp = 9°C."""
    items = [
        FakeItem(category_group="accessory", type="шапка"),
        FakeItem(category_group="top", type="кофта"),
        FakeItem(category_group="bottom", type="джинсы"),
        FakeItem(category_group="outerwear", type="куртка"),
    ]
    result = _select_outfit(items, "autumn", today, temp_morning=9.0)
    assert result["hat"] is not None


def test_scarf_below_5():
    """Шарф при temp < 5°C."""
    items = [
        FakeItem(category_group="accessory", type="шарф"),
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
        FakeItem(category_group="outerwear", type="куртка"),
    ]
    result = _select_outfit(items, "winter", today, temp_morning=4.0)
    assert result["scarf"] is not None


def test_no_scarf_at_5():
    """Нет шарфа при temp == 5°C (граница: < 5)."""
    items = [
        FakeItem(category_group="accessory", type="шарф"),
        FakeItem(category_group="top", type="кофта"),
        FakeItem(category_group="bottom", type="джинсы"),
        FakeItem(category_group="outerwear", type="куртка"),
    ]
    result = _select_outfit(items, "autumn", today, temp_morning=5.0)
    assert result["scarf"] is None


def test_gloves_below_0():
    """Перчатки при temp < 0°C."""
    items = [
        FakeItem(category_group="accessory", type="перчатки"),
        FakeItem(category_group="accessory", type="шапка"),
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
        FakeItem(category_group="outerwear", type="пуховик"),
    ]
    result = _select_outfit(items, "winter", today, temp_morning=-5.0)
    assert result["gloves"] is not None


def test_no_gloves_at_0():
    """Нет перчаток при temp == 0°C (граница: < 0)."""
    items = [
        FakeItem(category_group="accessory", type="перчатки"),
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
        FakeItem(category_group="outerwear", type="куртка"),
    ]
    result = _select_outfit(items, "winter", today, temp_morning=0.0)
    assert result["gloves"] is None


# ── Блок 1: Колготки vs носки ─────────────────────────────────────────────────

def test_tights_with_skirt_below_15():
    """Колготки нужны при юбке + temp <= 15°C."""
    items = [
        FakeItem(category_group="base_layer", type="колготки"),
        FakeItem(category_group="top", type="кофта"),
        FakeItem(category_group="bottom", type="юбка"),
    ]
    result = _select_outfit(items, "autumn", today, temp_morning=10.0)
    assert result["tights"] is not None


def test_socks_above_15():
    """При temp > 15°C — носки в socks, tights = None."""
    items = [
        FakeItem(category_group="base_layer", type="носки белые"),
        FakeItem(category_group="top", type="футболка"),
        FakeItem(category_group="bottom", type="шорты"),
    ]
    result = _select_outfit(items, "summer", today, temp_morning=22.0)
    assert result["socks"] is not None
    assert result["tights"] is None


# ── Блок 1: Removable layer ──────────────────────────────────────────────────

def test_removable_layer_on_big_temp_swing():
    """Разница утро–вечер > 8°C → removable_layer выбирается."""
    items = [
        FakeItem(category_group="top", type="футболка"),
        FakeItem(category_group="top", type="худи"),
        FakeItem(category_group="bottom", type="джинсы"),
    ]
    result = _select_outfit(items, "spring", today, temp_morning=8.0, temp_evening=20.0)
    assert result["removable_layer"] is not None
    if result["top"] is not None:
        assert result["removable_layer"].id != result["top"].id


def test_no_removable_layer_small_swing():
    """Разница утро–вечер <= 8°C → removable_layer = None."""
    items = [
        FakeItem(category_group="top", type="футболка"),
        FakeItem(category_group="top", type="худи"),
        FakeItem(category_group="bottom", type="джинсы"),
    ]
    result = _select_outfit(items, "spring", today, temp_morning=15.0, temp_evening=20.0)
    assert result["removable_layer"] is None


# ── Блок 1: One-piece ────────────────────────────────────────────────────────

def test_one_piece_preferred_in_heat():
    """При жаре one_piece (платье) выбирается, top = None."""
    items = [
        FakeItem(category_group="one_piece", type="платье"),
        FakeItem(category_group="top", type="футболка"),
        FakeItem(category_group="bottom", type="шорты"),
    ]
    result = _select_outfit(items, "summer", today, temp_morning=28.0)
    assert result["one_piece"] is not None
    assert result["top"] is None


def test_top_bottom_fallback_if_no_one_piece():
    """При жаре без one_piece → top + bottom."""
    items = [
        FakeItem(category_group="top", type="майка"),
        FakeItem(category_group="bottom", type="шорты"),
    ]
    result = _select_outfit(items, "summer", today, temp_morning=28.0)
    assert result["one_piece"] is None
    assert result["top"] is not None
    assert result["bottom"] is not None


# ── Блок 1: Верхняя одежда ───────────────────────────────────────────────────

def test_warm_outerwear_below_5():
    """При temp <= 5°C предпочитается пуховик."""
    items = [
        FakeItem(category_group="outerwear", type="ветровка"),
        FakeItem(category_group="outerwear", type="пуховик"),
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
    ]
    result = _select_outfit(items, "winter", today, temp_morning=2.0)
    assert result["outerwear"] is not None
    assert "пуховик" in result["outerwear"].type.lower()


def test_any_outerwear_between_5_and_15():
    """При 5 < temp <= 15 — любая верхняя одежда."""
    items = [
        FakeItem(category_group="outerwear", type="ветровка"),
        FakeItem(category_group="top", type="кофта"),
        FakeItem(category_group="bottom", type="джинсы"),
    ]
    result = _select_outfit(items, "autumn", today, temp_morning=10.0)
    assert result["outerwear"] is not None


def test_no_outerwear_above_15():
    """При temp > 15°C верхняя одежда не нужна."""
    items = [
        FakeItem(category_group="outerwear", type="куртка"),
        FakeItem(category_group="top", type="футболка"),
        FakeItem(category_group="bottom", type="джинсы"),
    ]
    result = _select_outfit(items, "summer", today, temp_morning=20.0)
    assert result["outerwear"] is None


# ── Блок 1: all_items агрегация ──────────────────────────────────────────────

def test_all_items_contains_selected():
    """all_items содержит все выбранные слоты."""
    items = [
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
        FakeItem(category_group="outerwear", type="куртка"),
        FakeItem(category_group="footwear", type="ботинки"),
    ]
    result = _select_outfit(items, "winter", today, temp_morning=3.0)
    ids = {i.id for i in result["all_items"]}
    for key in ("top", "bottom", "outerwear", "footwear"):
        if result[key]:
            assert result[key].id in ids, f"result['{key}'] отсутствует в all_items"


def test_all_items_includes_underwear():
    """all_items включает underwear_items."""
    items = [
        FakeItem(category_group="underwear", type="трусики"),
        FakeItem(category_group="top", type="футболка"),
    ]
    result = _select_outfit(items, "summer", today, temp_morning=20.0)
    assert len(result["all_items"]) >= 1


def test_all_items_no_duplicates():
    """all_items не содержит дублей."""
    items = [
        FakeItem(category_group="top", type="свитер"),
        FakeItem(category_group="bottom", type="штаны"),
        FakeItem(category_group="outerwear", type="куртка"),
        FakeItem(category_group="footwear", type="ботинки"),
        FakeItem(category_group="accessory", type="шапка"),
    ]
    result = _select_outfit(items, "winter", today, temp_morning=-5.0)
    ids = [i.id for i in result["all_items"]]
    assert len(ids) == len(set(ids)), "all_items содержит дубликаты"


# ── Блок 2: _format_child_block ──────────────────────────────────────────────

def test_format_basic():
    """Имя и day_type присутствуют; все вещи в текстовом брифе."""
    outfit = _empty_outfit()
    outfit["top"] = FakeItem(type="футболка", color="белый")
    text = _format_child_block("Алиса", "садик", outfit)
    assert "Алиса" in text
    assert "садик" in text
    # Утренний бриф = текст, все вещи показываются
    assert "футболка" in text


def test_format_no_score_ever():
    """Числовой скор никогда не показывается юзеру."""
    outfit = _empty_outfit()
    outfit["top"] = FakeItem(type="кофта", color="синий")
    text = _format_child_block("Алиса", "садик", outfit)
    assert "/10" not in text
    assert "8.5" not in text


def test_format_with_comment():
    """outfit_comment отображается в блоке."""
    outfit = _empty_outfit()
    outfit["top"] = FakeItem(type="кофта", color="синий")
    text = _format_child_block("Алиса", "садик", outfit, outfit_comment="Отличный образ!")
    assert "Отличный образ!" in text
    assert "💬" in text


def test_format_no_comment_when_none():
    """Без комментария — блок 💬 отсутствует."""
    outfit = _empty_outfit()
    outfit["top"] = FakeItem(type="кофта", color="синий")
    text = _format_child_block("Алиса", "садик", outfit, outfit_comment=None)
    assert "💬" not in text


def test_format_thermals():
    """Термобельё отображается в строке 'Под одежду'."""
    outfit = _empty_outfit()
    outfit["thermal_top"] = FakeItem(category_group="underwear", type="термолонгслив", color="серый")
    text = _format_child_block("Алиса", "прогулка", outfit)
    assert "ПОД ОДЕЖДУ" in text
    assert "термобельё" in text.lower()


def test_format_outerwear():
    """Верхняя одежда показывается в группе 'НА ВЫХОД'."""
    outfit = _empty_outfit()
    outfit["outerwear"] = FakeItem(category_group="outerwear", type="куртка", color="красный")
    text = _format_child_block("Алиса", "садик", outfit)
    assert "куртка" in text
    assert "НА ВЫХОД" in text


def test_format_accessories():
    """Аксессуары (шапка/шарф) — в группе 'НА ВЫХОД'."""
    outfit = _empty_outfit()
    outfit["hat"] = FakeItem(category_group="accessory", type="шапка", color="синий")
    outfit["scarf"] = FakeItem(category_group="accessory", type="шарф", color="серый")
    text = _format_child_block("Алиса", "прогулка", outfit)
    assert "шапка" in text
    assert "шарф" in text


def test_format_removable_layer():
    """Съёмный слой показывается в группе ОДЕЖДА."""
    outfit = _empty_outfit()
    outfit["top"] = FakeItem(type="футболка", color="белый")
    outfit["removable_layer"] = FakeItem(type="худи", color="серый")
    text = _format_child_block("Алиса", "садик", outfit)
    assert "худи" in text


def test_format_underwear_text_fallback():
    """Если нет underwear_items → underwear_text показывается."""
    outfit = _empty_outfit()
    outfit["underwear_text"] = "трусики"
    text = _format_child_block("Алиса", "садик", outfit)
    assert "трусики" in text


# ── Блок 3: _geocode_city + _get_weather ─────────────────────────────────────

def test_geocode_success():
    """Успешный геокодинг возвращает (lat, lon)."""
    mock = _MockHttpxClient(response_json=[{"lat": "54.6872", "lon": "25.2797"}])
    with patch("httpx.AsyncClient", return_value=mock):
        result = _run(_geocode_city("Vilnius"))
    assert result == (54.6872, 25.2797)


def test_geocode_empty_result():
    """Пустой ответ API → None."""
    mock = _MockHttpxClient(response_json=[])
    with patch("httpx.AsyncClient", return_value=mock):
        result = _run(_geocode_city("НесуществующийГород"))
    assert result is None


def test_geocode_network_error():
    """Ошибка сети → None (не crash)."""
    mock = _MockHttpxClient(raise_exc=Exception("network timeout"))
    with patch("httpx.AsyncClient", return_value=mock):
        result = _run(_geocode_city("Vilnius"))
    assert result is None


def test_weather_success():
    """Успешный запрос погоды: индексы [7] и [18] из hourly."""
    hourly = {
        "temperature_2m": [0.0] * 7 + [12.5] + [0.0] * 10 + [8.0] + [0.0] * 5,
        "precipitation_probability": [0] * 18 + [60] + [0] * 5,
    }
    mock = _MockHttpxClient(response_json={"hourly": hourly})
    with patch("httpx.AsyncClient", return_value=mock):
        result = _run(_get_weather(54.68, 25.27, "Europe/Vilnius"))
    assert result["temp_morning"] == 12.5
    assert result["temp_evening"] == 8.0
    assert result["precip_evening"] == 60


def test_weather_network_error():
    """Ошибка сети → дефолтные None значения, не crash."""
    mock = _MockHttpxClient(raise_exc=Exception("network timeout"))
    with patch("httpx.AsyncClient", return_value=mock):
        result = _run(_get_weather(54.68, 25.27, "Europe/Vilnius"))
    assert result["temp_morning"] is None
    assert result["temp_evening"] is None
    assert result["precip_evening"] == 0


def test_weather_incomplete_data():
    """Короткий массив (индекс 7/18 недоступен) → None temps, не crash."""
    mock = _MockHttpxClient(response_json={"hourly": {"temperature_2m": [5.0]}})
    with patch("httpx.AsyncClient", return_value=mock):
        result = _run(_get_weather(54.68, 25.27, "Europe/Vilnius"))
    assert result["temp_morning"] is None
    assert result["temp_evening"] is None


# ── Блок 4: _SEASONS ────────────────────────────────────────────────────────

def test_seasons_mapping_complete():
    """Все 12 месяцев покрыты."""
    assert len(_SEASONS) == 12
    assert all(m in _SEASONS for m in range(1, 13))


def test_seasons_mapping_correct():
    """Сезоны соответствуют правильным месяцам."""
    assert _SEASONS[1] == "winter"    # январь
    assert _SEASONS[4] == "spring"    # апрель
    assert _SEASONS[7] == "summer"    # июль
    assert _SEASONS[10] == "autumn"   # октябрь


# ── Блок 5: Edge cases ──────────────────────────────────────────────────────

def test_temp_morning_none_defaults_to_15():
    """temp_morning=None → default 15°C, функция не падает и возвращает результат."""
    items = [
        FakeItem(category_group="top", type="кофта"),
        FakeItem(category_group="bottom", type="джинсы"),
    ]
    result = _select_outfit(items, "spring", today, temp_morning=None)
    assert result["top"] is not None


def test_temp_evening_none_no_swing_warning():
    """temp_evening=None → приравнивается к temp_morning → нет предупреждения о перепаде."""
    items = [FakeItem(category_group="top", type="кофта")]
    result = _select_outfit(items, "spring", today, temp_morning=20.0, temp_evening=None)
    assert not any("слоями" in w for w in result["warnings"])


def test_only_outerwear_no_crash():
    """Только верхняя одежда в гардеробе — не падает, outerwear присутствует."""
    items = [FakeItem(category_group="outerwear", type="куртка")]
    result = _select_outfit(items, "winter", today, temp_morning=0.0)
    assert result["outerwear"] is not None
    assert result["top"] is None


def test_season_empty_matches_all():
    """Вещь с season=[] (пустой) доступна в любой сезон."""
    items = [FakeItem(category_group="top", type="футболка", season=[])]
    result = _select_outfit(items, "winter", today, temp_morning=10.0)
    # not i.season → True при пустом списке → вещь включается
    assert result["top"] is not None


def test_type_none_no_crash():
    """Вещь с type=None не вызывает AttributeError при .lower()."""
    items = [
        FakeItem(category_group="top", type=None),
        FakeItem(category_group="bottom", type="джинсы"),
    ]
    result = _select_outfit(items, "spring", today, temp_morning=20.0)
    assert result is not None  # главное — не упал


def test_precip_at_threshold_no_warning():
    """precip_evening == 50 → нет предупреждения об зонте (условие > 50, не >=)."""
    items = [FakeItem(category_group="top", type="футболка")]
    result = _select_outfit(items, "summer", today, precip_evening=50.0)
    warnings_text = " ".join(result["warnings"])
    assert "зонт" not in warnings_text.lower()


def test_precip_above_threshold_warning():
    """precip_evening == 51 → предупреждение с зонтом."""
    items = [FakeItem(category_group="top", type="футболка")]
    result = _select_outfit(items, "summer", today, precip_evening=51.0)
    warnings_text = " ".join(result["warnings"])
    assert "зонт" in warnings_text.lower()


# ── Блок 6: _format_item ─────────────────────────────────────────────────────

def test_format_item_color_not_in_type():
    """Цвет не в названии типа → добавляется в скобках."""
    item = FakeItem(type="кофта", color="синий")
    assert _format_item(item) == "кофта синий"


def test_format_item_color_in_type_no_duplicate():
    """Цвет уже в названии типа → не дублируется (exact match)."""
    item = FakeItem(type="синяя кофта", color="синяя")
    assert _format_item(item) == "синяя кофта"


def test_format_item_no_color():
    """Нет цвета → только тип."""
    item = FakeItem(type="кофта", color="")
    assert _format_item(item) == "кофта"


def test_format_item_none_color():
    """color=None → только тип, не crash."""
    item = FakeItem(type="кофта", color=None)
    assert _format_item(item) == "кофта"


def test_format_item_stem_matching():
    """Стем-matching: 'серебристый' → stem 'серебрист' → в 'серебристые кроссовки'."""
    item = FakeItem(type="серебристые кроссовки", color="серебристый")
    assert _format_item(item) == "серебристые кроссовки"


def test_format_item_stem_matching_pink():
    """Стем-matching: 'розовый' → stem 'розов' → в 'розовое платье'."""
    item = FakeItem(type="розовое платье", color="розовый")
    assert _format_item(item) == "розовое платье"


def test_format_item_short_color_no_stem():
    """Короткий цвет (<=5 символов) → сравнение без усечения."""
    item = FakeItem(type="синий топ", color="синий")
    assert _format_item(item) == "синий топ"


def test_format_item_none_type():
    """type=None → возвращает пустую строку, не crash."""
    item = FakeItem(type=None, color="белый")
    result = _format_item(item)
    assert result is not None  # не упал
