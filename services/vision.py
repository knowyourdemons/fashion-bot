"""Vision API и обработка фото — вынесено из bot/handlers/wardrobe.py."""
import base64
import io
import json
from difflib import SequenceMatcher

import structlog
from PIL import Image

from core.anthropic_client import get_anthropic_pool
from db.base import AsyncReadSession
from db.crud.wardrobe import get_owner_items

logger = structlog.get_logger()


# ── Системные промпты Vision ───────────────────────────────────────────────

_VISION_SYSTEM = """Ты определяешь детскую одежду на фото и добавляешь её в гардероб.
Фото может быть горизонтальным или вертикальным — определяй вещи независимо от ориентации.
Вещи могут лежать на ковре, висеть, быть сложены стопкой или надеты на ребёнка.

════════════════════════════════════════════
ФОРМАТ ОТВЕТА
════════════════════════════════════════════

Верни ТОЛЬКО JSON массив, без markdown, без пояснений. Каждая вещь:
{
  "type": "название строчными",
  "color": "цвет строчными",
  "style": "повседневный/спортивный/нарядный/домашний",
  "category_group": "outerwear/top/bottom/one_piece/footwear/accessory/base_layer/underwear/sportswear/home_beach",
  "category_code": "english_code",
  "season": ["winter/spring/summer/autumn"],
  "occasion": ["everyday/sport/formal/home/outdoor"],
  "brand": null,
  "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
  "score_breakdown": {
    "safety": 1, "practicality": 1, "durability": 1, "age_authenticity": 1,
    "ease_of_care": 1, "colortype": 1, "comfort": 1, "versatility": 1,
    "condition": 1, "size_fit_score": 1, "seasonality": 1
  }
}

════════════════════════════════════════════
КЛАССИФИКАЦИЯ ПО ФОРМЕ — ГЛАВНОЕ ПРАВИЛО
════════════════════════════════════════════

Определяй категорию ТОЛЬКО по форме и функции вещи, не по декору:

TOP (есть рукава + туловищная часть):
  футболка, лонгслив, кофта, свитер, худи, свитшот, олимпийка, водолазка,
  блузка, рубашка, боди с рукавами
  → УШКИ на капюшоне, принт, аппликация НЕ меняют категорию — это всё равно TOP

BOTTOM (надевается на ноги, есть поясная часть):
  штаны, брюки, джинсы, шорты, юбка, леггинсы, бриджи, комбинезон-штаны

ONE_PIECE (цельная вещь: туловище + ноги или юбка):
  платье, сарафан, комбинезон, ромпер, боди-комбинезон

OUTERWEAR (надевается поверх всего, предназначена для улицы):
  куртка, пальто, пуховик, ветровка, плащ, дождевик, жилет утеплённый

BASE_LAYER (термобельё, базовый слой):
  колготки, термоштаны, термофутболка, тельняшка, боди без рукавов

ACCESSORY (аксессуары):
  шапка, шарф, перчатки, варежки, панама, кепка, ремень, рюкзак, сумка

FOOTWEAR (обувь):
  кроссовки, ботинки, сапоги, туфли, сандалии, угги

UNDERWEAR (нижнее бельё):
  трусики, майка, бюстгальтер, носки, гольфы

════════════════════════════════════════════
SCORE_BREAKDOWN — ОЦЕНКА КАЖДОГО КРИТЕРИЯ
════════════════════════════════════════════

Оценивай каждый критерий от 1 до 3 (не float):
- safety: 1=опасная фурнитура/завязки, 2=норм, 3=максимально безопасная
- practicality: 1=неудобно одевать, 2=норм, 3=легко снимать/надевать
- durability: 1=нежный материал, 2=норм, 3=прочный
- age_authenticity: 1=не по возрасту, 2=норм, 3=идеально по возрасту
- ease_of_care: 1=сложный уход, 2=норм стирка, 3=машинная стирка
- colortype: 1=сложный цвет, 2=норм, 3=универсальный
- comfort: 1=жёсткий/неудобный, 2=норм, 3=мягкий/удобный
- versatility: 1=один вариант, 2=2-3 варианта, 3=много сочетаний
- condition: 1=потёрт/повреждён, 2=норм, 3=новый/отличный
- size_fit_score: 1=не по размеру, 2=норм, 3=идеально
- seasonality: 1=не по сезону, 2=норм, 3=идеально по сезону

════════════════════════════════════════════
BBOX — КООРДИНАТЫ ВЕЩИ
════════════════════════════════════════════

bbox задаёт координаты прямоугольника вещи в нормализованных координатах [0..1]:
- x, y — левый верхний угол
- w, h — ширина и высота

Если вещей несколько — каждая имеет свой bbox.
Если вещь занимает всё фото — bbox: {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}"""


_RATE_SYSTEM_CHILD = (
    "Ты стилист детской моды с насмотренностью Vogue Kids. Оцени образ ребёнка на фото.\n\n"
    "Если на фото виден только фрагмент образа (только ноги, только верх, только лицо):\n"
    "- Честно напиши: 'Вижу только часть образа'\n"
    "- Оцени только видимые элементы, не домысливай\n"
    "- Попроси прислать полное фото для полной оценки\n"
    "Для полной оценки нужно видеть весь образ от головы до ног.\n"
    "Оценивай ВСЕ видимые элементы: головной убор, верхняя одежда, низ, обувь — не пропускай ни один видимый.\n\n"
    "Структура ответа:\n"
    "⭐ Оценка: X/10\n"
    "✅ Что работает: (1-2 предложения)\n"
    "❌ Что улучшить: (конкретно)\n\n"
    "Язык: русский."
)

_RATE_SYSTEM_ADULT = (
    "Ты персональный стилист. Оцени образ взрослого человека на фото.\n\n"
    "Если на фото виден только фрагмент образа (только ноги, только верх, только лицо):\n"
    "- Честно напиши: 'Вижу только часть образа'\n"
    "- Оцени только видимые элементы, не домысливай\n"
    "- Попроси прислать фото в полный рост для полной оценки\n"
    "Для полной оценки нужно видеть весь образ от головы до ног.\n"
    "Оценивай ВСЕ видимые элементы: верхняя одежда, низ, обувь, аксессуары.\n\n"
    "Структура ответа — строго такая:\n"
    "⭐ Оценка: X/10\n"
    "✅ Что работает: (1-2 предложения — цвет, силуэт, сочетание)\n"
    "❌ Что улучшить: (конкретно и конструктивно)\n"
    "👗 Замена: [вещь на фото] → [вещь из гардероба]\n"
    "   Причина: улучшит [цветовую гармонию/стиль/баланс]\n\n"
    "Правила:\n"
    "- Оцениваешь образ взрослого — применяй критерии взрослой моды\n"
    "- Рекомендуй ТОЛЬКО вещи из гардероба пользователя если он не пуст\n"
    "- Если гардероб пуст — давай общие рекомендации без конкретных замен\n"
    "- Если оценка 8 или выше — раздел 'Замена' не нужен, только похвали\n"
    "- Максимум 2 замены\n"
    "- Тон: дружелюбный, как подруга-стилист\n"
    "- НЕ упоминай детей и детскую моду\n"
    "Язык: русский."
)


# ── Rate prompt builder ────────────────────────────────────────────────────

def _build_rate_prompt(wardrobe_items: list, owner_type: str = "child") -> str:
    """Строит системный промпт стилиста с топ-20 вещей гардероба по score."""
    top_items = sorted(
        [i for i in wardrobe_items if i.score_item],
        key=lambda x: float(x.score_item),
        reverse=True,
    )[:20]
    if top_items:
        wardrobe_context = ", ".join(f"{i.type} {i.color}" for i in top_items)
    else:
        wardrobe_context = "гардероб пуст"

    if owner_type == "child":
        return (
            "Ты стилист детской моды. Оцени образ ребёнка на фото.\n\n"
            "Если на фото виден только фрагмент образа (только ноги, только верх):\n"
            "- Честно напиши: 'Вижу только часть образа'\n"
            "- Оцени только видимые элементы, не домысливай\n"
            "- Попроси прислать полное фото\n"
            "Оценивай ВСЕ видимые элементы: головной убор, верхняя одежда, низ, обувь.\n\n"
            f"Гардероб ребёнка (лучшие вещи):\n{wardrobe_context}\n\n"
            "Структура ответа — строго такая:\n"
            "⭐ Оценка: X/10\n"
            "✅ Что работает: (1-2 предложения)\n"
            "❌ Что улучшить: (конкретно)\n"
            "👗 Замена: [вещь на фото] → [точное название из гардероба выше]\n"
            "   Причина: улучшит [цветовую гармонию/сезонность/стиль]\n\n"
            "Правила:\n"
            "- В разделе 'Замена' используй ТОЛЬКО вещи из списка гардероба выше\n"
            "- Если нужной замены нет в гардеробе — пропусти раздел 'Замена'\n"
            "- Если оценка 8 или выше — раздел 'Замена' не нужен, только похвали\n"
            "- Максимум 2 замены\n"
            "- НЕ советуй покупать вещи которые уже есть в гардеробе\n"
            "Язык: русский."
        )
    else:
        return (
            "Ты персональный стилист. Оцени образ взрослого человека на фото.\n\n"
            "Если на фото виден только фрагмент образа (только ноги, только верх):\n"
            "- Честно напиши: 'Вижу только часть образа'\n"
            "- Оцени только видимые элементы, не домысливай\n"
            "- Попроси прислать фото в полный рост\n"
            "Оценивай ВСЕ видимые элементы: верхняя одежда, низ, обувь, аксессуары.\n\n"
            f"Гардероб пользователя (лучшие вещи для рекомендаций):\n{wardrobe_context}\n\n"
            "Структура ответа — строго такая:\n"
            "⭐ Оценка: X/10\n"
            "✅ Что работает: (1-2 предложения — цвет, силуэт, сочетание)\n"
            "❌ Что улучшить: (конкретно и конструктивно)\n"
            "👗 Замена: [вещь на фото] → [точное название из гардероба выше]\n"
            "   Причина: улучшит [цветовую гармонию/стиль/баланс]\n\n"
            "Правила:\n"
            "- Оцениваешь образ взрослого — применяй критерии взрослой моды\n"
            "- В разделе 'Замена' используй ТОЛЬКО вещи из гардероба выше\n"
            "- Если гардероб пуст — давай общие рекомендации без конкретных замен\n"
            "- Если оценка 8 или выше — раздел 'Замена' не нужен, только похвали\n"
            "- Максимум 2 замены\n"
            "- Тон: дружелюбный, как подруга-стилист\n"
            "- НЕ упоминай детей и детскую моду\n"
            "Язык: русский."
        )


# ── Item utilities ─────────────────────────────────────────────────────────

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


def _fix_bbox(data: dict) -> dict:
    """Центрирует и ужимает bbox если он слишком велик для данного типа вещи."""
    bbox = data.get("bbox")
    if not bbox:
        return data
    bw = float(bbox.get("w", 0.5))
    bh = float(bbox.get("h", 0.5))
    item_type = (data.get("type") or "").lower()
    cg = data.get("category_group", "top")

    if cg in ("base_layer", "underwear") or any(
        w in item_type for w in ["носки", "трусик", "шапка", "повязка"]
    ):
        max_dim = 0.25
    elif cg in ("outerwear", "one_piece"):
        max_dim = 0.75
    else:
        max_dim = 0.55

    if bw > max_dim or bh > max_dim:
        logger.warning(
            "wardrobe.bbox.oversized",
            item_type=item_type, cg=cg,
            w=bw, h=bh, max_dim=max_dim,
            action="crop_tightened",
        )
        cx = float(bbox.get("x", 0.1)) + bw / 2
        cy = float(bbox.get("y", 0.1)) + bh / 2
        new_dim = max_dim * 0.8
        data["bbox"] = {
            "x": max(0.0, min(1.0 - new_dim, cx - new_dim / 2)),
            "y": max(0.0, min(1.0 - new_dim, cy - new_dim / 2)),
            "w": new_dim,
            "h": new_dim,
        }
    return data


def _default_score() -> tuple[dict, float]:
    breakdown = {
        "safety": 1, "practicality": 1, "durability": 1,
        "age_authenticity": 1, "ease_of_care": 1, "colortype": 1,
        "comfort": 1, "versatility": 1, "condition": 1,
        "size_fit_score": 1, "seasonality": 1,
    }
    return breakdown, round((sum(breakdown.values()) / 15) * 10, 2)


def _crop_bbox(image_bytes: bytes, bbox: dict) -> bytes:
    """Вырезает вещь из фото по нормализованным координатам bbox."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    iw, ih = img.size
    x = max(0.0, min(1.0, float(bbox.get("x", 0.0))))
    y = max(0.0, min(1.0, float(bbox.get("y", 0.0))))
    w = max(0.01, min(1.0 - x, float(bbox.get("w", 1.0))))
    h = max(0.01, min(1.0 - y, float(bbox.get("h", 1.0))))
    left = int(x * iw)
    top = int(y * ih)
    right = int((x + w) * iw)
    bottom = int((y + h) * ih)
    cropped = img.crop((left, top, right, bottom))
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _check_crop_quality(png_bytes: bytes, min_ratio: float = 0.15) -> bool:
    """
    Проверяет что вещь занимает достаточно места в кропе.
    Считает долю непрозрачных пикселей (альфа > 30).
    Возвращает True если вещь >= min_ratio площади кропа.
    """
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        pixels = list(img.getdata())
        total = len(pixels)
        opaque = sum(1 for p in pixels if p[3] > 30)
        ratio = opaque / total if total > 0 else 0
        return ratio >= min_ratio
    except Exception:
        return True  # fallback — не блокировать сохранение


def _color_similar(a: str, b: str) -> bool:
    """True если цвета почти идентичны (ratio > 0.95)."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() > 0.95


# ── Claude Vision calls ────────────────────────────────────────────────────

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


async def _call_rate_vision(
    photo_bytes_list: list[bytes],
    owner_id=None,
    owner_type: str | None = None,
) -> str:
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

    if owner_id and owner_type:
        async with AsyncReadSession() as session:
            wardrobe_items = await get_owner_items(session, owner_id, owner_type)
        system_prompt = _build_rate_prompt(wardrobe_items, owner_type=owner_type)
    else:
        system_prompt = _RATE_SYSTEM_CHILD

    response = await pool.create_message(
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
        max_tokens=512,
    )
    return response.content[0].text.strip() if response.content else "Не удалось оценить образ"
