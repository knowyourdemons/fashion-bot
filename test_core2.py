"""
Fashion Bot — дополнительные тесты.
Покрывают: _get_temp_regime, score_outfit + WOW, ScoringService.score_item, CircuitBreaker.

Запуск:
    docker exec docker-app-1 python -m pytest /app/tests/test_core2.py -v
"""
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class FakeMatrix:
    name: str = "3-7"
    max_score: int = 22
    criteria: dict = field(default_factory=lambda: {
        "safety":           2,
        "practicality":     2,
        "durability":       2,
        "age_authenticity": 2,
        "ease_of_care":     2,
        "colortype":        2,
        "comfort":          2,
        "versatility":      2,
        "condition":        2,
        "size_fit_score":   2,
        "seasonality":      2,
    })
    version: str = "v2.0"
    is_active: bool = True


def make_redis_mock(**overrides) -> AsyncMock:
    """Создаёт AsyncMock Redis с нужными методами."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.incr = AsyncMock(return_value=1)
    redis.delete = AsyncMock(return_value=1)
    redis.pipeline = MagicMock()
    pipe = AsyncMock()
    pipe.incr = AsyncMock()
    pipe.expire = AsyncMock()
    pipe.execute = AsyncMock(return_value=[1, True])
    redis.pipeline.return_value = pipe
    for k, v in overrides.items():
        setattr(redis, k, v)
    return redis


# ═══════════════════════════════════════════════════════════════════════
# 1. _get_temp_regime — граничные значения
# ═══════════════════════════════════════════════════════════════════════

class TestGetTempRegime:
    def setup_method(self):
        from worker.tasks.morning_brief import _get_temp_regime
        self.fn = _get_temp_regime

    # Центр диапазонов
    def test_heat(self):
        assert self.fn(30) == "жара"

    def test_warm(self):
        assert self.fn(20) == "тепло"

    def test_cool(self):
        assert self.fn(12) == "прохладно"

    def test_cold(self):
        assert self.fn(7) == "холодно"

    def test_frost(self):
        assert self.fn(3) == "мороз"

    def test_hard_frost(self):
        assert self.fn(-10) == "сильный_мороз"

    # Граничные значения (boundary)
    def test_boundary_25_is_warm_not_heat(self):
        assert self.fn(25) == "тепло"   # > 25 → жара, = 25 → тепло

    def test_boundary_26_is_heat(self):
        assert self.fn(26) == "жара"

    def test_boundary_15_is_cool_not_warm(self):
        assert self.fn(15) == "прохладно"   # > 15 → тепло, = 15 → прохладно

    def test_boundary_16_is_warm(self):
        assert self.fn(16) == "тепло"

    def test_boundary_10_is_cold_not_cool(self):
        assert self.fn(10) == "холодно"

    def test_boundary_11_is_cool(self):
        assert self.fn(11) == "прохладно"

    def test_boundary_5_is_frost_not_cold(self):
        assert self.fn(5) == "мороз"

    def test_boundary_6_is_cold(self):
        assert self.fn(6) == "холодно"

    def test_boundary_0_is_hard_frost(self):
        assert self.fn(0) == "сильный_мороз"   # > 0 → мороз, = 0 → сильный_мороз

    def test_boundary_1_is_frost(self):
        assert self.fn(1) == "мороз"

    def test_negative_is_hard_frost(self):
        assert self.fn(-30) == "сильный_мороз"


# ═══════════════════════════════════════════════════════════════════════
# 2. score_outfit + WOW детектор
# ═══════════════════════════════════════════════════════════════════════

class TestScoreOutfit:
    def setup_method(self):
        from services.scoring import ScoringService
        session = AsyncMock()
        redis = make_redis_mock()
        self.svc = ScoringService(session, redis)

    # ── Детский образ ──────────────────────────────────────────────────

    def test_child_perfect_score(self):
        """Все критерии максимум → 10.0."""
        scores = {
            "color_harmony": 2,
            "practicality_outfit": 2,
            "age_appropriateness": 2,
            "weather_fit": 2,
            "style_unity": 1,
            "variety": 1,
        }
        score, breakdown, is_wow = self.svc.score_outfit(scores, is_child=True)
        assert score == Decimal("10.00")
        assert is_wow is False  # дети никогда не WOW

    def test_child_zero_score(self):
        """Все нули → 0.0."""
        score, _, _ = self.svc.score_outfit({}, is_child=True)
        assert score == Decimal("0.00")

    def test_child_never_wow(self):
        """WOW для детей всегда False."""
        scores = {k: 99 for k in ["color_harmony", "practicality_outfit",
                                   "age_appropriateness", "weather_fit",
                                   "style_unity", "variety"]}
        _, _, is_wow = self.svc.score_outfit(scores, is_child=True)
        assert is_wow is False

    def test_child_score_clamps_values(self):
        """Значения выше максимума зажимаются."""
        scores = {"color_harmony": 99, "practicality_outfit": 99,
                  "age_appropriateness": 99, "weather_fit": 99,
                  "style_unity": 99, "variety": 99}
        score, _, _ = self.svc.score_outfit(scores, is_child=True)
        assert score == Decimal("10.00")

    # ── Взрослый образ ─────────────────────────────────────────────────

    def test_adult_zero_score(self):
        """Все нули → 0.0 (без accessory_bonus)."""
        score, breakdown, is_wow = self.svc.score_outfit({}, is_child=False)
        assert score == Decimal("0.00")
        assert is_wow is False

    def test_adult_accessory_bonus_positive(self):
        """Accessory bonus +2 увеличивает скор."""
        score_without, _, _ = self.svc.score_outfit({}, is_child=False)
        score_with, _, _ = self.svc.score_outfit({"accessory_bonus": 2}, is_child=False)
        assert score_with > score_without

    def test_adult_accessory_bonus_negative(self):
        """Accessory bonus -1 уменьшает скор."""
        score_without, _, _ = self.svc.score_outfit({}, is_child=False)
        score_with, breakdown, _ = self.svc.score_outfit({"accessory_bonus": -1}, is_child=False)
        assert breakdown["accessory_bonus"] == -1

    def test_adult_accessory_bonus_clamped(self):
        """Accessory bonus зажимается в -1..+2."""
        _, breakdown, _ = self.svc.score_outfit({"accessory_bonus": 99}, is_child=False)
        assert breakdown["accessory_bonus"] == 2

        _, breakdown2, _ = self.svc.score_outfit({"accessory_bonus": -99}, is_child=False)
        assert breakdown2["accessory_bonus"] == -1

    def test_adult_breakdown_has_group_totals(self):
        """Breakdown содержит _technical_total, _aesthetic_total, _personal_total."""
        _, breakdown, _ = self.svc.score_outfit({}, is_child=False)
        assert "_technical_total" in breakdown
        assert "_aesthetic_total" in breakdown
        assert "_personal_total" in breakdown
        assert "_total" in breakdown

    # ── WOW детектор ──────────────────────────────────────────────────

    def test_wow_requires_both_criteria(self):
        """WOW только когда transformation>=3 И unexpected_combination>=2."""
        _, _, is_wow = self.svc.score_outfit(
            {"transformation": 3, "unexpected_combination": 2}, is_child=False
        )
        assert is_wow is True

    def test_wow_false_if_only_transformation(self):
        """Только transformation>=3 — не WOW."""
        _, _, is_wow = self.svc.score_outfit(
            {"transformation": 3, "unexpected_combination": 1}, is_child=False
        )
        assert is_wow is False

    def test_wow_false_if_only_unexpected(self):
        """Только unexpected_combination>=2 — не WOW."""
        _, _, is_wow = self.svc.score_outfit(
            {"transformation": 2, "unexpected_combination": 2}, is_child=False
        )
        assert is_wow is False

    def test_wow_false_by_default(self):
        """Без критериев — не WOW."""
        _, _, is_wow = self.svc.score_outfit({}, is_child=False)
        assert is_wow is False


# ═══════════════════════════════════════════════════════════════════════
# 3. ScoringService.score_item — структура breakdown
# ═══════════════════════════════════════════════════════════════════════

class TestScoringServiceScoreItem:
    def setup_method(self):
        from services.scoring import ScoringService
        session = AsyncMock()
        redis = make_redis_mock()
        self.svc = ScoringService(session, redis)
        self.matrix = FakeMatrix()

    def test_returns_decimal_and_dict(self):
        """Возвращает (Decimal, dict)."""
        score, breakdown = self.svc.score_item({}, self.matrix)
        assert isinstance(score, Decimal)
        assert isinstance(breakdown, dict)

    def test_breakdown_has_meta_keys(self):
        """Breakdown содержит _total, _max, _normalized."""
        _, breakdown = self.svc.score_item({}, self.matrix)
        assert "_total" in breakdown
        assert "_max" in breakdown
        assert "_normalized" in breakdown

    def test_breakdown_per_criterion_structure(self):
        """Каждый критерий имеет given и max."""
        scores = {"safety": 2, "practicality": 1}
        _, breakdown = self.svc.score_item(scores, self.matrix)
        assert breakdown["safety"] == {"given": 2, "max": 2}
        assert breakdown["practicality"] == {"given": 1, "max": 2}

    def test_missing_criterion_defaults_to_zero(self):
        """Отсутствующий критерий = 0 (в отличие от calc_item_score где = 1)."""
        _, breakdown = self.svc.score_item({}, self.matrix)
        assert breakdown["safety"]["given"] == 0

    def test_normalized_matches_manual_calc(self):
        """normalized = total / max_score * 10."""
        scores = {"safety": 2}  # total = 2, max = 22
        score, breakdown = self.svc.score_item(scores, self.matrix)
        expected = round(Decimal(2) / Decimal(22) * 10, 2)
        assert score == expected
        assert Decimal(str(breakdown["_normalized"])) == expected

    def test_clamping_above_max(self):
        """Значение выше max_weight зажимается до max_weight."""
        scores = {"safety": 99}
        _, breakdown = self.svc.score_item(scores, self.matrix)
        assert breakdown["safety"]["given"] == 2  # max для safety = 2

    def test_clamping_below_zero(self):
        """Отрицательное значение зажимается до 0."""
        scores = {"safety": -5}
        _, breakdown = self.svc.score_item(scores, self.matrix)
        assert breakdown["safety"]["given"] == 0

    def test_perfect_score_is_ten(self):
        """Все критерии на максимум → 10.0."""
        scores = {k: 99 for k in self.matrix.criteria}
        score, _ = self.svc.score_item(scores, self.matrix)
        assert score == Decimal("10.00")

    def test_total_equals_sum_of_given(self):
        """_total = сумма всех given значений."""
        scores = {"safety": 2, "practicality": 1, "durability": 2}
        _, breakdown = self.svc.score_item(scores, self.matrix)
        given_sum = sum(
            v["given"] for k, v in breakdown.items()
            if isinstance(v, dict) and "given" in v
        )
        assert breakdown["_total"] == given_sum


# ═══════════════════════════════════════════════════════════════════════
# 4. CircuitBreaker
# ═══════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    def setup_method(self):
        from core.circuit_breaker import CircuitBreaker, CBState
        self.CBState = CBState
        self.redis = make_redis_mock()
        self.cb = CircuitBreaker(self.redis, "test_service", failure_threshold=3, recovery_timeout=60)

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        """По умолчанию circuit = closed."""
        self.redis.get = AsyncMock(return_value=None)
        state = await self.cb.get_state()
        assert state == self.CBState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call_passes_through(self):
        """Успешный вызов возвращает результат функции."""
        self.redis.get = AsyncMock(return_value=None)
        self.redis.delete = AsyncMock()
        self.redis.set = AsyncMock()

        async def ok_func():
            return "result"

        result = await self.cb.call(ok_func)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_open_circuit_raises(self):
        """Открытый circuit вызывает CircuitBreakerOpenError."""
        from exceptions import CircuitBreakerOpenError
        # Circuit открыт, последняя ошибка только что
        self.redis.get = AsyncMock(side_effect=[
            b"open",       # get_state → open
            str(time.time()).encode(),  # last_failure → только что
        ])

        async def func():
            pass

        with pytest.raises(CircuitBreakerOpenError):
            await self.cb.call(func)

    @pytest.mark.asyncio
    async def test_open_circuit_transitions_to_half_open_after_timeout(self):
        """После recovery_timeout circuit переходит в half_open."""
        old_time = str(time.time() - 120).encode()  # 2 минуты назад > recovery_timeout=60
        self.redis.get = AsyncMock(side_effect=[
            b"open",   # get_state → open
            old_time,  # last_failure → давно
        ])
        self.redis.set = AsyncMock()
        self.redis.delete = AsyncMock()

        async def ok_func():
            return "ok"

        result = await self.cb.call(ok_func)
        assert result == "ok"
        # Должен был вызвать set с half_open
        calls = [str(c) for c in self.redis.set.call_args_list]
        assert any("half_open" in c for c in calls)

    @pytest.mark.asyncio
    async def test_failure_increments_counter(self):
        """Ошибка инкрементирует счётчик failures."""
        self.redis.get = AsyncMock(return_value=None)  # state = closed
        self.redis.incr = AsyncMock(return_value=1)
        self.redis.set = AsyncMock()

        async def bad_func():
            raise ValueError("ошибка")

        with pytest.raises(ValueError):
            await self.cb.call(bad_func)

        self.redis.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        """После failure_threshold ошибок circuit открывается."""
        self.redis.get = AsyncMock(return_value=None)
        self.redis.incr = AsyncMock(return_value=3)  # = failure_threshold
        self.redis.set = AsyncMock()

        async def bad_func():
            raise ValueError("ошибка")

        with pytest.raises(ValueError):
            await self.cb.call(bad_func)

        # Должен вызвать set с "open"
        calls = [str(c) for c in self.redis.set.call_args_list]
        assert any("open" in c for c in calls)

    @pytest.mark.asyncio
    async def test_success_resets_to_closed(self):
        """Успешный вызов сбрасывает circuit в closed."""
        self.redis.get = AsyncMock(return_value=None)
        self.redis.delete = AsyncMock()
        self.redis.set = AsyncMock()

        async def ok_func():
            return 42

        await self.cb.call(ok_func)

        self.redis.delete.assert_called()  # failures удалены
        calls = [str(c) for c in self.redis.set.call_args_list]
        assert any("closed" in c for c in calls)

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_error_not_counted_as_failure(self):
        """CircuitBreakerOpenError не инкрементирует счётчик failures."""
        from exceptions import CircuitBreakerOpenError
        self.redis.get = AsyncMock(return_value=None)
        self.redis.incr = AsyncMock(return_value=0)

        async def raises_cb_error():
            raise CircuitBreakerOpenError("уже открыт")

        with pytest.raises(CircuitBreakerOpenError):
            await self.cb.call(raises_cb_error)

        # incr не должен вызываться для CircuitBreakerOpenError
        self.redis.incr.assert_not_called()
