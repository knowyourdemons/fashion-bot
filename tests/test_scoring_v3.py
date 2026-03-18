"""
Tests for scoring v3.0: матрицы, classify_role, get_wardrobe_balance_insight,
generate_item_comment, generate_outfit_comment.
"""
import pytest
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────────

@dataclass
class FakeChild:
    birthdate: date
    gender: str = "girl"
    name: str = "Алиса"
    colortype: Optional[str] = None


@dataclass
class FakeUser:
    segment: str = "no_kids"
    age: Optional[int] = None
    trimester: Optional[int] = None
    colortype: Optional[str] = None


@dataclass
class FakeItem:
    role: Optional[str] = None
    score_item: Optional[Decimal] = None
    type: str = "футболка"
    color: str = "белый"


class MockAnthropicPool:
    def __init__(self, response_text: str = "Отличная вещь!"):
        self._text = response_text

    async def create_message(self, **kwargs):
        msg = MagicMock()
        msg.content = [MagicMock(text=self._text)]
        return msg


# ── Тесты матриц ──────────────────────────────────────────────────────────────

def test_all_child_matrices_have_gender():
    """Все детские матрицы (age_to <= 16) имеют gender != 'all'."""
    from db.seeds.scoring_matrices import _MATRICES_V3
    for m in _MATRICES_V3:
        if not m.get("is_pregnant") and m["age_to"] <= 16:
            assert m["gender"] in ("boy", "girl"), \
                f"{m['name']} has gender={m['gender']}, expected boy or girl"


def test_matrix_name_girl_4_years():
    from services.scoring import matrix_name_for_owner
    child = FakeChild(birthdate=date.today() - timedelta(days=365 * 4), gender="girl")
    assert matrix_name_for_owner(None, child) == "3-7-girl"


def test_matrix_name_boy_4_years():
    from services.scoring import matrix_name_for_owner
    child = FakeChild(birthdate=date.today() - timedelta(days=365 * 4), gender="boy")
    assert matrix_name_for_owner(None, child) == "3-7-boy"


def test_matrix_name_girl_9_years():
    from services.scoring import matrix_name_for_owner
    child = FakeChild(birthdate=date.today() - timedelta(days=365 * 9), gender="girl")
    assert matrix_name_for_owner(None, child) == "7-12-girl"


def test_matrix_name_boy_15_years():
    from services.scoring import matrix_name_for_owner
    child = FakeChild(birthdate=date.today() - timedelta(days=365 * 15), gender="boy")
    assert matrix_name_for_owner(None, child) == "12-16-boy"


def test_all_matrices_have_tone():
    """Все матрицы имеют _tone в критериях."""
    from db.seeds.scoring_matrices import _MATRICES_V3
    for m in _MATRICES_V3:
        assert "_tone" in m["criteria"], f"{m['name']} missing _tone"
        assert m["criteria"]["_tone"], f"{m['name']} has empty _tone"


def test_all_matrices_have_wow_messages():
    """Все матрицы имеют _wow_messages (не менее 2)."""
    from db.seeds.scoring_matrices import _MATRICES_V3
    for m in _MATRICES_V3:
        assert "_wow_messages" in m["criteria"], f"{m['name']} missing _wow_messages"
        assert len(m["criteria"]["_wow_messages"]) >= 2, \
            f"{m['name']} has fewer than 2 wow messages"


def test_max_score_matches_weights():
    """max_score == sum(weight × 2) для каждой матрицы."""
    from db.seeds.scoring_matrices import _MATRICES_V3
    for m in _MATRICES_V3:
        expected = sum(
            v["weight"] * 2
            for k, v in m["criteria"].items()
            if not k.startswith("_") and isinstance(v, dict) and "weight" in v
        )
        assert m["max_score"] == expected, \
            f"{m['name']}: max_score={m['max_score']}, calculated={expected}"


def test_count_15_matrices():
    """Ровно 15 матриц v3.0."""
    from db.seeds.scoring_matrices import _MATRICES_V3
    assert len(_MATRICES_V3) == 15


# ── Тесты classify_role ────────────────────────────────────────────────────────

def test_classify_role_base_tshirt():
    from services.scoring import classify_role
    assert classify_role("футболка", "белый") == "base"


def test_classify_role_base_jeans():
    from services.scoring import classify_role
    assert classify_role("джинсы", "тёмно-синий") == "base"


def test_classify_role_accent_red_sweater():
    from services.scoring import classify_role
    assert classify_role("свитер", "красный") == "accent"


def test_classify_role_accent_leopard():
    from services.scoring import classify_role
    assert classify_role("юбка", "леопардовый") == "accent"


def test_classify_role_statement_dress():
    from services.scoring import classify_role
    assert classify_role("вечернее платье", "чёрный") == "statement"


def test_classify_role_statement_leather():
    from services.scoring import classify_role
    assert classify_role("кожаная куртка", "коричневый") == "statement"


def test_classify_role_basic_bright_color_is_accent():
    """Белая футболка — base, но яркая (красная) — accent."""
    from services.scoring import classify_role
    assert classify_role("футболка", "красный") == "accent"


# ── Тесты get_wardrobe_balance_insight ────────────────────────────────────────

def test_wardrobe_balance_too_many_accents():
    from services.scoring import get_wardrobe_balance_insight
    items = [FakeItem(role="accent")] * 8 + [FakeItem(role="base")] * 2
    insight = get_wardrobe_balance_insight(items)
    assert insight is not None
    assert "базовых" in insight.lower() or "нейтральных" in insight.lower()


def test_wardrobe_balance_too_few_bases():
    from services.scoring import get_wardrobe_balance_insight
    items = [FakeItem(role="accent")] * 7 + [FakeItem(role="base")] * 2 + [FakeItem(role="statement")] * 1
    insight = get_wardrobe_balance_insight(items)
    assert insight is not None


def test_wardrobe_balance_ok():
    from services.scoring import get_wardrobe_balance_insight
    items = (
        [FakeItem(role="base")] * 5 +
        [FakeItem(role="accent")] * 4 +
        [FakeItem(role="statement")] * 1
    )
    insight = get_wardrobe_balance_insight(items)
    assert insight is None


def test_wardrobe_balance_small_wardrobe():
    from services.scoring import get_wardrobe_balance_insight
    items = [FakeItem(role="base")] * 3
    insight = get_wardrobe_balance_insight(items)
    assert insight is None  # слишком мало для анализа


def test_wardrobe_balance_no_roles():
    from services.scoring import get_wardrobe_balance_insight
    items = [FakeItem(role=None)] * 15
    insight = get_wardrobe_balance_insight(items)
    assert insight is None  # нет данных о ролях


# ── Тесты комментариев (мок Haiku) ────────────────────────────────────────────
# Используем asyncio.run() вместо @pytest.mark.asyncio чтобы избежать
# конфликта с session-scoped event_loop из conftest.py.

def test_generate_item_comment_returns_string():
    import asyncio
    from services.scoring_comment import generate_item_comment
    pool = MockAnthropicPool(response_text="Отличная базовая вещь!")
    comment = asyncio.run(generate_item_comment(
        pool, "футболка", "белый", 8.0, "base", "Лето", True, "3 синих топа", None, None, None, ""
    ))
    assert isinstance(comment, str)
    assert len(comment) > 5
    assert "8.0" not in comment  # цифра не должна просочиться


def test_generate_item_comment_no_numeric_score():
    """Комментарий не содержит числа скора."""
    import asyncio
    from services.scoring_comment import generate_item_comment
    pool = MockAnthropicPool(response_text="Красивая вещь!")
    comment = asyncio.run(generate_item_comment(
        pool, "джинсы", "синий", 6.5, "base", "Зима", False, "", None, None, None, ""
    ))
    assert "6.5" not in comment
    assert "/10" not in comment


def test_generate_outfit_comment_wow():
    import asyncio
    from services.scoring_comment import generate_outfit_comment
    pool = MockAnthropicPool(response_text="✨ Отличный образ!")
    comment = asyncio.run(generate_outfit_comment(
        pool, ["свитер розовый", "джинсы синие"], "+10°C", "садик",
        9.0, True, "Алиса", "girl", 4, "", ["WOW!"]
    ))
    assert isinstance(comment, str)


def test_generate_outfit_comment_fallback_on_error():
    """При ошибке API возвращается fallback-строка, не исключение."""
    import asyncio
    from services.scoring_comment import generate_outfit_comment

    class FailPool:
        async def create_message(self, **kwargs):
            raise RuntimeError("API недоступен")

    comment = asyncio.run(generate_outfit_comment(
        FailPool(), ["куртка", "свитер"], "+5°C", "прогулка",
        7.0, False, None, None, None, "", []
    ))
    assert isinstance(comment, str)
    assert len(comment) > 0
