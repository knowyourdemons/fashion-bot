"""
Текстовые комментарии от стилиста Касси (через Haiku).
Заменяют числовой скор в интерфейсе — юзер никогда не видит цифру.

Variable reward: 20+ fallback templates per segment, rotated with Redis dedup.
"""
import hashlib
import random
import structlog

logger = structlog.get_logger()

# ── Fallback templates by segment ─────────────────────────────────────────

_TEMPLATES_MOM = [
    "Классная пара! Тепло и удобно 👌",
    "Отличный выбор — и красиво, и практично!",
    "Удобно, стильно, мама одобряет ✨",
    "Гармоничное сочетание! Мягкие цвета — то что надо 🌸",
    "Этот образ точно понравится — комфорт и стиль!",
    "Нежные тона — идеально для прогулки!",
    "Практично и со вкусом — редкое сочетание 👏",
    "Уютный образ на каждый день!",
    "Хорошее сочетание! Мягкие цвета отлично смотрятся вместе 🎨",
    "Готово к садику и прогулке! Тепло и красиво.",
    "Образ дня — удобство на первом месте, стиль на втором!",
    "Функциональный и стильный — мечта мамы!",
    "Цвета подобраны с душой — гармония! 💕",
    "Просто и со вкусом. Лучший стиль — незаметный стиль.",
    "Тёплый и уютный образ — то что надо!",
    "Практичная классика — всегда выручает!",
    "Отличная комбинация! Комфорт и красота в одном 🌟",
    "Мягкие цвета создают настроение — образ удался!",
    "Каждая вещь на своём месте — образ собран!",
    "Стильно и по погоде — два в одном! 👍",
    "Удачное сочетание текстур и цветов!",
    "Образ, в котором хочется гулять весь день 🌿",
]

_TEMPLATES_NO_KIDS = [
    "Изысканное сочетание для весны ✨",
    "Стильная комбинация — чувствуется вкус!",
    "Модный и актуальный образ! 🔥",
    "Цвета играют — отличная палитра!",
    "Элегантно и современно — люблю!",
    "Образ с характером — ты точно выделишься! ✨",
    "Трендовое сочетание — всё в точку!",
    "Минимализм и стиль — идеальный баланс.",
    "Этот образ говорит: я знаю что ношу 👑",
    "Текстуры и цвета — красивая игра!",
    "Свежий и актуальный look!",
    "Утончённое сочетание — браво! 🎨",
    "Лёгкий шик — то что модно сейчас.",
    "Образ для уверенных — стильно и точно.",
    "Классика с изюминкой — так и надо!",
    "Цветовая гармония на высоте! 💫",
    "Продуманный образ — каждая деталь работает.",
    "Современная элегантность — вне трендов.",
    "Стиль с характером! Нравится подход ✨",
    "Актуальное сочетание — модные журналы одобряют!",
    "Лаконично и со вкусом — лучший комплимент.",
    "Образ, который запомнят 🌟",
]


def _get_templates(segment: str) -> list[str]:
    """Return template list for segment."""
    if segment in ("mom_girl", "mom_boy"):
        return _TEMPLATES_MOM
    return _TEMPLATES_NO_KIDS


async def _pick_unique_template(
    redis, user_id: str, segment: str,
) -> str:
    """Pick a template that wasn't used in the last 48h (Redis dedup)."""
    templates = _get_templates(segment)
    redis_key = f"last_comment_hash:{user_id}"

    last_hash = None
    if redis:
        try:
            last_hash = await redis.get(redis_key)
            if isinstance(last_hash, bytes):
                last_hash = last_hash.decode()
        except Exception:
            pass

    # Try to pick a template different from last
    random.shuffle(templates)
    for tmpl in templates:
        h = hashlib.md5(tmpl.encode()).hexdigest()[:8]
        if h != last_hash:
            # Store hash with 48h TTL
            if redis:
                try:
                    await redis.set(redis_key, h, ex=172800)
                except Exception:
                    pass
            return tmpl

    # All same hash (impossible but safe)
    return templates[0]


async def generate_item_comment(
    pool,
    item_type: str,
    item_color: str,
    score: float,
    role: str,
    colortype: str | None,
    colortype_match: bool,
    wardrobe_summary: str,
    gender: str | None,
    age: int | None,
    child_name: str | None,
    tone: str,
) -> str:
    """Генерирует текстовый комментарий о добавленной вещи (Haiku, ~$0.002)."""
    system = (
        "Ты Касси — подруга-стилист. Говоришь тепло и с энтузиазмом.\n\n"
        "Правила:\n"
        "- НИКОГДА не упоминай числовой скор\n"
        "- Всегда позитивный: каждая вещь хороша для чего-то\n"
        "- Если вещь слабая — найди правильный контекст (дом, дача, прогулка)\n"
        "- Если есть проблема с цветотипом — подскажи мягко: 'попробуй с ...'\n"
        "- ЗАПРЕЩЁННЫЕ слова: критически, обязательно, срочно, не хватает, нужно, должна, нельзя\n"
        "- ВМЕСТО ЭТОГО: попробуй, добавь, будет здорово, классно смотрится\n"
        "- Максимум 2 предложения. Короче = лучше.\n"
        f"- Тон: {tone or 'тёплый, позитивный'}\n"
        f"Контекст гардероба: {wardrobe_summary or 'гардероб пополняется'}"
    )

    prompt = f"Вещь: {item_type}, цвет {item_color}."
    if colortype:
        match_text = "подходит" if colortype_match else "не в палитре"
        prompt += f" Цветотип: {colortype} ({match_text})."
    if child_name:
        gender_label = "девочки" if gender == "girl" else "мальчика"
        prompt += f" Для {gender_label} {child_name} ({age} лет)."
    prompt += f" Роль вещи: {role}."

    try:
        response = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=150,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning("scoring_comment.item_failed", error=str(e))
        role_labels = {"base": "базовая", "accent": "акцентная", "statement": "для особого случая"}
        return f"Хорошая {role_labels.get(role, 'универсальная')} вещь — {item_type} {item_color} найдёт своё место в гардеробе ✨"


async def generate_outfit_comment(
    pool,
    outfit_items: list[str],
    weather: str,
    context: str,
    score: float,
    is_wow: bool,
    child_name: str | None,
    gender: str | None,
    age: int | None,
    tone: str,
    wow_messages: list[str],
    colortype: str | None = None,
    segment: str | None = None,
    redis=None,
    item_count: int | None = None,
    user_id: str | None = None,
) -> str:
    """Генерирует текстовый комментарий об образе для брифа (Haiku, ~$0.003).

    Now includes colortype awareness, variable reward templates,
    and item-count-aware commentary.

    Args:
        item_count: number of real wardrobe items in outfit (affects comment style)
    """
    _n = item_count if item_count is not None else len(outfit_items)

    # Build colortype instruction
    colortype_line = ""
    if colortype:
        colortype_line = f"\n- Цветотип: {colortype}. Упоминай подходящие цвета из палитры цветотипа."

    # Item-count-aware instructions
    if _n <= 2:
        count_instruction = (
            "\n- В гардеробе мало вещей (1-2). НЕ говори слово 'образ'. "
            "Похвали конкретную вещь и мотивируй сфоткать ещё: 'Отличные штанишки! Сфоткай кофту — соберу полный образ!'"
        )
    elif _n <= 5:
        count_instruction = (
            "\n- В гардеробе 3-5 вещей. Комментируй сочетание тех вещей что есть. "
            "Можно сказать 'образ', но упомяни конкретные вещи."
        )
    else:
        count_instruction = ""

    system = (
        "Ты Касси — подруга-стилист. Говоришь тепло и с энтузиазмом.\n\n"
        "Правила:\n"
        "- НИКОГДА не упоминай числовой скор\n"
        "- Включи 1 конкретный позитивный совет\n"
        "- ЗАПРЕЩЁННЫЕ слова: критически, обязательно, срочно, не хватает, нужно, должна, нельзя\n"
        "- ВМЕСТО ЭТОГО: попробуй, добавь, будет здорово, классно смотрится, как тебе идея\n"
        "- Позитивный framing: 'добавь куртку — будет уютнее' НЕ 'без куртки холодно'\n"
        "- Максимум 2 предложения. Короче = лучше.\n"
        f"- Если wow — добавь эмоцию! Используй один из: {wow_messages}\n"
        f"- Контекст: {context}\n"
        f"- Тон: {tone or 'тёплый, позитивный'}"
        f"{colortype_line}"
        f"{count_instruction}"
    )

    items_text = ", ".join(outfit_items) if outfit_items else "вещи подобраны"
    prompt = f"Вещи: {items_text}. Всего вещей в образе: {_n}."
    if weather:
        prompt += f" Погода: {weather}."
    if child_name:
        gender_label = "девочки" if gender == "girl" else "мальчика"
        prompt += f" Для {gender_label} {child_name}, {age} лет."
    if colortype:
        prompt += f" Цветотип: {colortype}."
    if is_wow:
        prompt += " Это WOW-образ!"

    try:
        response = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=150,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning("scoring_comment.outfit_failed", error=str(e))
        if is_wow and wow_messages:
            return wow_messages[0]
        # Variable reward: use segment-specific template with dedup
        _seg = segment or "no_kids"
        try:
            return await _pick_unique_template(redis, user_id or "fallback", _seg)
        except Exception:
            return f"Образ подобран под погоду {weather}. Хорошего дня! ✨"
