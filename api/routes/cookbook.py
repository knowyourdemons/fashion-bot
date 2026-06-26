"""
Поваренная книга — тонкий бэкенд для AI-ассистента и импорта рецептов.

Переиспользует инфраструктуру фешн-бота:
- AnthropicPool (core/anthropic_client) — Vision (sonnet) + чат (haiku)
- Redis (core/redis) — дневной cost guard на Vision-вызовы

Авторизация: общий секрет (settings.cookbook_secret) в заголовке X-Cookbook-Secret.
Сайт личный, пользовательских аккаунтов нет — секрет защищает от утечки API-ключа.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from config import settings
from core.anthropic_client import get_anthropic_pool

logger = structlog.get_logger()
router = APIRouter()

SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"

ASSISTANT_SYSTEM = (
    "Ты — кулинарный ассистент в личной поваренной книге. Помогаешь в магазине и у плиты: "
    "по фото товара говоришь, тот ли это ингредиент, и чем его заменить; отвечаешь на вопросы "
    "по рецепту и готовке коротко и по делу, на русском.\n"
    "Если предлагаешь замену ингредиента — заполни поле substitution.\n"
    'Отвечай ТОЛЬКО валидным JSON без markdown: '
    '{"reply": "<текст ответа>", "substitution": null | '
    '{"original": "<что заменяем>", "replacement": "<на что>", "note": "<пропорция/нюанс>"}}'
)

IMPORT_SYSTEM = (
    "Извлеки рецепт со страницы/фото в строгий JSON без markdown:\n"
    '{"title": "", "cuisine": "", "category": "Основное", "time": <минуты int>, '
    '"baseServings": <int>, "forKid": false, "tags": [], '
    '"ingredients": [{"name": "", "qty": <число|null>, "unit": "", "group": "Прочее", "staple": false}], '
    '"steps": [{"text": "", "timer": <секунды int|null>}]}\n'
    "category — одно из: Завтрак|Суп|Основное|Гарнир|Салат|Десерт|Выпечка|Закуска|Напиток. "
    "Количества разнеси в qty/unit где возможно. Текст на языке оригинала рецепта."
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _check_secret(secret: str | None) -> None:
    expected = settings.cookbook_secret
    if not expected:
        raise HTTPException(status_code=503, detail="Cookbook assistant не настроен (нет cookbook_secret)")
    if not secret or secret != expected:
        raise HTTPException(status_code=401, detail="Неверный код доступа")


async def _vision_guard(n_images: int) -> None:
    """Дневной лимит Vision-вызовов (cost guard). Считает только вызовы с фото."""
    if n_images <= 0:
        return
    try:
        from core.redis import get_redis
        redis = get_redis()
        key = f"cb_vision:{date.today().isoformat()}"
        used = await redis.incrby(key, n_images)
        if used == n_images:
            await redis.expire(key, 2 * 86400)
        if used > settings.cookbook_vision_daily_cap:
            raise HTTPException(status_code=429, detail="Дневной лимит распознаваний исчерпан")
    except HTTPException:
        raise
    except Exception as e:  # Redis недоступен — не блокируем, просто логируем
        logger.warning("cookbook.vision_guard.error", error=str(e))


def _image_block(raw: bytes, media_type: str = "image/jpeg") -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type or "image/jpeg",
            "data": base64.standard_b64encode(raw).decode(),
        },
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    """Достаёт первый JSON-объект из текста (на случай обёртки markdown/мусора)."""
    if not text:
        return None
    text = text.strip()
    # срезаем ```json ... ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _resp_text(response: Any) -> str:
    try:
        return response.content[0].text if response.content else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# POST /assistant — чат с фото + предложения замен
# ---------------------------------------------------------------------------
@router.post("/assistant")
async def assistant(
    message: str = Form(""),
    context: str = Form("{}"),
    history: str = Form("[]"),
    photos: list[UploadFile] = File(default=[]),
    x_cookbook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_secret(x_cookbook_secret)

    photo_bytes: list[tuple[bytes, str]] = []
    for up in photos or []:
        data = await up.read()
        if data:
            photo_bytes.append((data, up.content_type or "image/jpeg"))
    await _vision_guard(len(photo_bytes))

    try:
        ctx = json.loads(context) if context else {}
    except Exception:
        ctx = {}
    try:
        hist = json.loads(history) if history else []
    except Exception:
        hist = []

    # Контекст рецепта/ингредиента в текст для модели
    ctx_lines: list[str] = []
    recipe = ctx.get("recipe") if isinstance(ctx, dict) else None
    if recipe:
        ings = ", ".join(i.get("name", "") for i in (recipe.get("ingredients") or [])[:20])
        ctx_lines.append(f"Рецепт: {recipe.get('title', '')}. Ингредиенты: {ings}.")
    ingredient = ctx.get("ingredient") if isinstance(ctx, dict) else None
    if ingredient:
        ctx_lines.append(f"Вопрос про ингредиент: {ingredient.get('name', '')}.")

    # Сборка messages: история (только текст) + текущее сообщение (+ фото)
    messages: list[dict[str, Any]] = []
    for h in hist[-10:]:
        role = "assistant" if h.get("role") == "bot" else "user"
        txt = h.get("text") or ""
        if txt:
            messages.append({"role": role, "content": txt})

    content: list[dict[str, Any]] = []
    for raw, mt in photo_bytes:
        content.append(_image_block(raw, mt))
    user_text = message or "Что это? Подходит ли для рецепта?"
    if ctx_lines:
        user_text = "\n".join(ctx_lines) + "\n\n" + user_text
    content.append({"type": "text", "text": user_text})
    messages.append({"role": "user", "content": content})

    model = SONNET if photo_bytes else HAIKU
    pool = get_anthropic_pool()
    try:
        response = await pool.create_message(
            model=model,
            max_tokens=700,
            system=ASSISTANT_SYSTEM,
            messages=messages,
        )
    except Exception as e:
        logger.error("cookbook.assistant.error", error=str(e))
        raise HTTPException(status_code=502, detail="Ассистент временно недоступен")

    raw_text = _resp_text(response)
    parsed = _extract_json(raw_text)
    if parsed and isinstance(parsed, dict) and "reply" in parsed:
        sub = parsed.get("substitution")
        if not (isinstance(sub, dict) and sub.get("original") and sub.get("replacement")):
            sub = None
        return {"reply": str(parsed.get("reply", "")).strip(), "substitution": sub}
    # модель не уложилась в JSON — отдаём как есть
    return {"reply": raw_text.strip() or "(пустой ответ)", "substitution": None}


# ---------------------------------------------------------------------------
# POST /import — по ссылке (schema.org JSON-LD) или фото (OCR Vision)
# ---------------------------------------------------------------------------
@router.post("/import")
async def import_recipe(
    url: str | None = Form(default=None),
    photo: UploadFile | None = File(default=None),
    x_cookbook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_secret(x_cookbook_secret)

    # Вариант JSON-body {url: ...} (если прислали application/json — Form будет пуст)
    if url:
        recipe = await _import_from_url(url)
        return {"recipe": recipe}

    if photo is not None:
        data = await photo.read()
        if not data:
            raise HTTPException(status_code=400, detail="Пустое фото")
        await _vision_guard(1)
        recipe = await _import_from_photo(data, photo.content_type or "image/jpeg")
        return {"recipe": recipe}

    raise HTTPException(status_code=400, detail="Нужен url или photo")


async def _import_from_url(url: str) -> dict[str, Any]:
    import httpx

    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="Некорректный URL")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 CookbookBot"}) as client:
            resp = await client.get(url)
            html = resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Не удалось загрузить страницу: {e}")

    node = _find_recipe_jsonld(html)
    if not node:
        raise HTTPException(status_code=422, detail="На странице не найдена разметка рецепта (schema.org)")
    return _schema_to_recipe(node)


def _find_recipe_jsonld(html: str) -> dict[str, Any] | None:
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        block = m.group(1).strip()
        try:
            data = json.loads(block)
        except Exception:
            continue
        for node in _iter_jsonld_nodes(data):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(x).lower() == "recipe" for x in types):
                return node
    return None


def _iter_jsonld_nodes(data: Any):
    if isinstance(data, list):
        for x in data:
            yield from _iter_jsonld_nodes(x)
    elif isinstance(data, dict):
        if "@graph" in data and isinstance(data["@graph"], list):
            for x in data["@graph"]:
                yield from _iter_jsonld_nodes(x)
        yield data


def _schema_to_recipe(node: dict[str, Any]) -> dict[str, Any]:
    def _first(v):
        return v[0] if isinstance(v, list) and v else v

    title = _first(node.get("name")) or "Импортированный рецепт"

    ingredients = []
    for raw in node.get("recipeIngredient") or node.get("ingredients") or []:
        name = str(raw).strip()
        if name:
            ingredients.append({"name": name, "qty": None, "unit": "", "group": "Прочее", "staple": False})

    steps = []
    instr = node.get("recipeInstructions")
    if isinstance(instr, str):
        for part in re.split(r"\n+|\.\s+", instr):
            part = part.strip()
            if part:
                steps.append({"text": part})
    elif isinstance(instr, list):
        for st in instr:
            if isinstance(st, str):
                txt = st.strip()
            elif isinstance(st, dict):
                # HowToStep / HowToSection
                if st.get("@type") == "HowToSection" and isinstance(st.get("itemListElement"), list):
                    for sub in st["itemListElement"]:
                        t = (sub.get("text") or sub.get("name") or "").strip() if isinstance(sub, dict) else str(sub).strip()
                        if t:
                            steps.append({"text": t})
                    continue
                txt = (st.get("text") or st.get("name") or "").strip()
            else:
                txt = ""
            if txt:
                steps.append({"text": txt})

    time_min = _parse_iso_duration(node.get("totalTime") or node.get("cookTime") or node.get("prepTime"))
    servings = _parse_servings(node.get("recipeYield"))
    cuisine = _first(node.get("recipeCuisine")) or ""
    category = _first(node.get("recipeCategory")) or "Основное"

    return {
        "title": str(title).strip(),
        "cuisine": str(cuisine).strip(),
        "category": str(category).strip() or "Основное",
        "time": time_min or 30,
        "baseServings": servings or 2,
        "forKid": False,
        "tags": [],
        "ingredients": ingredients,
        "steps": steps,
    }


def _parse_iso_duration(val: Any) -> int | None:
    """ISO 8601 (PT1H30M) → минуты."""
    if not val or not isinstance(val, str):
        return None
    m = re.match(r"P(?:T)?(?:(\d+)H)?(?:(\d+)M)?", val)
    if not m:
        return None
    hours = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    total = hours * 60 + mins
    return total or None


def _parse_servings(val: Any) -> int | None:
    if isinstance(val, list) and val:
        val = val[0]
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        m = re.search(r"\d+", val)
        if m:
            return int(m.group(0))
    return None


async def _import_from_photo(data: bytes, media_type: str) -> dict[str, Any]:
    pool = get_anthropic_pool()
    try:
        response = await pool.create_message(
            model=SONNET,
            max_tokens=1500,
            system=IMPORT_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    _image_block(data, media_type),
                    {"type": "text", "text": "Распознай рецепт с этого фото."},
                ],
            }],
        )
    except Exception as e:
        logger.error("cookbook.import_photo.error", error=str(e))
        raise HTTPException(status_code=502, detail="Распознавание недоступно")

    parsed = _extract_json(_resp_text(response))
    if not parsed:
        raise HTTPException(status_code=422, detail="Не удалось распознать рецепт")
    parsed.setdefault("ingredients", [])
    parsed.setdefault("steps", [])
    parsed.setdefault("category", "Основное")
    return parsed
