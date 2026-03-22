"""
Оценка образа по фото — профессиональный стилистический анализ.

Пользователь присылает фото в полный рост → Vision анализирует образ
по 6 измерениям профессиональной стилистики → структурированный фидбек.

Ключевые принципы:
- Оцениваем ОДЕЖДУ, не тело (никогда не комментируем фигуру)
- Начинаем с позитива (что работает)
- Конкретные и actionable рекомендации
- Максимум 2 замены из гардероба
- Тон: подруга-стилист (тёплый, поддерживающий)
"""
import json
import re
import structlog

from services.color_harmony import score_outfit_colors, is_neutral, color_compatibility

logger = structlog.get_logger()


# ── Evaluation dimensions (professional stylist framework) ────────────────

EVAL_DIMENSIONS = {
    "color_harmony": {
        "weight": 25,
        "label": "Цветовая гармония",
        "criteria": [
            "Цвета сочетаются (monochrome/analogous/complementary/accent)?",
            "Не больше 3 цветов (правило 60-30-10)?",
            "Цвета у лица подходят к тону кожи/волос/глаз?",
            "Контраст образа соответствует контрасту внешности?",
        ],
    },
    "proportions": {
        "weight": 25,
        "label": "Пропорции и силуэт",
        "criteria": [
            "Баланс объёмов (свободное + облегающее)?",
            "Правило третей (1/3 верх + 2/3 низ или наоборот)?",
            "Длины на выгодных точках (не режут на широком месте)?",
            "Силуэт удлиняет, не сжимает?",
        ],
    },
    "style_coherence": {
        "weight": 20,
        "label": "Стилевое единство",
        "criteria": [
            "Все вещи в одном стилистическом ключе?",
            "Нет конфликта формальностей (спорт + офис)?",
            "Текстуры дополняют друг друга?",
            "Образ рассказывает 'историю' или настроение?",
        ],
    },
    "occasion_fit": {
        "weight": 15,
        "label": "Уместность",
        "criteria": [
            "Формальность подходит для ситуации?",
            "Сезонность и погода учтены?",
            "Практичность для активности?",
        ],
    },
    "details_polish": {
        "weight": 10,
        "label": "Детали и завершённость",
        "criteria": [
            "Аксессуары дополняют (не перегружают)?",
            "Обувь подходит по стилю и цвету?",
            "Есть focal point (одна точка внимания)?",
        ],
    },
    "creativity": {
        "weight": 5,
        "label": "Индивидуальность",
        "criteria": [
            "Есть интересный или неожиданный элемент?",
            "Личность просвечивает через образ?",
        ],
    },
}


# ── Score tiers ──────────────────────────────────────────────────────────

def score_to_tier(score: float) -> dict:
    """Convert numeric score to tier with emoji and label."""
    if score >= 9.0:
        return {"tier": "wow", "emoji": "🔥", "label": "Wow-образ!", "show_swap": False}
    if score >= 7.5:
        return {"tier": "great", "emoji": "✨", "label": "Отличный образ!", "show_swap": False}
    if score >= 6.0:
        return {"tier": "good", "emoji": "👍", "label": "Хороший образ", "show_swap": True}
    if score >= 4.5:
        return {"tier": "adjust", "emoji": "💡", "label": "Есть потенциал", "show_swap": True}
    return {"tier": "boost", "emoji": "💪", "label": "Давай усилим!", "show_swap": True}


# ── Build evaluation prompt ──────────────────────────────────────────────

def build_eval_prompt(
    *,
    owner_type: str = "user",
    wardrobe_items: list | None = None,
    colortype: str | None = None,
    body_type: str | None = None,
    segment: str | None = None,
    child_age: int | None = None,
    occasion: str | None = None,
) -> str:
    """Build a professional evaluation system prompt.

    Returns a prompt that makes Vision evaluate the outfit across
    6 professional dimensions and return structured JSON + text feedback.
    """
    # Wardrobe context for swap suggestions
    if wardrobe_items:
        top_items = sorted(
            [i for i in wardrobe_items if getattr(i, "score_item", None)],
            key=lambda x: float(x.score_item),
            reverse=True,
        )[:20]
        wardrobe_context = ", ".join(
            f"{getattr(i, 'type', '')} {getattr(i, 'color', '')}" for i in top_items
        )
    else:
        wardrobe_context = ""

    # Colortype context
    colortype_hint = ""
    if colortype:
        colortype_hint = f"\nЦветотип пользователя: {colortype}. Учитывай при оценке цветов у лица."

    # Body type context
    body_hint = ""
    if body_type:
        body_hint = f"\nТип фигуры: {body_type}. Оценивай пропорции с учётом этого."

    # Segment-specific tone
    if owner_type == "child":
        age_str = f" ({child_age} лет)" if child_age else ""
        persona = f"детской моды. Оцени образ ребёнка{age_str} на фото"
        tone_rules = (
            "- Безопасность на первом месте (фурнитура, завязки, длины)\n"
            "- Практичность: легко одеть/снять\n"
            "- Комфорт и свобода движений\n"
            "- Тон: тёплый, поддерживающий маму"
        )
        dimensions_override = {
            "safety": {"weight": 20, "label": "Безопасность"},
            "comfort": {"weight": 20, "label": "Комфорт и практичность"},
            "color_harmony": {"weight": 20, "label": "Цветовая гармония"},
            "weather_fit": {"weight": 20, "label": "По сезону и погоде"},
            "age_appropriateness": {"weight": 15, "label": "По возрасту"},
            "creativity": {"weight": 5, "label": "Индивидуальность"},
        }
        dim_text = "\n".join(
            f"  - {v['label']} ({v['weight']}%)" for v in dimensions_override.values()
        )
    else:
        persona = "персональным стилистом. Оцени образ взрослой женщины на фото"
        segment_label = {
            "mom_girl": "мама девочки",
            "mom_boy": "мама мальчика",
            "pregnant": "беременная",
            "no_kids": "женщина для себя",
        }.get(segment or "", "")

        if segment in ("mom_girl", "mom_boy"):
            tone_rules = (
                "- Практичность важна: мама с ребёнком, удобство в приоритете\n"
                "- Но стиль тоже важен — мама заслуживает выглядеть красиво!\n"
                "- Тон: подруга-стилист, тёплый и поддерживающий\n"
                "- Не перегружай советами — максимум 2 замены"
            )
        elif segment == "pregnant":
            tone_rules = (
                "- Комфорт и удобство — приоритет\n"
                "- Учитывай, что вещи должны быть адаптивными\n"
                "- Тон: заботливый и поддерживающий"
            )
        else:
            tone_rules = (
                "- Стиль и гармония — ключевое\n"
                "- Оценивай как профессиональный стилист\n"
                "- Тон: подруга-стилист, вдохновляющий\n"
                "- Приветствуй смелые сочетания, если они работают"
            )

        if segment_label:
            persona += f" (сегмент: {segment_label})"

        dim_text = "\n".join(
            f"  - {v['label']} ({v['weight']}%)" for v in EVAL_DIMENSIONS.values()
        )

    # Occasion hint
    occasion_hint = ""
    if occasion:
        occasion_hint = f"\nОбраз для: {occasion}. Оценивай уместность с учётом этого."

    prompt = f"""Ты {persona}.

══════════════════════════════════════
ПРАВИЛА ОЦЕНКИ
══════════════════════════════════════

ФОТО:
- Если на фото виден только фрагмент (только ноги, только верх): честно напиши и оцени видимое
- Для полной оценки нужно фото в полный рост
- Оценивай ВСЕ видимые элементы: одежда, обувь, аксессуары
- Если на фото нет человека или нет одежды — напиши об этом

ГЛАВНОЕ ПРАВИЛО: оценивай ОДЕЖДУ, никогда не комментируй тело.

ПРАВИЛО ПРОПОРЦИЙ:
- Баланс объёмов: свободное + облегающее лучше чем всё свободное или всё обтягивающее
- Правило третей: 1/3 верх + 2/3 низ (или наоборот) создаёт гармонию
- Не режь силуэт на самом широком месте (юбка до колена лучше чем до середины икры)
- Зеркальное селфи — игнорируй руку с телефоном, оценивай одежду
{colortype_hint}{body_hint}{occasion_hint}

ИЗМЕРЕНИЯ ОЦЕНКИ:
{dim_text}

ТОНАЛЬНОСТЬ:
{tone_rules}

══════════════════════════════════════
ФОРМАТ ОТВЕТА — СТРОГО JSON
══════════════════════════════════════

Верни ТОЛЬКО JSON, без markdown, без пояснений:
{{
  "is_outfit": true,
  "is_partial": false,
  "score": 7.5,
  "dimensions": {{
    "color_harmony": 8,
    "proportions": 7,
    "style_coherence": 8,
    "occasion_fit": 7,
    "details_polish": 6,
    "creativity": 7
  }},
  "detected_items": [
    {{"type": "блузка", "color": "белый", "category_group": "top"}},
    {{"type": "джинсы", "color": "синий", "category_group": "bottom"}}
  ],
  "strengths": "Цвета отлично сочетаются — белый и синий создают свежий и чистый образ.",
  "improvements": "Добавь один яркий аксессуар (шарф или сумку) — он станет focal point.",
  "swaps": [
    {{
      "current": "кроссовки белые",
      "suggested": "лоферы бежевые",
      "reason": "лоферы поднимут формальность и подчеркнут стиль smart casual"
    }}
  ],
  "overall_vibe": "Свежий повседневный образ с отличной цветовой базой"
}}

ПРАВИЛА JSON:
- "is_outfit": true если на фото человек в одежде, false если flat lay или нет человека
- "is_partial": true если видна только часть образа
- "score": от 1 до 10, с одним десятичным
- "dimensions": каждое от 1 до 10
- "strengths": 1-2 предложения — что работает (ВСЕГДА начинай с позитива)
- "improvements": 1-2 конкретных совета (actionable, не абстрактных)
- "swaps": массив замен из гардероба (0-2 шт). ПУСТОЙ если score ≥ 8 или гардероб пуст
- "overall_vibe": настроение образа в 3-5 словах
- "detected_items": какие вещи видны на фото

{"ГАРДЕРОБ для замен (используй ТОЛЬКО эти вещи):" + chr(10) + wardrobe_context if wardrobe_context else "Гардероб пуст — давай общие рекомендации без конкретных замен."}

Язык: русский."""

    return prompt


# ── Parse evaluation response ────────────────────────────────────────────

def parse_eval_response(raw: str) -> dict | None:
    """Parse JSON from Vision response, handling markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # Try to find JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return _validate_eval(data)
    except json.JSONDecodeError:
        logger.warning("outfit_eval.json_parse_failed", raw=raw[:300])
        return None


def _validate_eval(data: dict) -> dict:
    """Validate and clamp evaluation data."""
    # Clamp score
    score = float(data.get("score", 5.0))
    data["score"] = max(1.0, min(10.0, round(score, 1)))

    # Clamp dimensions
    dims = data.get("dimensions", {})
    for key in dims:
        dims[key] = max(1, min(10, int(dims.get(key, 5))))
    data["dimensions"] = dims

    # Ensure required fields
    data.setdefault("is_outfit", True)
    data.setdefault("is_partial", False)
    data.setdefault("strengths", "")
    data.setdefault("improvements", "")
    data.setdefault("swaps", [])
    data.setdefault("overall_vibe", "")
    data.setdefault("detected_items", [])

    # Limit swaps to 2
    if len(data["swaps"]) > 2:
        data["swaps"] = data["swaps"][:2]

    return data


# ── Format evaluation for user ───────────────────────────────────────────

def format_eval_text(eval_data: dict, owner_type: str = "user") -> str:
    """Format structured evaluation into user-friendly text message.

    Rules:
    - Never show numeric score (only tier label)
    - Start with what works
    - Max 2 improvements
    - Warm, supportive tone
    """
    if not eval_data:
        return "Не удалось оценить образ. Попробуй прислать фото в полный рост на светлом фоне."

    # Not an outfit photo
    if not eval_data.get("is_outfit"):
        return (
            "🤔 На фото не вижу образа — пришли фото человека в одежде в полный рост!\n\n"
            "💡 Совет: хорошее освещение и нейтральный фон помогут оценить точнее."
        )

    score = eval_data.get("score", 5.0)
    tier = score_to_tier(score)
    is_partial = eval_data.get("is_partial", False)

    lines = []

    # Header
    if is_partial:
        lines.append("👀 Вижу только часть образа — оцениваю видимое:\n")

    lines.append(f"{tier['emoji']} {tier['label']}")

    # Overall vibe
    vibe = eval_data.get("overall_vibe", "")
    if vibe:
        lines.append(f"Настроение: {vibe}\n")

    # Strengths (always show)
    strengths = eval_data.get("strengths", "")
    if strengths:
        lines.append(f"✅ {strengths}")

    # Improvements (only if score < 8)
    improvements = eval_data.get("improvements", "")
    if improvements and tier["show_swap"]:
        lines.append(f"\n💡 {improvements}")

    # Swaps from wardrobe
    swaps = eval_data.get("swaps", [])
    if swaps and tier["show_swap"]:
        lines.append("")
        for swap in swaps[:2]:
            current = swap.get("current", "?")
            suggested = swap.get("suggested", "?")
            reason = swap.get("reason", "")
            lines.append(f"👗 {current} → {suggested}")
            if reason:
                lines.append(f"   {reason}")

    # Partial photo CTA
    if is_partial:
        lines.append("\n📸 Пришли фото в полный рост для полной оценки!")

    # CTA after evaluation
    if not is_partial:
        if tier["show_swap"]:
            lines.append("\n✨ Хочешь собрать образ из гардероба? Нажми «Что надеть»")
        elif score >= 9.0:
            lines.append("\n🎉 Сохрани этот образ в избранное!")

    return "\n".join(lines)


# ── Cross-validate with local scoring ────────────────────────────────────

def cross_validate_colors(
    detected_items: list[dict],
    eval_score: float,
) -> float:
    """Cross-validate Vision color assessment with local color_harmony.

    If local scoring disagrees significantly with Vision, adjust.
    This prevents hallucinated "great harmony" on clashing combos.
    """
    eval_score = float(eval_score)
    if not detected_items or len(detected_items) < 2:
        return eval_score

    # Build mock items for score_outfit_colors
    class _MockItem:
        def __init__(self, color: str):
            self.color = color

    colors = [d.get("color", "") for d in detected_items if d.get("color")]
    if len(colors) < 2:
        return eval_score

    mock_items = [_MockItem(c) for c in colors]
    local_score = score_outfit_colors(mock_items)

    # If local says clash (< 4) but Vision says great (> 7), pull down
    if local_score < 4.0 and eval_score > 7.0:
        adjusted = (eval_score + local_score) / 2
        logger.info(
            "outfit_eval.color_cross_validate",
            vision_score=eval_score,
            local_score=local_score,
            adjusted=adjusted,
        )
        return round(adjusted, 1)

    # If local says great (> 8) but Vision says bad (< 4), pull up slightly
    if local_score > 8.0 and eval_score < 4.0:
        adjusted = (eval_score * 2 + local_score) / 3
        return round(adjusted, 1)

    return eval_score


# ── Detect if photo is outfit vs single item ─────────────────────────────

def is_outfit_photo_heuristic(items: list[dict]) -> bool:
    """Determine if detected items suggest a full outfit vs single item.

    An outfit typically has items from 2+ category_groups.
    A single item is just one category_group.
    """
    if not items:
        return False

    groups = set()
    for item in items:
        cg = item.get("category_group", "")
        if cg and cg not in ("base_layer", "underwear"):
            groups.add(cg)

    return len(groups) >= 2
