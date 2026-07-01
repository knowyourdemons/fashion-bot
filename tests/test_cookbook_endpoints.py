"""E2E/contract-тесты кукбук-эндпоинтов и инвариантов фронта.

Закрывают классы багов, которые находил whole-product аудит:
- /import по URL: контракт Form vs JSON (эндпоинт читает Form — фронт обязан слать multipart).
- Рассинхрон ключей localStorage: init-ключ Store должен совпадать с write-ключом (cb_<key>).
- Гардрейл аллергенов: AI-вариант не должен содержать исключённый аллерген.
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

APP_JS = Path(__file__).resolve().parent.parent / "landing" / "js" / "app.js"


def _make_app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient  # внутри функции — иначе конфликт метакласса с моком httpx
    from api.routes.cookbook import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/cookbook")
    return app, TestClient


class TestImportContract:
    def test_import_url_accepts_multipart_form(self):
        """POST /import с url в multipart-form → 200 и рецепт (регрессия Form-vs-JSON бага)."""
        app, TestClient = _make_app()
        canned = {"title": "Борщ", "ingredients": [{"name": "свёкла"}], "steps": []}
        with patch("api.routes.cookbook._authorize", new=AsyncMock(return_value=None)), \
             patch("api.routes.cookbook._import_from_url", new=AsyncMock(return_value=canned)):
            with TestClient(app) as client:
                resp = client.post("/api/v1/cookbook/import", data={"url": "https://example.com/recipe"})
        assert resp.status_code == 200
        assert resp.json()["recipe"]["title"] == "Борщ"

    def test_import_without_url_or_photo_is_400(self):
        app, TestClient = _make_app()
        with patch("api.routes.cookbook._authorize", new=AsyncMock(return_value=None)):
            with TestClient(app) as client:
                resp = client.post("/api/v1/cookbook/import", data={})
        assert resp.status_code == 400


class TestStoreKeyInvariant:
    def test_init_key_matches_write_key(self):
        """Каждый ключ Store инициализируется из cb_<key> — совпадает с тем, куда пишет save().

        Ловит баг userRecipes (init читал cb_user_recipes, save писал cb_userRecipes → потеря данных).
        """
        src = APP_JS.read_text(encoding="utf-8")
        m = re.search(r"const Store = \{(.+?)\n    save\(key\)", src, re.S)
        assert m, "не найден блок Store в app.js"
        block = m.group(1)
        pairs = re.findall(r"(\w+):\s*LS\.get\(\"cb_(\w+)\"", block)
        assert pairs, "не найдены init-ключи Store"
        mismatched = [(k, suffix) for k, suffix in pairs if k != suffix]
        assert not mismatched, f"init-ключ != cb_<key>: {mismatched}"


class TestAllergenGuard:
    def test_hits_detect_by_ingredient_name(self):
        from api.routes.cookbook import _recipe_allergen_hits
        r = {"allergens": [], "ingredients": [{"name": "пшеничная мука"}, {"name": "сыр"}]}
        assert _recipe_allergen_hits(r, {"глютен", "молоко"}) == {"глютен", "молоко"}
        assert _recipe_allergen_hits(r, {"соя"}) == set()

    def test_hits_detect_by_declared_allergen(self):
        from api.routes.cookbook import _recipe_allergen_hits
        r = {"allergens": ["Молоко"], "ingredients": [{"name": "вода"}]}
        assert "молоко" in _recipe_allergen_hits(r, {"молоко"})

    @pytest.mark.asyncio
    async def test_cf_recipe_rejects_forbidden_allergen(self):
        """Если модель упорно возвращает вариант с запрещённым аллергеном → 422 (жёсткий гардрейл)."""
        from fastapi import HTTPException
        from api.routes import cookbook
        bad = '{"title":"Блины","ingredients":[{"name":"пшеничная мука"}],"steps":[]}'
        with patch("api.routes.cookbook._cf_chat", new=AsyncMock(return_value=bad)):
            with pytest.raises(HTTPException) as ei:
                await cookbook._cf_recipe(cookbook.GENERATE_SYSTEM, "x", forbidden=["глютен"])
        assert ei.value.status_code == 422
