"""Debug команды — только для ADMIN_TELEGRAM_IDS.

Команды:
  /debug_reset   — сбросить онбординг, план → premium
  /debug_free    — сбросить в free план
  /debug_brief   — триггернуть утренний бриф
  /debug_eval    — тест оценки образа (показать prompt + tiers)
  /debug_gaps    — показать gap analysis гардероба
  /debug_style   — показать style_preferences + colortype
  /debug_wardrobe — статистика гардероба (слоты, баланс, комбо)
"""
import structlog
from datetime import datetime, timezone

import sqlalchemy as sa
from telegram import Update
from telegram.ext import ContextTypes

from config import settings
from db.base import AsyncWriteSession, AsyncReadSession
from db.models.user import User
from db.models.child import Child

logger = structlog.get_logger()


async def handle_debug_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    if user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(Child)
            .where(Child.user_id == user.id, Child.deleted_at == None)
            .values(deleted_at=datetime.now(timezone.utc))
        )
        await session.execute(
            sa.update(User)
            .where(User.id == user.id)
            .values(
                onboarding_completed=False,
                onboarding_step=None,
                segment=None,
                city=None,
                timezone="Europe/Vilnius",
                plan="premium",
                daily_requests_used=0,
                daily_requests_reset_at=None,
            )
        )
        await session.commit()

    # Очистить кэш owner из bot_data
    cache_key = f"owner:{user.id}"
    context.application.bot_data.pop(cache_key, None)

    # Reload user from DB to ensure context has fresh data
    from db.base import AsyncReadSession
    from db.crud.users import get_by_id
    async with AsyncReadSession() as rsession:
        refreshed = await get_by_id(rsession, user.id)
        if refreshed:
            user = refreshed
    context.user_data["db_user"] = user

    logger.info("debug.reset", user_id=str(user.id))
    await update.message.reply_text("✅ Сброшено. План → premium. Лимиты обнулены. /start")


async def handle_debug_free(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сбросить юзера в free для тестирования free-flow. Только для admin."""
    user = context.user_data.get("db_user")
    if not user:
        return

    if user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(User)
            .where(User.id == user.id)
            .values(
                plan="free",
                plan_expires_at=None,
                trial_ends_at=None,
                trial_started_at=None,
                daily_requests_used=0,
            )
        )
        await session.commit()

    # Reload user from DB to ensure context has fresh data
    from db.base import AsyncReadSession
    from db.crud.users import get_by_id
    async with AsyncReadSession() as rsession:
        refreshed = await get_by_id(rsession, user.id)
        if refreshed:
            user = refreshed
    context.user_data["db_user"] = user

    logger.info("debug.free", user_id=str(user.id))
    await update.message.reply_text("✅ План → free. Подписки и trial сброшены.")


async def handle_debug_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Триггер Morning Brief по запросу. Только для admin."""
    user = context.user_data.get("db_user")
    if not user:
        return

    if user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    redis = context.bot_data.get("redis")
    if not redis:
        await update.message.reply_text("❌ Redis недоступен.")
        return

    try:
        # Clear brief lock for debug
        from datetime import date as _d
        _lock = f"lock:brief:{user.id}:{_d.today().isoformat()}"
        await redis.delete(_lock)

        from core.queue import RedisQueue, QueuePriority
        queue = RedisQueue(redis)
        await queue.push(
            "generate_brief",
            {"user_id": str(user.id)},
            priority=QueuePriority.HIGH,
        )
        logger.info("debug.brief_triggered", user_id=str(user.id))
        await update.message.reply_text("🌅 Бриф в очереди — придёт через несколько секунд.")
    except Exception as e:
        logger.error("debug.brief_failed", error=str(e))
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_debug_eval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать текущие настройки оценки образа: dimensions, tiers, user context."""
    user = context.user_data.get("db_user")
    if not user or user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    from services.outfit_evaluator import EVAL_DIMENSIONS, score_to_tier

    lines = ["🔍 *Debug: Outfit Evaluation*\n"]

    # User context
    lines.append(f"colortype: `{user.colortype or 'не задан'}`")
    lines.append(f"body\\_type: `{getattr(user, 'body_type', None) or 'не задан'}`")
    lines.append(f"segment: `{user.segment or 'не задан'}`")
    prefs = getattr(user, "style_preferences", None) or {}
    lines.append(f"style\\_prefs: `{prefs or 'не заданы'}`")

    # Dimensions
    lines.append("\n*Измерения оценки:*")
    for key, dim in EVAL_DIMENSIONS.items():
        lines.append(f"  {dim['label']}: {dim['weight']}%")

    # Tiers
    lines.append("\n*Tier-ы:*")
    for score in [9.5, 8.0, 6.5, 5.0, 3.0]:
        t = score_to_tier(score)
        lines.append(f"  {t['emoji']} {score}: {t['label']} (swap: {t['show_swap']})")

    lines.append("\n📸 Пришли фото для тестирования оценки!")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_debug_gaps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать gap analysis гардероба: пробелы, orphans, combo potential."""
    user = context.user_data.get("db_user")
    if not user or user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    from bot.handlers.wardrobe import _get_owner
    from db.crud.wardrobe import get_owner_items
    from services.scoring import get_wardrobe_gaps, get_wardrobe_balance_insight

    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    lines = [f"📋 *Debug: Gap Analysis* ({len(items)} вещей)\n"]

    # Category breakdown
    from collections import Counter
    cg_counts = Counter(getattr(i, "category_group", "?") for i in items)
    lines.append("*Категории:*")
    for cg, count in cg_counts.most_common():
        lines.append(f"  {cg}: {count}")

    # Gaps
    gaps = get_wardrobe_gaps(items)
    if gaps:
        lines.append("\n*Пробелы:*")
        for gap in gaps:
            lines.append(f"  • {gap}")
    else:
        lines.append("\n✅ Пробелов нет!")

    # Balance
    balance = get_wardrobe_balance_insight(items)
    if balance:
        lines.append(f"\n*Баланс:* {balance}")

    # Color distribution
    colors = Counter(getattr(i, "color", "?") for i in items)
    top_colors = colors.most_common(5)
    lines.append("\n*Топ-5 цветов:*")
    for color, count in top_colors:
        lines.append(f"  {color}: {count}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_debug_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать стилистический профиль: colortype, palette, style_preferences."""
    user = context.user_data.get("db_user")
    if not user or user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    lines = ["💅 *Debug: Style Profile*\n"]

    # Colortype + palette
    ct = user.colortype or "не задан"
    lines.append(f"Цветотип: `{ct}`")

    if ct and ct != "не задан":
        try:
            from worker.tasks.style_config import COLORTYPE_PALETTES
            palette = COLORTYPE_PALETTES.get(ct, {})
            if palette:
                lines.append("Палитра:")
                for slot, colors in list(palette.items())[:4]:
                    lines.append(f"  {slot}: {', '.join(colors[:3])}")
            else:
                lines.append(f"⚠️ Палитра для '{ct}' не найдена")
        except Exception as e:
            lines.append(f"Ошибка палитры: {e}")

    # Style preferences
    prefs = getattr(user, "style_preferences", None) or {}
    if prefs:
        lines.append(f"\nСтиль: `{prefs.get('style', 'не задан')}`")
        avoid = prefs.get("avoid", [])
        if avoid:
            lines.append(f"Избегать: {', '.join(avoid)}")
        prefer = prefs.get("prefer", [])
        if prefer:
            lines.append(f"Люблю: {', '.join(prefer)}")
    else:
        lines.append("\nstyle\\_preferences: не заданы")

    # Body type
    bt = getattr(user, "body_type", None) or "не задан"
    lines.append(f"\nТип фигуры: `{bt}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_debug_wardrobe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Полная статистика гардероба: slots, scores, versatility."""
    user = context.user_data.get("db_user")
    if not user or user.telegram_id not in settings.admin_ids_list:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    from bot.handlers.wardrobe import _get_owner
    from db.crud.wardrobe import get_owner_items
    from services.scoring import calc_item_versatility, classify_role

    owner_id, owner_type = await _get_owner(user, context)
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)

    lines = [f"👗 *Debug: Wardrobe Stats* ({len(items)} вещей)\n"]

    if not items:
        lines.append("Гардероб пуст.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # Score distribution
    scores = [float(i.score_item) for i in items if getattr(i, "score_item", None)]
    if scores:
        avg_score = sum(scores) / len(scores)
        lines.append(f"*Средний скор:* {avg_score:.1f}/10")
        lines.append(f"*Мин/Макс:* {min(scores):.1f} / {max(scores):.1f}")

    # Roles
    from collections import Counter
    roles = Counter()
    for item in items:
        role = classify_role(getattr(item, "type", ""), getattr(item, "color", ""))
        roles[role] += 1
    lines.append(f"\n*Роли:* base={roles.get('base', 0)}, accent={roles.get('accent', 0)}, statement={roles.get('statement', 0)}")

    # Seasons
    season_counts = Counter()
    for item in items:
        for s in (getattr(item, "season", None) or []):
            season_counts[s] += 1
    lines.append(f"*Сезоны:* {dict(season_counts.most_common())}")

    # Top 5 most versatile
    if len(items) >= 5:
        versatility = [(i, calc_item_versatility(i, items)) for i in items]
        versatility.sort(key=lambda x: x[1], reverse=True)
        lines.append("\n*Топ-5 универсальных:*")
        for item, v in versatility[:5]:
            lines.append(f"  {item.type} {item.color} — {v} сочетаний")

    # Least versatile (orphans)
    if len(items) >= 8:
        orphans = [(i, v) for i, v in versatility if v < 2]
        if orphans:
            lines.append(f"\n*Одинокие ({len(orphans)}):*")
            for item, v in orphans[:3]:
                lines.append(f"  {item.type} {item.color} — {v} сочетаний")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
