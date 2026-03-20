"""Gap analysis — шоппинг-лист по гардеробу."""
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()

_SEASON_MAP = {
    12: "зима", 1: "зима", 2: "зима",
    3: "весна", 4: "весна", 5: "весна",
    6: "лето", 7: "лето", 8: "лето",
    9: "осень", 10: "осень", 11: "осень",
}

# Творительный падеж для "Что стоит купить этой {season}"
_SEASON_INSTRUMENTAL = {
    "зима": "зимой", "весна": "весной",
    "лето": "летом", "осень": "осенью",
}


def _get_current_season(tz_str: str) -> str:
    try:
        import pytz
        tz = pytz.timezone(tz_str)
        month = datetime.now(tz).month
    except Exception:
        month = datetime.now(timezone.utc).month
    season = _SEASON_MAP.get(month, "весна")
    return _SEASON_INSTRUMENTAL.get(season, season)


async def build_shopping_list(
    user, items: list, redis, *, child=None
) -> Optional[str]:
    """
    Анализирует гардероб и возвращает шоппинг-лист.

    Returns:
        "lock"  — другой запрос уже выполняется
        ""      — гардероб ок, ничего докупать не нужно
        None    — ошибка или мало вещей (< 5)
        str     — текст шоппинг-листа
    """
    items = items or []

    if len(items) < 5:
        return None

    # Cache version — bump when prompt/logic changes to invalidate old cache
    _CACHE_VER = "v5"
    lock_key = f"gap_lock:{user.id}"
    cache_key = f"gap_analysis:{_CACHE_VER}:{user.id}"

    # Проверить lock
    if await redis.get(lock_key):
        return "lock"

    # Проверить кэш
    cached = await redis.get(cache_key)
    if cached:
        return cached.decode() if isinstance(cached, bytes) else cached

    # Определить сезон (именительный для промпта)
    try:
        import pytz
        _tz = pytz.timezone(user.timezone or "Europe/Vilnius")
        _month = datetime.now(_tz).month
    except Exception:
        _month = datetime.now(timezone.utc).month
    season = _SEASON_MAP.get(_month, "весна")

    # Owner context — детальный для ребёнка
    segment = getattr(user, "segment", "") or ""
    is_child_wardrobe = segment in ("mom_girl", "mom_boy")

    if is_child_wardrobe and child is not None:
        from datetime import date as _date
        child_parts: list[str] = []
        gender = getattr(child, "gender", "girl")
        gender_word = "девочка" if gender == "girl" else "мальчик"
        child_parts.append(f"Детский гардероб, {gender_word}")
        if getattr(child, "birthdate", None):
            age_days = (_date.today() - child.birthdate).days
            age_years = age_days // 365
            age_months = (age_days % 365) // 30
            if age_years < 2:
                child_parts.append(f"{age_years} г. {age_months} мес.")
            else:
                child_parts.append(f"{age_years} лет")
        if getattr(child, "current_size", None):
            child_parts.append(f"размер одежды {child.current_size}")
        if getattr(child, "shoe_size", None):
            child_parts.append(f"обувь {child.shoe_size}")
        owner_context = ", ".join(child_parts) + "."
    elif is_child_wardrobe:
        owner_context = "Детский гардероб."
    else:
        body_type = getattr(user, "body_type", None)
        owner_context = "Взрослая женщина."
        if body_type:
            owner_context = f"Взрослая женщина, тип фигуры: {body_type}."

    # Топ-50 по score_item DESC (None → в конец)
    sorted_items = sorted(
        items,
        key=lambda x: (
            getattr(x, "score_item", None) is None,
            -(getattr(x, "score_item", None) or 0),
        ),
    )[:50]

    # Только нужные поля для промпта
    items_lines = "\n".join(
        f"- {getattr(i, 'category_group', '')} | {getattr(i, 'type', '')} | "
        f"{getattr(i, 'color', '')} | сезон: {getattr(i, 'season', [])}"
        for i in sorted_items
    )

    colortype = user.colortype or ""
    colortype_str = ""
    if colortype:
        colortype_str = f"\nЦветотип: {colortype}."
        # Подсказка по палитре из COLORTYPE_PALETTES
        try:
            from worker.tasks.style_config import COLORTYPE_PALETTES
            palette = COLORTYPE_PALETTES.get(colortype, {})
            if palette:
                color_hints = []
                for slot, colors in list(palette.items())[:4]:
                    color_hints.append(f"{slot}: {', '.join(colors[:2])}")
                colortype_str += f" Рекомендуемые цвета: {'; '.join(color_hints)}."
        except Exception:
            pass

    # Контекст из скоринговых матриц и SEASON_SLOT_TYPES
    child_instruction = ""
    scoring_context = ""

    if is_child_wardrobe and child is not None:
        gender = getattr(child, "gender", "girl")
        gender_word = "девочки" if gender == "girl" else "мальчика"

        # Матрица скоринга — какие критерии важны для этого возраста
        from services.scoring import matrix_name_for_owner
        matrix_name = matrix_name_for_owner(user, child)

        try:
            from db.base import AsyncReadSession as _ARS
            from db.models.scoring_matrix import ScoringMatrix as _SM
            from sqlalchemy import select as _sel
            async with _ARS() as _sess:
                _res = await _sess.execute(
                    _sel(_SM).where(_SM.name == matrix_name, _SM.is_active.is_(True))
                )
                _matrix = _res.scalar_one_or_none()
            if _matrix:
                criteria_keys = [k for k in _matrix.criteria if not k.startswith("_")]
                scoring_context = f"Критерии оценки для {matrix_name}: {', '.join(criteria_keys)}.\n"
        except Exception:
            pass

        # Базовые вещи по текущей погоде из SEASON_SLOT_TYPES
        from worker.tasks.style_config import SEASON_SLOT_TYPES, get_temp_regime
        from services.brief_weather import _geocode_city, _get_weather

        expected_items: list[str] = []
        try:
            coords = await _geocode_city(user.city or "")
            if coords:
                w = await _get_weather(coords[0], coords[1], user.timezone or "Europe/Vilnius")
                _temp = w.get("temp_now") or w.get("temp_morning") or 10.0
            else:
                _temp = 10.0
            regime = get_temp_regime(_temp)
            for slot, regimes in SEASON_SLOT_TYPES.items():
                item_type = regimes.get(regime)
                if item_type:
                    expected_items.append(f"{slot}: {item_type}")
        except Exception:
            pass

        expected_str = ""
        if expected_items:
            expected_str = f"По текущей погоде ребёнку нужно: {', '.join(expected_items)}.\n"

        child_instruction = (
            f"ВАЖНО: это детский гардероб для {gender_word}. "
            f"Рекомендуй ТОЛЬКО детские вещи подходящие по возрасту и размеру. "
            f"Практичные вещи важнее модных. Дети быстро растут. "
            f"Не рекомендуй взрослые вещи (рубашки, пиджаки, офисная одежда).\n"
            f"{scoring_context}"
            f"{expected_str}"
        )

    # Промпт — простой и прямолинейный (Haiku теряет фокус на длинных промптах)
    if is_child_wardrobe and child is not None:
        from datetime import date as _date2
        gender = getattr(child, "gender", "girl")
        child_name = getattr(child, "name", "ребёнок")
        age_years = 3
        if getattr(child, "birthdate", None):
            age_years = (_date2.today() - child.birthdate).days // 365
        gender_word = "девочка" if gender == "girl" else "мальчик"

        system_prompt = (
            f"Ты помогаешь маме купить одежду для ребёнка {child_name} ({gender_word}, {age_years} лет). "
            f"Отвечай ТОЛЬКО нумерованным списком. Без заголовков, без markdown, без пояснений."
        )
        # Few-shot example для правильного формата и детских вещей
        user_prompt = (
            f"Пример для мальчика 4 лет весной:\n"
            f"1. Ветровка детская голубая\n"
            f"2. Толстовка с капюшоном серая\n"
            f"3. Джоггеры детские тёмно-синие\n"
            f"4. Кроссовки детские белые\n"
            f"5. Шапка тонкая серая\n\n"
            f"Теперь для {child_name} ({gender_word}, {age_years} лет).\n"
            f"В гардеробе: {items_lines}\n"
            f"Сезон: {season}.\n"
            f"Напиши 5-7 ДЕТСКИХ вещей для {'девочки' if gender == 'girl' else 'мальчика'} {age_years} лет с цветом:"
        )
    else:
        system_prompt = "Ты стилист. Помогаешь составить список покупок. Отвечай нумерованным списком на русском."
        user_prompt = (
            f"{owner_context}{colortype_str}\n"
            f"Сезон: {season}.\n\n"
            f"Гардероб ({len(sorted_items)} вещей):\n{items_lines}\n\n"
            f"Каких вещей не хватает на этот сезон? Напиши 5-7 вещей с цветом."
        )

    # Установить lock перед вызовом Claude
    await redis.set(lock_key, "1", ex=60)

    try:
        from core.anthropic_client import get_anthropic_pool
        pool = get_anthropic_pool()

        # Sonnet for children (better at following constraints), Haiku for adults
        _model = "claude-sonnet-4-6" if is_child_wardrobe else "claude-haiku-4-5-20251001"
        response = await pool.create_message(
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=400,
            model=_model,
            system=system_prompt,
        )

        result = response.content[0].text.strip() if response.content else ""

        # Сохранить в кэш на 24 часа
        await redis.set(cache_key, result, ex=86400)

        logger.info(
            "gap_analysis.done",
            user_id=str(user.id),
            items_count=len(sorted_items),
            season=season,
        )
        return result

    except Exception as e:
        logger.error("gap_analysis.error", user_id=str(user.id), error=str(e))
        return None

    finally:
        await redis.delete(lock_key)
