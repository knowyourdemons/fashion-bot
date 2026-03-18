"""
Текстовые комментарии от стилиста Касси (через Haiku).
Заменяют числовой скор в интерфейсе — юзер никогда не видит цифру.
"""
import structlog

logger = structlog.get_logger()


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
        "Ты стилист Касси. Генерируй короткий комментарий (2-3 предложения) о вещи.\n\n"
        "Правила:\n"
        "- НИКОГДА не упоминай числовой скор\n"
        "- Всегда позитивный фрейминг: каждая вещь хороша для чего-то\n"
        "- Если вещь слабая — найди правильный контекст (дом, дача, прогулка)\n"
        "- Если есть проблема с цветотипом — подскажи МЯГКО что идёт лучше\n"
        "- Укажи роль вещи: базовая / акцентная / для особого случая\n"
        f"- Тон: {tone or 'дружелюбный стилист'}\n"
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
) -> str:
    """Генерирует текстовый комментарий об образе для брифа (Haiku, ~$0.003)."""
    system = (
        "Ты стилист Касси. Напиши короткий комментарий (2-3 предложения) об образе на день.\n\n"
        "Правила:\n"
        "- НИКОГДА не упоминай числовой скор\n"
        "- Включи 1 конкретный совет (добавь/поменяй/обрати внимание)\n"
        f"- Если wow — добавь эмоцию! Используй один из wow-шаблонов: {wow_messages}\n"
        f"- Учти контекст: {context}\n"
        f"- Тон: {tone or 'дружелюбный стилист'}"
    )

    items_text = ", ".join(outfit_items) if outfit_items else "вещи подобраны"
    prompt = f"Образ: {items_text}."
    if weather:
        prompt += f" Погода: {weather}."
    if child_name:
        gender_label = "девочки" if gender == "girl" else "мальчика"
        prompt += f" Для {gender_label} {child_name}, {age} лет."
    if is_wow:
        prompt += " Это WOW-образ!"

    try:
        response = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=200,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning("scoring_comment.outfit_failed", error=str(e))
        if is_wow and wow_messages:
            return wow_messages[0]
        return f"Образ подобран под погоду {weather}. Хорошего дня! ✨"
