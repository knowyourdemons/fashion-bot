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
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile

from config import settings
from core.anthropic_client import get_anthropic_pool

SESSION_TTL = 30 * 86400  # 30 дней
TELEGRAM_AUTH_MAX_AGE = 86400  # подпись виджета не старше суток

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
def _allowed_ids() -> set[str]:
    return {x.strip() for x in (settings.cookbook_allowed_telegram_ids or "").split(",") if x.strip()}


async def _session_tg_id(token: str | None) -> str | None:
    """Возвращает telegram_id по валидной сессии или None."""
    if not token:
        return None
    try:
        from core.redis import get_redis
        redis = get_redis()
        tg_id = await redis.get(f"cb_session:{token}")
        if tg_id is None:
            return None
        return tg_id.decode() if isinstance(tg_id, bytes) else str(tg_id)
    except Exception as e:
        logger.warning("cookbook.session.lookup_error", error=str(e))
        return None


async def _authorize(session: str | None, secret: str | None) -> None:
    """Доступ к ассистенту/импорту: валидная Telegram-сессия ИЛИ общий секрет."""
    if await _session_tg_id(session):
        return
    expected = settings.cookbook_secret
    if expected and secret and hmac.compare_digest(secret, expected):
        return
    if not expected and not _allowed_ids():
        raise HTTPException(status_code=503, detail="Cookbook доступ не настроен")
    raise HTTPException(status_code=401, detail="Нужна авторизация (войдите через Telegram)")


def _verify_telegram(data: dict[str, Any]) -> str | None:
    """Проверяет подпись Telegram Login Widget. Возвращает telegram_id (str) или None."""
    recv_hash = data.get("hash")
    if not recv_hash or not settings.telegram_bot_token:
        return None
    pairs = {k: v for k, v in data.items() if k != "hash" and v is not None}
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    calc = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, str(recv_hash)):
        return None
    try:
        if time.time() - int(data.get("auth_date", 0)) > TELEGRAM_AUTH_MAX_AGE:
            return None
    except (ValueError, TypeError):
        return None
    return str(data.get("id"))


async def _issue_session(tg_id: str) -> str:
    token = secrets.token_urlsafe(32)
    from core.redis import get_redis
    redis = get_redis()
    await redis.setex(f"cb_session:{token}", SESSION_TTL, tg_id)
    return token


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
# Cloudflare Workers AI ($0 free tier): Llama 3.3 — текст, llava — vision
# ---------------------------------------------------------------------------
CF_TEXT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
CF_VISION_MODEL = "@cf/llava-1.5-7b-hf"
ASSISTANT_VISION_PROMPT = (
    "Ты — кулинарный ассистент. По фото товара/блюда коротко на русском скажи, что это, "
    "подходит ли к рецепту и чем заменить при необходимости."
)


async def _cf_run(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    acct = settings.cloudflare_account_id
    token = settings.cloudflare_api_token
    if not (acct and token):
        raise HTTPException(status_code=503, detail="Ассистент не настроен (нет CF Workers AI)")
    import httpx

    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload)
    except Exception as e:
        logger.error("cookbook.cf.request_error", model=model, error=str(e))
        raise HTTPException(status_code=502, detail="Ассистент временно недоступен")
    if r.status_code != 200:
        logger.error("cookbook.cf.http_error", model=model, status=r.status_code, body=r.text[:300])
        raise HTTPException(status_code=502, detail="Ассистент временно недоступен")
    data = r.json()
    if not data.get("success", True):
        logger.error("cookbook.cf.api_error", model=model, errors=str(data.get("errors"))[:300])
        raise HTTPException(status_code=502, detail="Ассистент временно недоступен")
    return data.get("result", {}) or {}


async def _cf_chat(messages: list[dict[str, Any]], system: str, max_tokens: int = 700) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    res = await _cf_run(CF_TEXT_MODEL, {"messages": msgs, "max_tokens": max_tokens})
    return (res.get("response") or "").strip()


async def _cf_vision(raw: bytes, prompt: str, max_tokens: int = 512) -> str:
    res = await _cf_run(CF_VISION_MODEL, {"image": list(raw), "prompt": prompt, "max_tokens": max_tokens})
    return (res.get("description") or res.get("response") or "").strip()


# ---------------------------------------------------------------------------
# GET /config — публичная конфигурация для фронта (виджет логина)
# ---------------------------------------------------------------------------
@router.get("/config")
async def config() -> dict[str, Any]:
    return {
        "botUsername": settings.cookbook_bot_username,
        "ssoEnabled": bool(settings.telegram_bot_token and _allowed_ids()),
    }


# ---------------------------------------------------------------------------
# POST /auth/telegram — вход через Telegram Login Widget
# ---------------------------------------------------------------------------
@router.post("/auth/telegram")
async def auth_telegram(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Ожидается JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Некорректные данные")

    tg_id = _verify_telegram(data)
    if not tg_id:
        raise HTTPException(status_code=401, detail="Подпись Telegram не подтверждена")

    allowed = _allowed_ids()
    if allowed and tg_id not in allowed:
        logger.warning("cookbook.auth.not_allowed", tg_id=tg_id)
        raise HTTPException(status_code=403, detail="Этому аккаунту вход не разрешён")

    token = await _issue_session(tg_id)
    name = data.get("first_name") or data.get("username") or "Повар"
    return {"token": token, "name": name}


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
    x_cookbook_session: str | None = Header(default=None),
) -> dict[str, Any]:
    await _authorize(x_cookbook_session, x_cookbook_secret)

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

    ctx_prefix = ("\n".join(ctx_lines) + "\n\n") if ctx_lines else ""
    user_text = message or "Что это? Подходит ли для рецепта?"

    # Фото → vision (llava): простой ответ, без JSON-substitution
    if photo_bytes:
        prompt = (ASSISTANT_VISION_PROMPT + "\n" + ctx_prefix + user_text).strip()
        reply = await _cf_vision(photo_bytes[0][0], prompt)
        return {"reply": reply or "(пустой ответ)", "substitution": None}

    # Текст → Llama 3.3 (история + контекст), JSON с возможной заменой
    messages: list[dict[str, Any]] = []
    for h in hist[-10:]:
        role = "assistant" if h.get("role") == "bot" else "user"
        txt = h.get("text") or ""
        if txt:
            messages.append({"role": role, "content": txt})
    messages.append({"role": "user", "content": ctx_prefix + user_text})

    raw_text = await _cf_chat(messages, ASSISTANT_SYSTEM, max_tokens=700)
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
    x_cookbook_session: str | None = Header(default=None),
) -> dict[str, Any]:
    await _authorize(x_cookbook_session, x_cookbook_secret)

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
