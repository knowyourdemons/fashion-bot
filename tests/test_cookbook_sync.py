"""Юнит-тесты синка кукбука: last-write-wins и набор синкаемых ключей."""
import pytest

from api.routes.cookbook import (
    SYNC_KEYS,
    _lww_action,
    _parse_ingredient_line,
    _require_tg_id,
)
from fastapi import HTTPException


class TestLwwAction:
    def test_insert_when_no_server_row(self):
        assert _lww_action(1000, None) == "write"

    def test_client_newer_overwrites(self):
        assert _lww_action(2000, 1000) == "write"

    def test_server_newer_returns_newer(self):
        assert _lww_action(1000, 2000) == "newer"

    def test_equal_rev_is_noop(self):
        assert _lww_action(1500, 1500) == "noop"

    def test_boundary_off_by_one(self):
        assert _lww_action(1001, 1000) == "write"
        assert _lww_action(999, 1000) == "newer"


class TestSyncKeys:
    def test_covers_frontend_store_keys(self):
        # Должны совпадать с ключами Store в landing/js/app.js
        assert SYNC_KEYS == {"shopping", "pantry", "memory", "userRecipes", "plan", "ingChecks", "profile"}

    def test_does_not_sync_auth_or_chat(self):
        for k in ("session_token", "secret", "assistant", "rev"):
            assert k not in SYNC_KEYS


class TestRequireTgId:
    @pytest.mark.asyncio
    async def test_no_session_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await _require_tg_id(None)
        assert exc.value.status_code == 401


class TestIngredientParser:
    def test_metric_qty_unit(self):
        assert _parse_ingredient_line("200 г муки") == (200, "г", "муки")

    def test_spoon_unit(self):
        assert _parse_ingredient_line("2 ст.л. сахара") == (2, "ст.л.", "сахара")

    def test_fraction_slash(self):
        qty, unit, name = _parse_ingredient_line("1/2 стакана молока")
        assert qty == 0.5 and unit == "стакана" and name == "молока"

    def test_unicode_fraction(self):
        qty, unit, name = _parse_ingredient_line("½ лимона")
        assert qty == 0.5 and name == "лимона"

    def test_decimal_comma(self):
        assert _parse_ingredient_line("1,5 кг картофеля") == (1.5, "кг", "картофеля")

    def test_no_quantity(self):
        assert _parse_ingredient_line("соль по вкусу") == (None, "", "соль по вкусу")

    def test_english_unit(self):
        assert _parse_ingredient_line("500 g flour") == (500, "g", "flour")

    def test_number_without_known_unit(self):
        # число есть, но следующее слово — не единица → оно часть названия
        qty, unit, name = _parse_ingredient_line("3 яйца")
        assert qty == 3 and unit == "" and name == "яйца"
