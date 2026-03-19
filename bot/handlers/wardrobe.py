"""Wardrobe handlers."""
import asyncio
import base64
import io
import json
import time
import uuid

import sentry_sdk
import structlog
import sqlalchemy as sa
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import settings
from core.anthropic_client import get_anthropic_pool
from db.base import AsyncWriteSession, AsyncReadSession
from db.crud.wardrobe import create, get_owner_items
from db.models.user import User
from exceptions import FashionBotError, RateLimitError
from services.i18n.ru import t
from bot.handlers.menu import get_main_menu
from services.scoring import ScoringService, matrix_name_for_owner, calc_item_score
from services.usage import get_limit_exceeded_msg, get_usage_str
from core.permissions import get_effective_plan, get_limit
from services.vision import (
    _build_rate_prompt,
    _dedup_key,
    _item_label,
    _fix_bbox,
    _default_score,
    _crop_bbox,
    _check_crop_quality,
    _call_vision,
    _call_rate_vision,
    _color_similar,
    _RATE_SYSTEM_CHILD,
    _RATE_SYSTEM_ADULT,
)
from services.outfit_builder import (
    select_outfit,
    get_temp_regime,
    get_collage_params,
    build_outfit_slots,
    score_to_text,
    outfit_score_to_text,
    color_circle,
    warm_outfit_comment as _warm_outfit_comment,
    SEASONS,
)

logger = structlog.get_logger()


_VALID_CATEGORY_GROUPS = {
    "outerwear", "top", "bottom", "one_piece", "footwear",
    "accessory", "base_layer", "sportswear", "special",
    "home_beach", "pregnant_specific", "underwear",
}

_CATEGORY_LABELS = {
    "outerwear": "Верхняя одежда",
    "top": "Верх",
    "bottom": "Низ",
    "one_piece": "Комбинезон/платье",
    "footwear": "Обувь",
    "accessory": "Аксессуары",
    "base_layer": "Базовый слой",
    "sportswear": "Спортивная",
    "special": "Особый повод",
    "home_beach": "Дом/пляж",
    "pregnant_specific": "Для беременных",
    "underwear": "Нижнее бельё",
}


PAGE_SIZE = 20
OUTFIT_DAY_LIMIT_FREE = 2
OUTFIT_DAY_LIMIT_PREMIUM = 5


# ── Owner helpers ──────────────────────────────────────────────────────────

async def _get_owner(user, context) -> tuple:
    """Получить текущего владельца гардероба. Приоритет: Redis owner_mode → segment."""
    redis = context.bot_data.get("redis")
    if redis:
        try:
            mode = await redis.get(f"owner_mode:{user.id}")
            if mode:
                mode = mode if isinstance(mode, str) else mode.decode()
                if mode == "user":
                    return (user.id, "user")
                elif mode.startswith("child:"):
                    import uuid as _uuid
                    child_id = _uuid.UUID(mode[6:])
                    return (child_id, "child")
        except Exception:
            pass

    async with AsyncReadSession() as session:
        from db.crud.children import get_children
        children = await get_children(session, user.id)

    if user.segment in ("mom_girl", "mom_boy") and children:
        return (children[0].id, "child")
    return (user.id, "user")


async def _get_scoring_matrix(redis, user, owner_id: uuid.UUID, owner_type: str):
    """Возвращает ScoringMatrix для owner или None если Redis недоступен."""
    if not redis:
        return None
    try:
        child = None
        if owner_type == "child":
            from db.models.child import Child
            from sqlalchemy import select as _sel
            async with AsyncReadSession() as session:
                result = await session.execute(_sel(Child).where(Child.id == owner_id))
                child = result.scalar_one_or_none()
        name = matrix_name_for_owner(user, child)
        async with AsyncReadSession() as session:
            svc = ScoringService(session, redis)
            return await svc.get_matrix(name)
    except Exception as e:
        logger.warning("scoring_matrix.load_failed", error=str(e))
        return None


async def _load_existing_set(owner_id: uuid.UUID, owner_type: str = "user") -> set:
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)
    return {
        (
            (i.type or "").lower().strip(),
            (i.color or "").lower().strip(),
            i.category_group or "top",
        )
        for i in items
    }


# ── Brief trigger ──────────────────────────────────────────────────────────

async def _maybe_trigger_first_brief(user, owner_id, owner_type, message, context, redis) -> None:
    """Триггер первого брифа ровно на 5-й вещи. Работает для ВСЕХ планов."""
    if redis is None:
        return
    lock_key = f"lock:first_brief:{user.id}"
    acquired = await redis.set(lock_key, "1", ex=86400, nx=True)
    if not acquired:
        return
    try:
        from db.crud.wardrobe import get_owner_items_count
        async with AsyncReadSession() as session:
            wardrobe_count = await get_owner_items_count(session, owner_id, owner_type)
        if wardrobe_count < 5:
            await redis.delete(lock_key)
            remaining = 5 - wardrobe_count
            if remaining == 1:
                suffix = "вещь"
            elif remaining < 5:
                suffix = "вещи"
            else:
                suffix = "вещей"
            await message.reply_text(f"📸 Ещё {remaining} {suffix} — и я соберу первый образ!")
            return
        from core.queue import RedisQueue, QueuePriority
        queue = RedisQueue(redis)
        await queue.push(
            "generate_brief",
            {"user_id": str(user.id)},
            priority=QueuePriority.HIGH,
        )
        await message.reply_text(
            "✨ У тебя уже 5 вещей! Собираю первый образ — подожди пару секунд..."
        )
        logger.info("wardrobe.first_brief_triggered", user_id=str(user.id), count=wardrobe_count)
    except Exception as e:
        logger.warning("wardrobe.first_brief_trigger_failed", error=str(e))


async def _upload_crop(
    photo_bytes: bytes,
    bbox: dict | None,
    owner_id: uuid.UUID | None = None,
    redis=None,
) -> tuple[str | None, bool]:
    """Кропит по bbox → удаляет фон → загружает PNG в R2."""
    if not bbox:
        return None, True
    try:
        crop_bytes = _crop_bbox(photo_bytes, bbox)
        from services.image_processor import remove_background
        png_bytes = await remove_background(crop_bytes, redis=redis)
        good_crop = _check_crop_quality(png_bytes)
        if not good_crop:
            logger.warning("wardrobe.crop.low_quality", action="show_in_collage=False")
        is_png = png_bytes[:4] == b'\x89PNG'
        ext = "png" if is_png else "jpg"
        content_type = "image/png" if is_png else "image/jpeg"
        from services.storage.r2_storage import get_r2_storage
        r2 = get_r2_storage()
        filename = f"{uuid.uuid4()}.{ext}"
        key = await r2.upload_photo(
            png_bytes, filename,
            owner_id=str(owner_id) if owner_id else "",
            content_type=content_type,
        )
        url = r2.get_public_url(key) if settings.cloudflare_r2_cdn_url else key
        return url, good_crop
    except Exception as e:
        logger.warning("wardrobe.crop_upload_failed", error=str(e))
        return None, True


RATE_LIMIT_FREE = 5
RATE_LIMIT_PREMIUM = 20


async def _save_one(
    owner_id: uuid.UUID,
    owner_type: str,
    photo_id: str,
    data: dict,
    matrix=None,
    photo_url: str | None = None,
    show_in_collage: bool = True,
) -> bool:
    """Сохраняет WardrobeItem."""
    category_group = data.get("category_group") or "top"
    if category_group not in _VALID_CATEGORY_GROUPS:
        category_group = "top"
    data["category_group"] = category_group

    raw_breakdown = data.get("score_breakdown") or {}
    if matrix and raw_breakdown:
        score_breakdown = raw_breakdown
        score_item = calc_item_score(raw_breakdown, matrix)
        score_version = "v3.0"
    else:
        score_breakdown, score_item = _default_score()
        score_version = "v1.0"

    from services.scoring import classify_role as _classify_role
    item_role = _classify_role(data.get("type") or "", data.get("color") or "")

    try:
        async with AsyncWriteSession() as session:
            await create(
                session,
                owner_id=owner_id,
                owner_type=owner_type,
                photo_id=photo_id,
                photo_url=photo_url,
                category_group=category_group,
                category_code=data.get("category_code") or category_group,
                type=data.get("type") or "вещь",
                color=data.get("color") or "неизвестный",
                style=data.get("style") or "casual",
                brand=data.get("brand"),
                season=data.get("season") or ["spring", "summer", "autumn"],
                occasion=data.get("occasion") or ["everyday"],
                condition="новая",
                wear_count=0,
                keep=True,
                wishlist=False,
                quantity=1,
                show_in_collage=show_in_collage,
                is_base_layer=(category_group == "base_layer"),
                role=item_role,
                score_item=score_item,
                score_breakdown=score_breakdown,
                score_version=score_version,
                score_notes="",
            )
            await session.commit()
    except Exception as e:
        logger.error(
            "wardrobe.save_failed",
            error=str(e),
            exc_info=True,
            owner_id=str(owner_id),
            item_type=data.get("type"),
            category_group=category_group,
        )
        raise
    return True


# ── Ядро: анализ + сохранение одного фото ──────────────────────────────────

async def _analyze_and_save(
    photo_id: str,
    owner_id: uuid.UUID,
    owner_type: str,
    bot,
    matrix=None,
    redis=None,
) -> list[dict]:
    """Скачать фото → Claude Vision → crop по bbox → R2 → сохранить WardrobeItem."""
    tg_file = await bot.get_file(photo_id)
    photo_bytes = bytes(await tg_file.download_as_bytearray())

    items_data = await _call_vision(photo_bytes)

    # Дедупликация: загружаем существующие вещи
    existing_set = await _load_existing_set(owner_id, owner_type)

    added: list[dict] = []

    for data in items_data:
        cg = data.get("category_group") or "top"
        if cg not in _VALID_CATEGORY_GROUPS:
            cg = "top"
        data["category_group"] = cg

        key = _dedup_key(data)
        if key in existing_set:
            logger.info("wardrobe.dedup.skipped", type=data.get("type"), color=data.get("color"))
            continue

        _fix_bbox(data)
        bbox = data.get("bbox") or {}
        bw = float(bbox.get("w", 0.5))
        bh = float(bbox.get("h", 0.5))

        # Переклассификация: маленькая "шапка" → носки
        if (data.get("category_group") == "accessory" and
                any(w in (data.get("type") or "").lower()
                    for w in ["шапка", "шапочка", "hat"]) and
                bw <= 0.2 and bh <= 0.2):
            logger.info("wardrobe.reclassify",
                from_type=data.get("type"), to_type="носки",
                reason="small_bbox_accessory")
            data["category_group"] = "base_layer"
            data["type"] = "носки"

        photo_url, good_crop = await _upload_crop(photo_bytes, data.get("bbox"), owner_id=owner_id, redis=redis)
        await _save_one(owner_id, owner_type, photo_id, data, matrix,
                        photo_url=photo_url, show_in_collage=good_crop)
        existing_set.add(key)
        added.append(data)
        # Инвалидировать кеш wardrobe summary
        if redis:
            try:
                await redis.delete(f"wardrobe_summary:{owner_id}")
            except Exception:
                pass

    return added


# ── Оценка образа ───────────────────────────────────────────────────────────

async def _rate_photos(
    file_ids: list[str],
    mode: str,
    message,
    bot,
    owner_id: uuid.UUID | None = None,
    owner_type: str | None = None,
) -> None:
    try:
        if mode == "single":
            photo_bytes_list = []
            for file_id in file_ids:
                logger.info("rate.photo_source",
                    file_id=file_id[:20], source="telegram_original")
                tg_file = await bot.get_file(file_id)
                photo_bytes = bytes(await tg_file.download_as_bytearray())
                logger.info("rate.download_ok",
                    file_id=file_id[:20], size=len(photo_bytes))
                photo_bytes_list.append(photo_bytes)
            result = await _call_rate_vision(photo_bytes_list, owner_id=owner_id, owner_type=owner_type)
            await message.reply_text(result, reply_markup=get_main_menu())
        else:
            for i, file_id in enumerate(file_ids, 1):
                tg_file = await bot.get_file(file_id)
                photo_bytes = bytes(await tg_file.download_as_bytearray())
                result = await _call_rate_vision([photo_bytes], owner_id=owner_id, owner_type=owner_type)
                await message.reply_text(f"📷 Фото {i}:\n{result}", reply_markup=get_main_menu())
    except Exception as e:
        await message.reply_text("Не удалось оценить образ. Попробуй ещё раз.", reply_markup=get_main_menu())
        logger.error("rate_photos.error", error=str(e))
        sentry_sdk.capture_exception(e)


# ── UX: кнопки выбора действия ──────────────────────────────────────────────

async def _send_action_buttons(message, group_id: str) -> None:
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👜 В гардероб", callback_data=f"photo_action:add:{group_id}"),
        InlineKeyboardButton("⭐ Оценить образ", callback_data=f"photo_action:rate:{group_id}"),
    ]])
    await message.reply_text("Что делаем с фото?", reply_markup=keyboard)


async def _collect_and_ask(group_id: str, message, redis) -> None:
    """Ждём 3 сек (пока Telegram пришлёт все фото группы), потом спрашиваем."""
    await asyncio.sleep(3)
    try:
        raw_ids = await redis.lrange(f"media_group:{group_id}", 0, -1)
        file_ids = [fid.decode() if isinstance(fid, bytes) else fid for fid in raw_ids]
    except Exception as e:
        logger.error("collect_and_ask.redis_failed", error=str(e))
        return
    if not file_ids:
        return
    try:
        await redis.set(f"photo_pending:{group_id}", json.dumps(file_ids), ex=300)
    except Exception as e:
        logger.error("collect_and_ask.store_failed", error=str(e))
        return
    await _send_action_buttons(message, group_id)


# ── handle_photo ───────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    if not user.onboarding_completed:
        await update.message.reply_text("Сначала пройди настройку: /start")
        return

    # Режим оценки образа (из кнопки меню)
    if context.user_data.get("awaiting_rate_photo"):
        context.user_data.pop("awaiting_rate_photo")

        # Проверить лимит оценок
        redis = context.bot_data.get("redis")
        from datetime import date as _date_rate
        today = _date_rate.today().isoformat()
        rate_key = f"rate_limit:{user.id}:{today}"
        effective_plan = get_effective_plan(user)
        rate_limit = get_limit("rate_per_day", effective_plan)
        rate_count = 0
        if redis:
            val = await redis.get(rate_key)
            rate_count = int(val) if val else 0
        if rate_count >= rate_limit:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
            ]])
            await update.message.reply_text(
                f"✋ Лимит оценок на сегодня ({rate_limit}/день).\n"
                f"Завтра снова доступно!",
                reply_markup=keyboard,
            )
            return

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id
        else:
            return
        owner_id, owner_type = await _get_owner(user, context)
        await update.message.reply_text("⭐ Оцениваю...")
        asyncio.create_task(
            _rate_photos([file_id], "single", update.message,
                         context.bot, owner_id=owner_id, owner_type=owner_type)
        )
        # Увеличить счётчик после запуска оценки
        if redis:
            await redis.incr(rate_key)
            await redis.expire(rate_key, 86400)
        return

    redis = context.bot_data.get("redis")

    # ── Лимиты: фото в день и размер гардероба ───────────────────────────────
    _effective_plan = get_effective_plan(user)
    if _effective_plan != "admin":
        # Первые 5 вещей — без лимита (онбординг через фото)
        _owner_id_check, _owner_type_check = await _get_owner(user, context)
        async with AsyncReadSession() as _session_check:
            _existing_items = await get_owner_items(_session_check, _owner_id_check, _owner_type_check)
        _skip_daily_limit = len(_existing_items) < 5

        from datetime import date as _date_ph
        _today_ph = _date_ph.today().isoformat()
        _photo_key = f"photos_day:{user.id}:{_today_ph}"
        _photo_count = 0
        if redis:
            _val = await redis.get(_photo_key)
            _photo_count = int(_val) if _val else 0
        _photo_limit = get_limit("photos_per_day", _effective_plan)
        if not _skip_daily_limit and _photo_count >= _photo_limit:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
            ]])
            await update.message.reply_text(
                f"📸 Добавлено {_photo_count}/{_photo_limit} фото сегодня.\n"
                f"Лимит восстановится завтра!",
                reply_markup=keyboard,
            )
            return

        # Проверить лимит размера гардероба (используем _existing_items уже загруженный выше)
        _wardrobe_limit = get_limit("wardrobe_size", _effective_plan)
        if len(_existing_items) >= _wardrobe_limit:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Расширить гардероб →", callback_data="show_upgrade")
            ]])
            if _effective_plan == "free":
                msg = t(
                    "wardrobe.full.free",
                    used=str(len(_existing_items)),
                    max=str(_wardrobe_limit),
                )
            else:
                msg = t(
                    "wardrobe.full",
                    used=str(len(_existing_items)),
                    max=str(_wardrobe_limit),
                )
            await update.message.reply_text(msg, reply_markup=keyboard)
            return

    # ── Trial активация при первом фото ──────────────────────────────────────
    if not getattr(user, "trial_started_at", None):
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        from sqlalchemy import update as _sa_update
        _now = _dt.now(_tz.utc)
        async with AsyncWriteSession() as _ts:
            _res = await _ts.execute(
                _sa_update(User)
                .where(User.id == user.id)
                .where(User.trial_started_at.is_(None))
                .values(trial_started_at=_now, trial_ends_at=_now + _td(days=14))
            )
            await _ts.commit()
        if _res.rowcount > 0:
            user.trial_started_at = _now
            user.trial_ends_at = _now + _td(days=14)
            logger.info("trial.activated", user_id=str(user.id))
            await update.message.reply_text(t("trial.activated"))

    # Подсказка про bulk upload — один раз, если гардероб пуст
    if redis:
        tip_key = f"shown_bulk_tip:{user.id}"
        if not await redis.get(tip_key):
            async with AsyncReadSession() as session:
                existing = await get_owner_items(session, user.id, "user")
            if not existing:
                await update.message.reply_text(
                    "💡 Советы для лучшего результата:\n"
                    "📱 Снимай вертикально\n"
                    "🗂 До 10 вещей на фото\n"
                    "💡 Раскладывай вещи так чтобы они не перекрывали друг друга"
                )
                await redis.set(tip_key, "1", ex=31_536_000)

    if not redis:
        # Redis недоступен — немедленное добавление в гардероб
        owner_id, owner_type = await _get_owner(user, context)
        effective_plan = get_effective_plan(user)
        limit = get_limit("photos_per_day", effective_plan)
        if limit != 9999 and user.daily_requests_used >= limit:
            await update.message.reply_text(get_limit_exceeded_msg(user))
            return
        await _handle_single_photo(update, context, user, owner_id, owner_type)
        return

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    else:
        return
    media_group_id = update.message.media_group_id

    if not media_group_id:
        # Одиночное фото — сохраняем pending и показываем кнопки
        group_id = str(uuid.uuid4())
        await redis.set(f"photo_pending:{group_id}", json.dumps([file_id]), ex=300)
        await _send_action_buttons(update.message, group_id)
    else:
        # Медиагруппа — собираем все фото за 3 сек, потом спрашиваем
        list_key = f"media_group:{media_group_id}"
        length = await redis.rpush(list_key, file_id)
        if length == 1:
            await redis.expire(list_key, 15)
            asyncio.create_task(
                _collect_and_ask(media_group_id, update.message, redis)
            )


# ── Одиночное фото (fallback без Redis) ─────────────────────────────────────

async def _handle_single_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    owner_id: uuid.UUID,
    owner_type: str,
) -> None:
    try:
        start = time.monotonic()
        photo_id = update.message.photo[-1].file_id

        redis = context.bot_data.get("redis")
        matrix = await _get_scoring_matrix(redis, user, owner_id, owner_type)
        added = await _analyze_and_save(photo_id, owner_id, owner_type, context.bot, matrix, redis=redis)

        new_count = user.daily_requests_used + 1
        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User).where(User.id == user.id)
                .values(daily_requests_used=new_count)
            )
            await session.commit()
        user.daily_requests_used = new_count

        duration_ms = int((time.monotonic() - start) * 1000)

        lines = []
        if added:
            lines.append(f"✅ Добавила {len(added)} вещей:")
            for d in added:
                lines.append(f"→ {_item_label(d)}")
        if not added:
            lines.append("🤔 На фото не найдено одежды")

        await update.message.reply_text("\n".join(lines))

        # Комментарий стилиста для первой добавленной вещи
        if added:
            try:
                from datetime import date
                from services.scoring_comment import generate_item_comment
                from services.scoring import classify_role
                first = added[0]
                _item_type = first.get("type") or "вещь"
                _item_color = first.get("color") or ""
                _role = classify_role(_item_type, _item_color)
                _pool = get_anthropic_pool()
                # Тон из матрицы
                _tone = ""
                if matrix and hasattr(matrix, "criteria"):
                    _tone = matrix.criteria.get("_tone") or ""
                # Информация о ребёнке/пользователе
                _child_name = _child_gender = _child_age = None
                if owner_type == "child":
                    try:
                        from db.crud.children import get_children
                        async with AsyncReadSession() as _cs:
                            _children = await get_children(_cs, user.id)
                        _ch = next((c for c in _children if c.id == owner_id), None)
                        if _ch:
                            _child_name = _ch.name
                            _child_gender = getattr(_ch, "gender", None)
                            _child_age = (date.today() - _ch.birthdate).days // 365 if _ch.birthdate else None
                    except Exception:
                        pass
                _colortype = getattr(user, "colortype", None)
                _comment = await generate_item_comment(
                    pool=_pool,
                    item_type=_item_type,
                    item_color=_item_color,
                    score=0.0,
                    role=_role,
                    colortype=_colortype,
                    colortype_match=True,
                    wardrobe_summary="",
                    gender=_child_gender,
                    age=_child_age,
                    child_name=_child_name,
                    tone=_tone,
                )
                await update.message.reply_text(f"💬 {_comment}")
            except Exception as _e:
                logger.warning("wardrobe.item_comment_failed", error=str(_e))

        # ── Balance insight при milestone (каждые 10 вещей) ────────────────
        if added:
            try:
                from services.scoring import get_wardrobe_balance_insight
                async with AsyncReadSession() as _bi_sess:
                    _all_items = await get_owner_items(_bi_sess, owner_id, owner_type)
                _count = len(_all_items)
                if _count > 0 and _count % 10 == 0:
                    _insight = get_wardrobe_balance_insight(_all_items)
                    if _insight:
                        await update.message.reply_text(_insight)
            except Exception as _e:
                logger.warning("wardrobe.balance_insight_failed", error=str(_e))

        # ── Триггер первого брифа на 5-й вещи (для ВСЕХ юзеров) ────────────
        if added and user.onboarding_completed:
            await _maybe_trigger_first_brief(user, owner_id, owner_type, update.message, context, redis)

        usage = get_usage_str(user)
        if usage:
            await update.message.reply_text(usage)

        logger.info(
            "wardrobe.item.added",
            user_id=str(user.id),
            action="wardrobe.item.added",
            added=len(added),
            duration_ms=duration_ms,
        )

    except (RateLimitError, FashionBotError) as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(t("error.generic"))
        logger.error("wardrobe.photo.error", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)


# ── Callback: выбор действия с фото ─────────────────────────────────────────

async def handle_photo_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    action, group_id = parts[1], parts[2]

    user = context.user_data.get("db_user")
    if not user:
        return

    redis = context.bot_data.get("redis")
    if not redis:
        await query.edit_message_text("Сервис временно недоступен")
        return

    raw = await redis.get(f"photo_pending:{group_id}")
    if not raw:
        await query.edit_message_text("⏱ Время вышло. Отправь фото ещё раз.")
        return

    file_ids = json.loads(raw if isinstance(raw, str) else raw.decode())

    if action == "add":
        effective_plan = get_effective_plan(user)
        limit = get_limit("photos_per_day", effective_plan)
        if limit != 9999 and user.daily_requests_used >= limit:
            await query.edit_message_text(get_limit_exceeded_msg(user))
            return
        await query.edit_message_text("📥 Добавляю в гардероб...")
        asyncio.create_task(
            _process_media_group(
                file_ids=file_ids,
                user_id=str(user.id),
                message=query.message,
                bot=context.bot,
                context=context,
            )
        )

    elif action == "rate":
        owner_id, owner_type = await _get_owner(user, context)
        if len(file_ids) > 1:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("👗 Это один образ", callback_data=f"rate_mode:single:{group_id}"),
                InlineKeyboardButton("👗👗 Каждое фото отдельно", callback_data=f"rate_mode:each:{group_id}"),
            ]])
            await query.edit_message_text("Как оцениваем?", reply_markup=keyboard)
        else:
            await query.edit_message_text("⭐ Оцениваю...")
            asyncio.create_task(_rate_photos(file_ids, "single", query.message, context.bot, owner_id=owner_id, owner_type=owner_type))



# ── handle_rate_mode_text (кнопка Оценить образ из меню) ────────────────

async def handle_rate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    owner_id, owner_type = await _get_owner(user, context)

    if owner_type == "child":
        async with AsyncReadSession() as session:
            from db.models.child import Child as _Child
            from sqlalchemy import select as _sel
            _res = await session.execute(_sel(_Child).where(_Child.id == owner_id))
            _child = _res.scalar_one_or_none()
        name = _child.name if _child else "ребёнка"
        prompt = f"Оцениваю образ для <b>{name}</b> 👧\nПришли фото в полный рост!"
    else:
        prompt = "Оцениваю <b>твой</b> образ 👗\nПришли фото в полный рост!"

    context.user_data["awaiting_rate_photo"] = True
    await update.message.reply_text(prompt, parse_mode="HTML")


# ── Callback: режим оценки ───────────────────────────────────────────────────

async def handle_rate_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    mode, group_id = parts[1], parts[2]

    redis = context.bot_data.get("redis")
    raw = await redis.get(f"photo_pending:{group_id}") if redis else None
    if not raw:
        await query.edit_message_text("⏱ Время вышло. Отправь фото ещё раз.")
        return

    user = context.user_data.get("db_user")
    owner_id, owner_type = await _get_owner(user, context) if user else (None, None)

    file_ids = json.loads(raw if isinstance(raw, str) else raw.decode())
    await query.edit_message_text("⭐ Оцениваю...")
    asyncio.create_task(_rate_photos(file_ids, mode, query.message, context.bot, owner_id=owner_id, owner_type=owner_type))


# ── Обработка медиагруппы (добавление в гардероб) ──────────────────────────

async def _process_media_group(
    file_ids: list[str],
    user_id: str,
    message,
    bot,
    context,
) -> None:
    total_received = len(file_ids)
    if not total_received:
        return

    # Загрузить актуального пользователя из БД
    try:
        uid = uuid.UUID(user_id)
        async with AsyncReadSession() as session:
            from sqlalchemy import select as _select
            result = await session.execute(_select(User).where(User.id == uid))
            user = result.scalar_one_or_none()
        if not user:
            return
    except Exception as e:
        logger.error("media_group.user_load_failed", error=str(e))
        return

    owner_id, owner_type = await _get_owner(user, context)

    # Проверка лимита
    effective_plan = get_effective_plan(user)
    limit = get_limit("photos_per_day", effective_plan)
    if limit != 9999:
        remaining = limit - user.daily_requests_used
        if remaining <= 0:
            await message.reply_text(get_limit_exceeded_msg(user))
            return
    else:
        remaining = total_received  # unlimited

    to_process = file_ids[:min(10, remaining)]
    total = len(to_process)
    skipped_limit = max(0, min(total_received, 10) - total)

    if total_received > 10:
        await message.reply_text(
            f"📸 Получила {total_received} фото — обработаю первые {total}."
        )
    else:
        await message.reply_text(f"📸 Получила {total_received} фото. Начинаю анализ...")

    progress_text = f"🔍 Анализирую фото 1 из {total}..."
    progress_msg = await message.reply_text(progress_text)

    _redis = context.bot_data.get("redis") if context else None
    matrix = await _get_scoring_matrix(_redis, user, owner_id, owner_type)

    photo_lines: list[str] = []
    total_added = 0
    successful_photos = 0

    for i, file_id in enumerate(to_process):
        try:
            logger.info("wardrobe.processing", index=i, file_id=file_id[:20])
            new_progress = f"🔍 Анализирую фото {i + 1} из {total}..."
            if new_progress != progress_text:
                await progress_msg.edit_text(new_progress)
                progress_text = new_progress

            logger.info("wardrobe.vision_start", index=i)
            tg_file = await bot.get_file(file_id)
            photo_bytes = bytes(await tg_file.download_as_bytearray())
            items_data = await _call_vision(photo_bytes)
            logger.info("wardrobe.vision_done", index=i, items_count=len(items_data))

            # Дедупликация: загружаем актуальный набор вещей
            existing_set = await _load_existing_set(owner_id, owner_type)

            added: list[dict] = []
            for data in items_data:
                cg = data.get("category_group") or "top"
                if cg not in _VALID_CATEGORY_GROUPS:
                    cg = "top"
                data["category_group"] = cg

                key = _dedup_key(data)
                if key in existing_set:
                    logger.info("wardrobe.dedup.skipped", index=i, type=data.get("type"), color=data.get("color"))
                    continue

                logger.info("wardrobe.save_start", index=i, item_type=data.get("type"))
                _fix_bbox(data)
                _bbox = data.get("bbox") or {}
                _bw = float(_bbox.get("w", 0.5))
                _bh = float(_bbox.get("h", 0.5))
                if (data.get("category_group") == "accessory" and
                        any(w in (data.get("type") or "").lower()
                            for w in ["шапка", "шапочка", "hat"]) and
                        _bw <= 0.2 and _bh <= 0.2):
                    logger.info("wardrobe.reclassify",
                        from_type=data.get("type"), to_type="носки",
                        reason="small_bbox_accessory")
                    data["category_group"] = "base_layer"
                    data["type"] = "носки"
                photo_url, good_crop = await _upload_crop(photo_bytes, data.get("bbox"), owner_id=owner_id, redis=_redis)
                await _save_one(owner_id, owner_type, file_id, data, matrix,
                                photo_url=photo_url, show_in_collage=good_crop)
                existing_set.add(key)
                added.append(data)
                logger.info("wardrobe.save_done", index=i)

            successful_photos += 1
            total_added += len(added)

            if added:
                names = ", ".join(_item_label(d) for d in added)
                photo_lines.append(f"📷 Фото {i + 1}: {names}")
            else:
                photo_lines.append(f"📷 Фото {i + 1}: одежды не найдено")

            logger.info(
                "wardrobe.item.added",
                user_id=user_id,
                action="wardrobe.item.added",
                photo_index=i,
                added=len(added),
                bulk=True,
            )
        except Exception as e:
            photo_lines.append(f"📷 Фото {i + 1}: ❌ не удалось распознать")
            logger.error("media_group.item_failed", index=i, error=str(e), exc_info=True)

    for j in range(skipped_limit):
        photo_lines.append(f"📷 Фото {total + j + 1}: ⏭ пропущено (лимит запросов)")

    if successful_photos > 0:
        try:
            async with AsyncWriteSession() as session:
                await session.execute(
                    sa.update(User).where(User.id == uid)
                    .values(daily_requests_used=User.daily_requests_used + successful_photos)
                )
                await session.commit()
        except Exception as e:
            logger.error("media_group.counter_update_failed", error=str(e))

    summary = "\n".join(photo_lines)
    await progress_msg.edit_text(
        f"✅ Добавила {total_added} вещей из {total} фото:\n\n{summary}"
    )

    # ── Триггер первого брифа на 5-й вещи (для ВСЕХ юзеров) ────────────
    if total_added > 0 and user.onboarding_completed:
        _redis2 = context.bot_data.get("redis") if context else None
        await _maybe_trigger_first_brief(user, owner_id, owner_type, message, context, _redis2)


# ── handle_wardrobe_menu (кнопка Гардероб в меню) ───────────────────────────

async def handle_wardrobe_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать гардероб с кнопкой переключения владельца."""
    user = context.user_data.get("db_user")
    if not user:
        return

    async with AsyncReadSession() as session:
        from db.crud.children import get_children
        children = await get_children(session, user.id)

    owner_id, owner_type = await _get_owner(user, context)

    if owner_type == "user":
        owner_name = user.name
    else:
        child = next((c for c in children if c.id == owner_id), None)
        owner_name = child.name if child else "Ребёнок"

    buttons = []
    if children:
        if owner_type == "child":
            buttons.append([InlineKeyboardButton(
                "👗 Мои вещи",
                callback_data="switch_owner:user"
            )])
        else:
            child = children[0]
            buttons.append([InlineKeyboardButton(
                f"👧 Вещи {child.name}",
                callback_data=f"switch_owner:child:{child.id}"
            )])

    # Считаем вещи и средний скор для заголовка
    async with AsyncReadSession() as session:
        all_items = await get_owner_items(session, owner_id, owner_type)
    item_count = len(all_items)

    # Кнопки: образ дня + список; gap analysis для premium; switch-кнопки ниже
    from core.permissions import get_effective_plan, can_gap_analysis
    _ep = get_effective_plan(user)
    top_row = [
        InlineKeyboardButton("🌤 Образ дня", callback_data="outfit_request"),
        InlineKeyboardButton("👀 Посмотреть вещи", callback_data="show_wardrobe_list"),
    ]
    extra_rows = []
    if can_gap_analysis(_ep):
        extra_rows.append([InlineKeyboardButton("📋 Что не хватает?", callback_data="gap_analysis")])
    markup = InlineKeyboardMarkup([top_row] + extra_rows + buttons)

    await update.message.reply_text(
        f"👗 Гардероб: *{owner_name}* · {item_count} вещей",
        parse_mode="Markdown",
        reply_markup=markup,
    )


async def handle_switch_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: переключить владельца, обновить кнопки в том же сообщении."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    import uuid as _uuid
    redis = context.bot_data.get("redis")
    parts = query.data.split(":")  # switch_owner:user OR switch_owner:child:{uuid}
    target = parts[1] if len(parts) > 1 else "child"
    child_id_str = parts[2] if len(parts) > 2 else None

    # Загрузить детей один раз для валидации и формирования кнопок
    async with AsyncReadSession() as session:
        from db.crud.children import get_children as _gc
        children = await _gc(session, user.id)

    if target == "user":
        new_owner_id = user.id
        new_owner_type = "user"
        owner_label = f"👗 Гардероб: {user.name}"
    elif target == "child" and child_id_str:
        try:
            child_id = _uuid.UUID(child_id_str)
        except ValueError:
            await query.answer("Ошибка: неверный ID")
            return
        # Валидация — child должен принадлежать этому пользователю
        child = next((c for c in children if c.id == child_id), None)
        if not child:
            await query.answer("Ребёнок не найден")
            return
        new_owner_id = child_id
        new_owner_type = "child"
        owner_label = f"👧 Гардероб: {child.name}"
    else:
        return

    # Сохранить новый owner в кеш и Redis
    cache_key = f"owner:{user.id}"
    context.bot_data[cache_key] = (new_owner_id, new_owner_type)
    if redis:
        mode_val = f"child:{new_owner_id}" if new_owner_type == "child" else "user"
        await redis.set(f"owner_mode:{user.id}", mode_val, ex=86400 * 30)

    # Загрузить вещи нового owner для count
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, new_owner_id, new_owner_type)
    count = len(items)

    # Заголовок
    if count == 0:
        header = (
            f"✅ Переключено\n"
            f"{owner_label} · 0 вещей\n"
            f"Пришли фото чтобы добавить вещи 📸"
        )
    else:
        header = f"✅ Переключено\n{owner_label} · {count} вещей"

    # Кнопка переключения на другого owner
    if new_owner_type == "child":
        switch_btn = InlineKeyboardButton("👗 Мои вещи", callback_data="switch_owner:user")
    elif children:
        child = children[0]
        switch_btn = InlineKeyboardButton(
            f"👧 Вещи {child.name}",
            callback_data=f"switch_owner:child:{child.id}"
        )
    else:
        switch_btn = None

    # Кнопка действия
    if count == 0:
        action_btn = InlineKeyboardButton("📸 Добавить вещи", callback_data="add_items_hint")
    else:
        action_btn = InlineKeyboardButton("👀 Посмотреть вещи", callback_data="show_wardrobe_list")

    keyboard_rows = [[
        InlineKeyboardButton("🌤 Образ дня", callback_data="outfit_request"),
        action_btn,
    ]]
    if switch_btn:
        keyboard_rows.append([switch_btn])

    new_markup = InlineKeyboardMarkup(keyboard_rows)

    try:
        await query.edit_message_text(header, reply_markup=new_markup)
    except Exception as e:
        if "not modified" not in str(e).lower():
            await query.message.reply_text(header, reply_markup=new_markup)


async def handle_add_items_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: подсказка как добавить вещи (при пустом гардеробе)."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "📸 Просто пришли фото вещей — добавлю в гардероб!",
        reply_markup=get_main_menu(),
    )



# ── handle_outfit_request (кнопка Образ дня из Гардероба) ───────────────────

async def _generate_outfit_for_user(message, user, context, exclude_ids: set | None = None) -> None:
    """Общая логика генерации образа. Вызывается из меню и из inline-кнопки гардероба."""
    redis = context.bot_data.get("redis")
    from datetime import date as _date, datetime as _datetime
    import random as _random

    today = _date.today().isoformat()
    limit_key = f"outfit_req:{user.id}:{today}"
    _ep_outfit = get_effective_plan(user)
    day_limit = get_limit("outfit_req_per_day", _ep_outfit)

    count = 0
    if redis:
        val = await redis.get(limit_key)
        count = int(val) if val else 0

    if count >= day_limit and _ep_outfit != "admin":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Получить безлимит →", callback_data="show_upgrade")
        ]])
        await message.reply_text(
            f"✋ На сегодня лимит образов ({day_limit}/день).\n"
            "Следующий образ — завтра утром в 07:00 🌅",
            reply_markup=keyboard,
        )
        return

    await message.reply_text("🌤 Собираю образ...")

    try:
        from services.weather import WeatherService
        from services.image_builder import build_collage

        # Найти детей
        async with AsyncReadSession() as session:
            from db.crud.children import get_children as _get_children
            children = await _get_children(session, user.id)

        is_no_kids = getattr(user, "segment", None) == "no_kids"

        if not children and not is_no_kids:
            await message.reply_text(
                "Добавь ребёнка в профиле чтобы получать образы 👧",
                reply_markup=get_main_menu(),
            )
            return

        child = children[0] if children else None

        # Погода — fallback 10/12°C если город не задан или сервис недоступен
        temp_m, temp_e = 10.0, 12.0
        try:
            if user.city and redis:
                svc = WeatherService(redis)
                wd = await svc.get(user.city)
                temp_m = float(wd.temp_c)
                temp_e = float(wd.evening_temp)
                logger.info("outfit_request.weather_ok",
                    city=user.city, temp_m=temp_m, temp_e=temp_e)
        except Exception as we:
            logger.warning("outfit_request.weather_failed",
                error=str(we), city=getattr(user, "city", None))

        # Вещи: для no_kids — из гардероба пользователя, иначе — ребёнка
        if child:
            owner_id_for_outfit, owner_type_for_outfit = child.id, "child"
            colortype_for_outfit = getattr(child, "colortype", None) or "default"
        else:
            owner_id_for_outfit, owner_type_for_outfit = user.id, "user"
            colortype_for_outfit = getattr(user, "colortype", None) or "default"

        async with AsyncReadSession() as session:
            items = await get_owner_items(session, owner_id_for_outfit, owner_type_for_outfit)

        if not items:
            await message.reply_text(
                "Гардероб пуст — добавь вещи через фото 📸",
                reply_markup=get_main_menu(),
            )
            return

        # Полностью случайный seed при каждом запросе
        import uuid as _uuid
        _random.seed(str(_uuid.uuid4()))

        # Накопленные исключения из Redis (все ранее показанные образы сегодня)
        shown_key = f"outfit_shown:{user.id}:{owner_id_for_outfit}"
        accumulated_ids: set = set(exclude_ids or [])
        if redis:
            try:
                raw_shown = await redis.smembers(shown_key)
                for raw in raw_shown:
                    try:
                        accumulated_ids.add(_uuid.UUID(raw.decode() if isinstance(raw, bytes) else raw))
                    except Exception:
                        pass
            except Exception:
                pass

        # Исключить все ранее показанные вещи
        if accumulated_ids:
            items_shuffled = [i for i in items if i.id not in accumulated_ids]
            if len(items_shuffled) < 3:
                # Мало вещей — сбросить историю, включить все
                if redis:
                    try:
                        await redis.delete(shown_key)
                    except Exception:
                        pass
                items_shuffled = list(items)
        else:
            items_shuffled = list(items)
        _random.shuffle(items_shuffled)

        today_date = _date.today()
        season = SEASONS[today_date.month]
        outfit = select_outfit(items_shuffled, season, today_date, temp_m, temp_e)

        regime = get_temp_regime(temp_m)
        all_slots = build_outfit_slots(
            outfit, child=child, temp=temp_m, colortype=colortype_for_outfit, regime=regime
        )

        _day_type = ("садик" if today_date.weekday() < 5 else "прогулка") if child else ""
        _collage_params = get_collage_params(child=child, user=user, temp=temp_m, day_type=_day_type)

        # Тёплый комментарий Касси
        scored = [float(i.score_item) for i in outfit.get("all_items", []) if i.score_item]
        has_ow = any(s["slot"] == "outerwear" and s.get("has_item") for s in all_slots)
        missing = [s["slot"] for s in all_slots if not s.get("has_item")]
        child_name_str = child.name if child else None
        if scored:
            avg = sum(scored) / len(scored)
            comment = _warm_outfit_comment(avg, child_name_str, temp_m, has_ow, missing)
        else:
            comment = _warm_outfit_comment(6.0, child_name_str, temp_m, has_ow, missing)

        caption = f"✨ {comment}"

        outfit_warnings = outfit.get("warnings") or []
        if outfit_warnings:
            caption += "\n\n" + "\n".join(outfit_warnings)

        collage_bytes = await build_collage(
            outfit_slots=all_slots,
            theme=_collage_params["theme"],
            header_text=_collage_params["header_text"],
        )

        if redis:
            await redis.incr(limit_key)
            await redis.expire(limit_key, 86400)
            # Сохранить ID вещей этого образа — исключить при следующем reroll
            try:
                shown_item_ids = [str(i.id) for i in outfit.get("all_items", []) if hasattr(i, "id")]
                if shown_item_ids:
                    await redis.sadd(shown_key, *shown_item_ids)
                    await redis.expire(shown_key, 86400)
            except Exception:
                pass

        _reroll_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Другой образ", callback_data="outfit_request"),
        ]])
        if collage_bytes:
            await message.reply_photo(
                photo=collage_bytes, caption=caption, reply_markup=_reroll_markup
            )
        else:
            await message.reply_text(caption, reply_markup=_reroll_markup)

    except Exception as e:
        logger.error("outfit_request.failed", error=str(e))
        import sentry_sdk as _sentry
        _sentry.capture_exception(e)
        await message.reply_text(
            "Не удалось собрать образ. Попробуй позже.",
            reply_markup=get_main_menu(),
        )


async def handle_outfit_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline-кнопка 'Образ дня' в гардеробе → генерация образа."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    await _generate_outfit_for_user(query.message, user, context)


async def handle_what_to_wear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка '✨ Что надеть' в главном меню → сразу генерирует образ."""
    user = context.user_data.get("db_user")
    if not user:
        return
    await _generate_outfit_for_user(update.message, user, context)


async def handle_ask_kassi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка '💬 Спросить Касси' → подсказка для чата."""
    user = context.user_data.get("db_user")
    from core.permissions import get_effective_plan as _gep, get_limit as _gl
    plan = _gep(user) if user else "free"
    chat_limit = _gl("chat_per_day", plan)
    await update.message.reply_text(
        "Напиши вопрос про стиль — помогу! 👗\n"
        f"(до {chat_limit} вопросов в день)",
        reply_markup=get_main_menu(),
    )


# ── handle_list ─────────────────────────────────────────────────────────────

async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    page = context.user_data.get("wardrobe_page", 0)
    await _show_wardrobe_page(update.message, user, page, context=context)
    usage = get_usage_str(user)
    if usage:
        await update.message.reply_text(usage)


async def handle_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback кнопка 📋 Посмотреть вещи из меню гардероба."""
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    context.user_data["wardrobe_page"] = 0
    await _show_wardrobe_page(query.message, user, 0, context=context)


async def handle_wardrobe_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    page = int(query.data.split(":")[2])
    context.user_data["wardrobe_page"] = page
    await _show_wardrobe_page(query.message, user, page, context=context)


async def _show_wardrobe_page(message, user, page: int, owner_id=None, owner_type=None, context=None) -> None:
    try:
        if owner_id is None:
            if context is not None:
                owner_id, owner_type = await _get_owner(user, context)
            else:
                owner_id, owner_type = user.id, "user"
        elif owner_type is None:
            owner_type = "user"
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, owner_id, owner_type)

        if not items:
            await message.reply_text(t("wardrobe.empty"))
            return

        total = len(items)

        paged = items[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
        paged_groups: dict[str, list] = {}
        for item in paged:
            paged_groups.setdefault(item.category_group, []).append(item)

        lines = [f"👗 Гардероб ({total} вещей)\n"]
        for group, group_items in paged_groups.items():
            label = _CATEGORY_LABELS.get(group, group)
            names = ", ".join(f"{color_circle(i.color)} {i.type} {i.color}" for i in group_items[:5])
            lines.append(f"{label} ({len(group_items)}): {names}")

        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton("← Назад", callback_data=f"wardrobe:page:{page - 1}"))
        if (page + 1) * PAGE_SIZE < total:
            buttons.append(InlineKeyboardButton("Ещё →", callback_data=f"wardrobe:page:{page + 1}"))

        await message.reply_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([buttons]) if buttons else None,
        )

    except Exception as e:
        await message.reply_text(t("error.generic"))
        logger.error("wardrobe.list.error", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)


# ── Upgrade flow ─────────────────────────────────────────────────────────────

async def handle_show_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать экран выбора плана."""
    query = update.callback_query
    await query.answer()
    from core.permissions import PRICES, ULTRA_FEATURES

    text = (
        "✨ Касси Premium\n\n"
        "📅 Бриф каждый день\n"
        "👗 Образ дня без ограничений\n"
        "📸 30 фото в день\n"
        "⭐ 20 оценок образа\n"
        "💬 20 вопросов стилисту\n"
        "👧 До 3 детей\n\n"
        "Выбери план:\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_monthly']['label']}",
            callback_data="subscribe:monthly",
        )],
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_quarterly']['label']}",
            callback_data="subscribe:quarterly",
        )],
        [InlineKeyboardButton(
            f"📅 {PRICES['premium_yearly']['label']} ⭐",
            callback_data="subscribe:yearly",
        )],
        [InlineKeyboardButton("🔒 Ultra — скоро!", callback_data="show_ultra")],
    ])
    await query.message.reply_text(text, reply_markup=keyboard)


async def handle_show_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию об Ultra плане."""
    query = update.callback_query
    await query.answer()
    from core.permissions import ULTRA_FEATURES

    text = "💎 Касси Ultra — скоро!\n\nВ разработке:\n"
    for f in ULTRA_FEATURES:
        text += f"  {f}\n"
    text += "\nОставь контакт и мы уведомим о запуске!"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔔 Уведомить меня", callback_data="notify_ultra")
    ]])
    await query.message.reply_text(text, reply_markup=keyboard)


async def handle_notify_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Заглушка: пользователь хочет узнать про Ultra."""
    query = update.callback_query
    await query.answer("Отлично! Уведомим тебя первой 🎉")
    # TODO: сохранить в БД список желающих Ultra


async def handle_gap_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: gap_analysis → on-demand gap analysis."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    from core.permissions import get_effective_plan, can_gap_analysis
    plan = get_effective_plan(user)
    if not can_gap_analysis(plan):
        await query.message.reply_text(
            "📋 Анализ гардероба доступен в Premium!\n✨ Нажми «Подписка» для доступа."
        )
        return

    await query.message.reply_text("📋 Анализирую гардероб...")

    redis = context.bot_data.get("redis")
    owner_id, owner_type = await _get_owner(user, context)

    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    from services.gap_analysis import build_shopping_list, _get_current_season
    from services.i18n.ru import t
    import redis.asyncio as aioredis
    from config import settings as _settings

    redis_client = aioredis.from_url(_settings.redis_url, decode_responses=False)
    try:
        result = await build_shopping_list(user, items, redis_client)
    finally:
        await redis_client.aclose()

    if result is None:
        await query.message.reply_text(
            "📸 Добавь больше вещей в гардероб — нужно минимум 5 для анализа!"
        )
    elif result == "lock":
        await query.message.reply_text("⏳ Анализ уже выполняется, подожди немного...")
    elif result == "":
        await query.message.reply_text("✅ Гардероб укомплектован на этот сезон!")
    else:
        season = _get_current_season(user.timezone or "Europe/Vilnius")
        await query.message.reply_text(t("shopping.header", season=season, list=result))
