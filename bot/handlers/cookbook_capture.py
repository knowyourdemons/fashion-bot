"""Захват рецепта в кукбук через Telegram (ров: «переслал боту → рецепт в книге»).

Источники: /recipe <url>, /recipe в ответ на сообщение, пересланное фото страницы/поста,
пересланный текст со ссылкой. ТОЛЬКО для cookbook-allowed юзеров — обычные фото (гардероб)
фешн-бота не затрагиваются (ловим лишь forwarded + команду).

Сохраняет рецепт в CookbookState(key="userRecipes") → появится в SPA «Мои рецепты» после синка.
Импорт-пайплайн переиспользуется из api/routes/cookbook.py (алиасы import_recipe_link / import_recipe_photo).
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any

import structlog

from config import settings

logger = structlog.get_logger()
_URL_RE = re.compile(r"https?://\S+")


def cookbook_user_ids() -> set[str]:
    return {x.strip() for x in (settings.cookbook_allowed_telegram_ids or "").split(",") if x.strip()}


async def _save_recipe(tg_id: str, recipe: dict[str, Any]) -> None:
    """Добавляет рецепт в userRecipes юзера (append + bump rev под LWW-синк)."""
    from sqlalchemy import select
    from db.base import AsyncWriteSession
    from db.models.cookbook_state import CookbookState

    recipe.setdefault("id", "tg_" + uuid.uuid4().hex[:10])
    recipe.setdefault("category", "Основное")
    recipe.setdefault("steps", [])
    rev = int(time.time() * 1000)
    async with AsyncWriteSession() as session:
        row = (await session.execute(
            select(CookbookState).where(CookbookState.tg_id == str(tg_id), CookbookState.key == "userRecipes")
        )).scalar_one_or_none()
        lst = list(row.value) if row and isinstance(row.value, list) else []
        lst.append(recipe)
        if row is None:
            session.add(CookbookState(tg_id=str(tg_id), key="userRecipes", value=lst, rev=rev))
        else:
            row.value = lst
            row.rev = rev
        await session.commit()


async def _import_message(context, message) -> dict[str, Any] | None:
    """Определяет источник в сообщении и импортирует рецепт: фото → OCR, текст со ссылкой → импорт по ссылке."""
    from api.routes.cookbook import import_recipe_link, import_recipe_photo

    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        photo_id = message.document.file_id
    if photo_id:
        tg_file = await context.bot.get_file(photo_id)
        data = bytes(await tg_file.download_as_bytearray())
        return await import_recipe_photo(data, "image/jpeg")

    text = message.text or message.caption or ""
    m = _URL_RE.search(text)
    if m:
        return await import_recipe_link(m.group(0))
    return None


async def _run_capture(update, context, message, override_url: str | None = None) -> None:
    tg_id = str(update.effective_user.id)
    status = await update.effective_message.reply_text("📖 Распознаю рецепт…")
    try:
        if override_url:
            from api.routes.cookbook import import_recipe_link
            recipe = await import_recipe_link(override_url)
        else:
            recipe = await _import_message(context, message)
        if not recipe or not recipe.get("title"):
            await status.edit_text("Пришлите ссылку на рецепт, фото страницы книги или перешлите пост с рецептом.")
            return
        await _save_recipe(tg_id, recipe)
        await status.edit_text(f"✅ «{recipe['title']}» сохранён в вашу книгу — откройте приложение, раздел «Мои рецепты».")
    except Exception as e:
        logger.warning("cookbook_capture.failed", tg_id=tg_id, error=str(e))
        await status.edit_text("Не получилось распознать рецепт. Попробуйте другую ссылку или фото поближе.")


async def handle_recipe_command(update, context) -> None:
    """/recipe [url] — импортирует из URL в аргументе, из reply, или из самого сообщения."""
    if str(update.effective_user.id) not in cookbook_user_ids():
        return
    msg = update.effective_message
    args_text = " ".join(context.args) if getattr(context, "args", None) else ""
    url_m = _URL_RE.search(args_text)
    target = msg.reply_to_message or msg
    await _run_capture(update, context, target, override_url=(url_m.group(0) if url_m else None))


async def handle_forwarded_capture(update, context) -> None:
    """Пересланное сообщение от cookbook-юзера (фильтр уже гарантирует forwarded + фото/URL)."""
    await _run_capture(update, context, update.effective_message)
