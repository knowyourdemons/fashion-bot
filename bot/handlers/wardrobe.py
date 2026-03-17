"""Wardrobe handlers."""
import asyncio
import base64
import json
import time
import uuid
from difflib import SequenceMatcher

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
from services.scoring import ScoringService, matrix_name_for_owner, calc_item_score
from services.usage import get_limit_exceeded_msg, get_usage_str

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

_PLAN_LIMITS = {
    "free":    settings.daily_limits_free,
    "basic":   settings.daily_limits_basic,
    "family":  settings.daily_limits_family,
    "premium": -1,
}

PAGE_SIZE = 20

_VISION_SYSTEM = """Фото может быть в любой ориентации — горизонтальной или вертикальной.
Определяй вещи независимо от их расположения на фото.

Ты определяешь детскую одежду на фото для гардероба.

Найди все вещи на фото и верни JSON массив. Каждая вещь:
{
  "type": "название строчными",
  "color": "цвет строчными",
  "style": "повседневный/спортивный/нарядный/домашний",
  "category_group": "одна из: outerwear/top/bottom/one_piece/footwear/accessory/base_layer/underwear/sportswear/home_beach",
  "category_code": "english_code",
  "season": ["winter/spring/summer/autumn"],
  "occasion": ["everyday/sport/formal/home/outdoor"],
  "brand": null,
  "score_breakdown": {"safety":1,"practicality":1,"durability":1,"age_authenticity":1,"ease_of_care":1,"colortype":1,"comfort":1,"versatility":1,"condition":1,"size_fit_score":1,"seasonality":1}
}

Для каждой вещи оцени score_breakdown по шкале 0-2:
0 = плохо, 1 = нейтрально/не видно, 2 = отлично
- safety: завязки/острые детали → 0, безопасно → 2
- practicality: резинка/застёжки → 2, сложный крой → 0
- durability: плотная ткань → 2, тонкая → 0
- age_authenticity: детский крой/принт → 2, взрослый → 0
- ease_of_care: синтетика → 2, деликатный → 0, хлопок → 1
- colortype: холодные пастели → 2, тёплые земляные → 0, нейтральные → 1
- comfort: мягкий трикотаж → 2, жёсткий → 0
- versatility: базовые цвета → 2, яркий принт → 0, нейтральный → 1
- condition: новая/без пятен → 2, ношеная → 0, обычная → 1
- size_fit_score: на ребёнке/сидит хорошо → 2, не на ребёнке → 1
- seasonality: подходит весне (март) → 2, не по сезону → 0

Категории:
- underwear: трусики, майки нательные, термобельё (термолонгслив, термолеггинсы)
  майка нательная (облегающая, тонкая, с принтом или без) → underwear, тип: майка
  НЕ путать с футболкой (футболка свободнее)
- base_layer: носки, колготки, пижама
- top: футболка, лонгслив с принтом, кофта, свитер
- bottom: штаны, шорты, юбка, леггинсы
- one_piece: платье, комбинезон, ромпер
- outerwear: куртка, пальто, жилет утеплённый
- accessory: шапка, шарф, варежки
- footwear: обувь (НЕ носки!)

Верни ТОЛЬКО JSON массив, без markdown."""

_RATE_SYSTEM = (
    "Ты стилист с насмотренностью Vogue Kids. Оцени образ на фото.\n"
    "Верни оценку от 1 до 10 и краткий комментарий (максимум 3 строки).\n"
    "Что работает, что нет, как улучшить. Язык: русский."
)


def _dedup_key(data: dict) -> tuple:
    """Ключ дедупликации: (тип, цвет, категория) в нижнем регистре."""
    return (
        (data.get("type") or "").lower().strip(),
        (data.get("color") or "").lower().strip(),
        data.get("category_group") or "top",
    )


def _item_label(data: dict) -> str:
    """Короткое название вещи для сообщений."""
    return f"{data.get('color', '')} {data.get('type', 'вещь')}".strip()


def _default_score() -> tuple[dict, float]:
    breakdown = {
        "safety": 1, "practicality": 1, "durability": 1,
        "age_authenticity": 1, "ease_of_care": 1, "colortype": 1,
        "comfort": 1, "versatility": 1, "condition": 1,
        "size_fit_score": 1, "seasonality": 1,
    }
    return breakdown, round((sum(breakdown.values()) / 15) * 10, 2)


# ── Определить владельца вещи (пользователь или ребёнок) ───────────────────

async def _get_owner(user, context) -> tuple:
    cache_key = f"owner:{user.id}"
    cached = context.bot_data.get(cache_key)
    if cached:
        return cached

    async with AsyncReadSession() as session:
        from db.crud.children import get_children
        children = await get_children(session, user.id)

    if user.segment in ("mom_girl", "mom_boy") and children:
        owner = (children[0].id, "child")
    else:
        owner = (user.id, "user")

    context.bot_data[cache_key] = owner
    return owner


# ── Загрузить матрицу скоринга для владельца ───────────────────────────────

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


# ── Получить существующие вещи владельца (ключи дедупликации) ──────────────

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


# ── Вызов Claude Vision → список dict ──────────────────────────────────────

async def _call_vision(photo_bytes: bytes) -> list[dict]:
    pool = get_anthropic_pool()
    response = await pool.create_message(
        model="claude-sonnet-4-6",
        system=_VISION_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(photo_bytes).decode(),
                    },
                },
                {"type": "text", "text": "Определи все вещи на фото."},
            ],
        }],
        max_tokens=4096,
    )

    raw = response.content[0].text.strip() if response.content else "[]"
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if not raw.endswith("]"):
        last_complete = raw.rfind("},")
        if last_complete > 0:
            raw = raw[:last_complete + 1] + "]"

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            parsed = []
    except json.JSONDecodeError:
        logger.warning("wardrobe.json_parse_failed", raw=raw[:200])
        parsed = []

    for item in parsed:
        if isinstance(item.get("type"), str):
            item["type"] = item["type"].lower()
        if isinstance(item.get("color"), str):
            item["color"] = item["color"].lower()

    return parsed


# ── Вызов Claude Vision → оценка образа ────────────────────────────────────

async def _call_rate_vision(photo_bytes_list: list[bytes]) -> str:
    pool = get_anthropic_pool()
    content = []
    for photo_bytes in photo_bytes_list:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(photo_bytes).decode(),
            },
        })
    content.append({"type": "text", "text": "Оцени образ на фото."})

    response = await pool.create_message(
        system=_RATE_SYSTEM,
        messages=[{"role": "user", "content": content}],
        max_tokens=256,
    )
    return response.content[0].text.strip() if response.content else "Не удалось оценить образ"


# ── Сохранить один item в БД ────────────────────────────────────────────────

def _color_similar(a: str, b: str) -> bool:
    """True если цвета почти идентичны (ratio > 0.95)."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() > 0.95


async def _save_one(
    owner_id: uuid.UUID,
    owner_type: str,
    photo_id: str,
    data: dict,
    matrix=None,
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
        score_version = "v2.0"
    else:
        score_breakdown, score_item = _default_score()
        score_version = "v1.0"

    try:
        async with AsyncWriteSession() as session:
            await create(
                session,
                owner_id=owner_id,
                owner_type=owner_type,
                photo_id=photo_id,
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
                show_in_collage=True,
                is_base_layer=(category_group == "base_layer"),
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
) -> list[dict]:
    """Скачать фото → Claude Vision → сохранить все WardrobeItem. Возвращает added."""
    tg_file = await bot.get_file(photo_id)
    photo_bytes = bytes(await tg_file.download_as_bytearray())

    items_data = await _call_vision(photo_bytes)

    added: list[dict] = []

    for data in items_data:
        cg = data.get("category_group") or "top"
        if cg not in _VALID_CATEGORY_GROUPS:
            cg = "top"
        data["category_group"] = cg

        await _save_one(owner_id, owner_type, photo_id, data, matrix)
        added.append(data)

    return added


# ── Оценка образа ───────────────────────────────────────────────────────────

async def _rate_photos(file_ids: list[str], mode: str, message, bot) -> None:
    try:
        if mode == "single":
            photo_bytes_list = []
            for file_id in file_ids:
                tg_file = await bot.get_file(file_id)
                photo_bytes_list.append(bytes(await tg_file.download_as_bytearray()))
            result = await _call_rate_vision(photo_bytes_list)
            await message.reply_text(f"⭐ Скор образа:\n{result}")
        else:
            for i, file_id in enumerate(file_ids, 1):
                tg_file = await bot.get_file(file_id)
                photo_bytes = bytes(await tg_file.download_as_bytearray())
                result = await _call_rate_vision([photo_bytes])
                await message.reply_text(f"📷 Фото {i}:\n{result}")
    except Exception as e:
        await message.reply_text("Не удалось оценить образ. Попробуй ещё раз.")
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

    redis = context.bot_data.get("redis")

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
        limit = _PLAN_LIMITS.get(user.plan, settings.daily_limits_free)
        if limit != -1 and user.daily_requests_used >= limit:
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
        added = await _analyze_and_save(photo_id, owner_id, owner_type, context.bot, matrix)

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
        limit = _PLAN_LIMITS.get(user.plan, settings.daily_limits_free)
        if limit != -1 and user.daily_requests_used >= limit:
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
        if len(file_ids) > 1:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("👗 Это один образ", callback_data=f"rate_mode:single:{group_id}"),
                InlineKeyboardButton("👗👗 Каждое фото отдельно", callback_data=f"rate_mode:each:{group_id}"),
            ]])
            await query.edit_message_text("Как оцениваем?", reply_markup=keyboard)
        else:
            await query.edit_message_text("⭐ Оцениваю...")
            asyncio.create_task(_rate_photos(file_ids, "single", query.message, context.bot))


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

    file_ids = json.loads(raw if isinstance(raw, str) else raw.decode())
    await query.edit_message_text("⭐ Оцениваю...")
    asyncio.create_task(_rate_photos(file_ids, mode, query.message, context.bot))


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
    limit = _PLAN_LIMITS.get(user.plan, settings.daily_limits_free)
    if limit != -1:
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

    matrix = await _get_scoring_matrix(context.bot_data.get("redis") if context else None, user, owner_id, owner_type)

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

            added: list[dict] = []
            for data in items_data:
                cg = data.get("category_group") or "top"
                if cg not in _VALID_CATEGORY_GROUPS:
                    cg = "top"
                data["category_group"] = cg
                logger.info("wardrobe.save_start", index=i, item_type=data.get("type"))
                await _save_one(owner_id, owner_type, file_id, data, matrix)
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


# ── handle_list ─────────────────────────────────────────────────────────────

async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return
    page = context.user_data.get("wardrobe_page", 0)
    await _show_wardrobe_page(update.message, user, page)
    usage = get_usage_str(user)
    if usage:
        await update.message.reply_text(usage)


async def handle_wardrobe_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    if not user:
        return
    page = int(query.data.split(":")[2])
    context.user_data["wardrobe_page"] = page
    await _show_wardrobe_page(query.message, user, page)


async def _show_wardrobe_page(message, user, page: int) -> None:
    try:
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, user.id, "user")

        if not items:
            await message.reply_text(t("wardrobe.empty"))
            return

        total = len(items)
        scored = [float(i.score_item) for i in items if i.score_item]
        avg_score = round(sum(scored) / len(scored), 1) if scored else 0

        paged = items[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
        paged_groups: dict[str, list] = {}
        for item in paged:
            paged_groups.setdefault(item.category_group, []).append(item)

        lines = [f"👗 Гардероб ({total} вещей) · ⭐ средний скор: {avg_score}\n"]
        for group, group_items in paged_groups.items():
            label = _CATEGORY_LABELS.get(group, group)
            names = ", ".join(f"{i.color} {i.type}" for i in group_items[:5])
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
