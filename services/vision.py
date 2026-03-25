"""Vision API и обработка фото — вынесено из bot/handlers/wardrobe.py."""
import asyncio
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

_VISION_SYSTEM = """Ты определяешь одежду на фото и добавляешь её в гардероб.
Фото может быть горизонтальным или вертикальным — определяй вещи независимо от ориентации.
Вещи могут лежать на ковре, висеть, быть сложены стопкой или надеты на ребёнка/взрослого.
На фото может быть НЕСКОЛЬКО вещей — определи КАЖДУЮ отдельно с отдельным bbox.

ИГНОРИРУЙ бирки, ценники, этикетки, упаковку. Определи САМУ вещь.
bbox должен включать ВЕЩЬ, не бирку рядом.

ТИПИЧНЫЕ ОШИБКИ — ИЗБЕГАЙ:
- Свёрнутые/скомканные вещи: кофта, свитер или штаны могут быть скомканы — определяй по ткани, цвету, видимым элементам (воротник, рукав, пуговицы). bbox должен охватывать ВСЮ скомканную вещь целиком.
- Свёрнутые детские носки и колготки часто похожи на шапку — если вещь маленькая и лежит рядом с другой одеждой, это скорее носки/колготки, а НЕ шапка.
- Шапка обычно на фото с верхней одеждой (куртка, комбинезон), а не с футболками и штанами.
- Если сомневаешься между шапкой и носками — выбирай носки.

════════════════════════════════════════════
ФОРМАТ ОТВЕТА
════════════════════════════════════════════

Верни ТОЛЬКО JSON массив, без markdown, без пояснений. Каждая вещь:
{
  "type": "название строчными",
  "color": "цвет строчными",
  "style": "повседневный/спортивный/нарядный/домашний",
  "category_group": "outerwear/top/bottom/one_piece/footwear/accessory/bag/base_layer/underwear/sportswear/home_beach",
  "formality_level": null,
  "category_code": "english_code",
  "season": ["winter/spring/summer/autumn"],
  "occasion": ["everyday/sport/formal/home/outdoor"],
  "brand": null,
  "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
  "flat_lay_rotation": 0,
  "warmth_level": 3,
  "rain_ok": false,
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

ONE_PIECE (цельная вещь: ЗАКРЫВАЕТ и туловище и бёдра/ноги):
  платье, сарафан, комбинезон, ромпер, боди-комбинезон
  ⚠️ ВАЖНО: Если вещь заканчивается НА ТАЛИИ или ЧУТЬ НИЖЕ — это TOP, не one_piece!
  - Длинная кофта/туника до бёдер = TOP (не платье!)
  - Свитер с рюшами = TOP
  - Вязаная кофта с декором = TOP
  - ONE_PIECE = ОБЯЗАТЕЛЬНО имеет юбочную/штанную часть (ниже бёдер)
  - Если сомневаешься (фото сверху, не видно длину) — ставь TOP, не one_piece
  - Ставь "confidence": "low" если неуверен в категории

OUTERWEAR (надевается поверх всего, предназначена для улицы):
  куртка, пальто, пуховик, ветровка, плащ, дождевик, жилет утеплённый

BASE_LAYER (термобельё, базовый слой):
  колготки, термоштаны, термофутболка, тельняшка, боди без рукавов

ACCESSORY (аксессуары):
  Головные уборы: шапка, шарф, перчатки, варежки, панама, кепка
  Украшения: серьги-гвоздики, серьги-кольца, серьги длинные, колье, чокер, цепочка, кулон, браслет, кольцо, часы, брошь
  Ремень/пояс
  Для украшений определи metal_tone: gold / silver / rose_gold / mixed / none

BAG (сумки):
  рюкзак, сумка, клатч, тоут/шоппер, кроссбоди, портфель, поясная сумка, мини-сумка
  → category_group = "bag" (НЕ accessory!)

FOOTWEAR (обувь):
  кроссовки, ботинки, сапоги, туфли, сандалии, угги, лоферы, балетки, ботильоны
  → formality_level: 5=formal (лодочки, шпильки), 4=smart (лоферы, оксфорды),
    3=casual smart (ботинки, челси, балетки), 2=casual (кроссовки, кеды),
    1=super casual (сандалии, шлёпки)

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

КРИТИЧЕСКИ ВАЖНО — bbox должен быть МАКСИМАЛЬНО ПЛОТНЫМ (tight-crop):
- bbox = МИНИМАЛЬНЫЙ прямоугольник вокруг ТОЛЬКО пикселей самой вещи
- Представь что обводишь вещь маркером по самому краю ткани — вот такой bbox нужен
- Каждый край bbox должен касаться края вещи, зазор ≤1-2%
- НИКОГДА не захватывай пол, ковёр, диван, соседние вещи — даже 1 см фона = брак
- Если вещи лежат рядом — bbox'ы НЕ должны перекрываться
- ЛУЧШЕ обрезать 5% края вещи, чем захватить 5% фона
- Проверь себя: если убрать bbox из фото — виден ли фон/пол? Если да — bbox слишком большой, уменьши

Если вещей несколько — каждая имеет свой bbox.
Если вещь занимает всё фото — bbox: {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

════════════════════════════════════════════
WARMTH_LEVEL — ТЕПЛОТА ВЕЩИ
════════════════════════════════════════════

Оценивай теплоту вещи от 1 до 5:
- 1: очень лёгкая (футболка, майка, шорты, сандалии, панама, топ)
- 2: лёгкая (лонгслив, рубашка, лёгкое платье, кроссовки, ветровка, кеды)
- 3: средняя (кофта, худи, джинсы, брюки, штаны, леггинсы, ботинки)
- 4: тёплая (свитер, водолазка, толстовка, куртка, тёплые штаны, сапоги, шапка, шарф, перчатки)
- 5: очень тёплая (пуховик, зимняя куртка, угги, варежки, термобельё, дублёнка)

════════════════════════════════════════════
FLAT_LAY_ROTATION — ПОВОРОТ ДЛЯ КОЛЛАЖА
════════════════════════════════════════════

Для журнальной фото-раскладки (flat-lay) вещь должна быть ориентирована так:
- Футболка/кофта/свитер: горизонтально, горловина по центру СВЕРХУ, рукава в стороны
- Штаны/леггинсы/брюки: вертикально, ПОЯС СВЕРХУ, штанины ВНИЗ
- Платье/сарафан: вертикально, горловина/бретели СВЕРХУ, юбка ВНИЗ
- Обувь: горизонтально, носок вправо

Определи: на сколько градусов по часовой стрелке нужно повернуть ФОТО чтобы вещь оказалась в правильной flat-lay ориентации.

ВАЖНО для штанов: найди ПОЯС (застёжка, пуговица, молния, резинка) — он должен быть СВЕРХУ после поворота. Если пояс на фото внизу — rotation = 180.

Значение: 0, 90, 180 или 270.

════════════════════════════════════════════
RAIN_OK — НЕПРОМОКАЕМОСТЬ
════════════════════════════════════════════

rain_ok = true ТОЛЬКО если вещь водонепроницаемая или водоотталкивающая:
дождевик, плащ, резиновые сапоги, мембранная куртка, непромокаемые штаны.
Обычная куртка, кроссовки, джинсы = false."""


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
    """Центрирует и ужимает bbox только если он занимает почти весь кадр.

    Одиночные фото вещей: вещь нормально занимает 60-80% кадра.
    Ужимаем только truly full-frame bbox (>92%), где Vision не смог
    определить точные границы.
    """
    bbox = data.get("bbox")
    if not bbox:
        return data
    bw = float(bbox.get("w", 0.5))
    bh = float(bbox.get("h", 0.5))
    item_type = (data.get("type") or "").lower()
    cg = data.get("category_group", "top")

    # Мелкие вещи (носки, трусики) не должны занимать полкадра
    if cg in ("base_layer", "underwear") or any(
        w in item_type for w in ["носки", "трусик", "шапка", "повязка"]
    ):
        max_dim = 0.45
    else:
        # Для остальных вещей: кроп только если bbox ≈ 100% кадра
        max_dim = 0.92

    if bw > max_dim or bh > max_dim:
        logger.warning(
            "wardrobe.bbox.oversized",
            item_type=item_type, cg=cg,
            w=bw, h=bh, max_dim=max_dim,
            action="crop_tightened",
        )
        cx = float(bbox.get("x", 0.1)) + bw / 2
        cy = float(bbox.get("y", 0.1)) + bh / 2
        new_dim = max_dim * 0.9
        data["bbox"] = {
            "x": max(0.0, min(1.0 - new_dim, cx - new_dim / 2)),
            "y": max(0.0, min(1.0 - new_dim, cy - new_dim / 2)),
            "w": new_dim,
            "h": new_dim,
        }
    return data


def _resolve_bbox_overlaps(items: list[dict]) -> list[dict]:
    """Shrink overlapping bboxes so each item gets its own non-overlapping area.

    When Vision returns overlapping bboxes for items on the same photo,
    the overlap zone causes sibling masking to erase parts of the target item.

    Strategy: for each pair of overlapping bboxes, shrink the smaller one
    away from the larger one along the axis of maximum overlap.
    """
    if len(items) < 2:
        return items

    bboxes = []
    for item in items:
        b = item.get("bbox")
        if b:
            bboxes.append({
                "x": float(b.get("x", 0)), "y": float(b.get("y", 0)),
                "w": float(b.get("w", 1)), "h": float(b.get("h", 1)),
            })
        else:
            bboxes.append(None)

    for i in range(len(bboxes)):
        if not bboxes[i]:
            continue
        a = bboxes[i]
        for j in range(i + 1, len(bboxes)):
            if not bboxes[j]:
                continue
            b = bboxes[j]

            # Check overlap
            ox = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
            oy = max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
            if ox <= 0 or oy <= 0:
                continue  # no overlap

            # Shrink the smaller bbox away from the larger one
            area_a = a["w"] * a["h"]
            area_b = b["w"] * b["h"]
            small, large = (b, a) if area_b < area_a else (a, b)

            # Skip if overlap is truly negligible (<3% of smaller bbox)
            overlap_area = ox * oy
            small_area = small["w"] * small["h"]
            if small_area > 0 and overlap_area / small_area < 0.03:
                continue

            # Save original dims — don't shrink below 50% of original
            orig_w, orig_h = small["w"], small["h"]

            # Determine main overlap axis and shrink along it
            if ox < oy:
                # Horizontal overlap — shrink horizontally
                if small["x"] < large["x"]:
                    # small is to the left → trim its right edge
                    small["w"] = max(0.10, large["x"] - small["x"])
                else:
                    # small is to the right → move its left edge
                    new_x = large["x"] + large["w"]
                    shrink = new_x - small["x"]
                    small["x"] = new_x
                    small["w"] = max(0.10, small["w"] - shrink)
            else:
                # Vertical overlap — shrink vertically
                if small["y"] < large["y"]:
                    small["h"] = max(0.10, large["y"] - small["y"])
                else:
                    new_y = large["y"] + large["h"]
                    shrink = new_y - small["y"]
                    small["y"] = new_y
                    small["h"] = max(0.10, small["h"] - shrink)

            # Guard: don't shrink below 50% of original dimension
            if small["w"] < orig_w * 0.5:
                small["w"] = orig_w
            if small["h"] < orig_h * 0.5:
                small["h"] = orig_h

    # Write back
    for i, item in enumerate(items):
        if bboxes[i]:
            item["bbox"] = bboxes[i]

    return items


def _refine_bbox_by_color(image_bytes: bytes, items: list[dict]) -> list[dict]:
    """Shrink bbox edges that contain background (floor/carpet).

    Strategy: sample BACKGROUND color from photo corners, then scan each
    bbox edge inward. If a strip is SIMILAR to background → trim it.
    Stop when strip looks different from background (= garment found).

    This is the inverse of the old approach (which compared to center).
    Comparing to background is more robust because floor color is consistent
    across the photo, while garment center may have varied textures.
    """
    try:
        import cv2
        import numpy as np
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad = np.sqrt(gx ** 2 + gy ** 2)
        ih, iw = arr.shape[:2]

        # Sample background from 4 corners (10x10 patches)
        p = 10
        corners = [
            lab[:p, :p],        lab[:p, -p:],
            lab[-p:, :p],       lab[-p:, -p:],
        ]
        bg_color = np.mean([c.mean(axis=(0, 1)) for c in corners], axis=0)
        bg_grad_corners = [
            grad[:p, :p],       grad[:p, -p:],
            grad[-p:, :p],      grad[-p:, -p:],
        ]
        bg_grad = np.mean([c.mean() for c in bg_grad_corners])

        for item in items:
            bbox = item.get("bbox")
            if not bbox:
                continue
            x, y = float(bbox.get("x", 0)), float(bbox.get("y", 0))
            w, h = float(bbox.get("w", 1)), float(bbox.get("h", 1))

            if w * h > 0.5:
                continue
            # Don't refine tiny items (noise)
            if w * h < 0.01:
                continue

            px_x, px_y = int(x * iw), int(y * ih)
            px_r, px_b = int((x + w) * iw), int((y + h) * ih)
            strip_w = max(4, int(w * iw * 0.05))
            strip_h = max(4, int(h * ih * 0.05))

            # Center band for sampling edge strips (avoid corners of bbox)
            mid_y1 = int((y + h * 0.3) * ih)
            mid_y2 = int((y + h * 0.7) * ih)
            mid_x1 = int((x + w * 0.3) * iw)
            mid_x2 = int((x + w * 0.7) * iw)

            def _is_background(strip_region):
                """True if strip looks like background (similar color OR texture to corners)."""
                y1, y2, x1, x2 = strip_region
                if y2 <= y1 + 1 or x2 <= x1 + 1:
                    return False
                sc = lab[y1:y2, x1:x2]
                if sc.size == 0:
                    return False
                color_diff = np.sqrt(np.sum((sc.mean(axis=(0, 1)) - bg_color) ** 2))
                sg = grad[y1:y2, x1:x2]
                grad_diff = abs(sg.mean() - bg_grad)
                # Color similar to bg → likely background
                if color_diff < 22.0:
                    return True
                # Texture similar to bg AND color not drastically different → background
                if grad_diff < 20.0 and color_diff < 35.0:
                    return True
                return False

            orig_x, orig_y, orig_w, orig_h = x, y, w, h
            trimmed = False
            # Guard: never trim more than 25% from any side
            max_trim_w = orig_w * 0.25
            max_trim_h = orig_h * 0.25

            # Left edge: scan inward while strip looks like background
            for step in range(8):
                lx = px_x + step * strip_w
                if lx + strip_w >= mid_x1:
                    break
                new_x = (lx + strip_w) / iw
                if new_x - orig_x > max_trim_w:
                    break  # guard: too much trimmed
                if _is_background((mid_y1, mid_y2, lx, lx + strip_w)):
                    bbox["x"] = new_x
                    bbox["w"] = max(0.06, (orig_x + orig_w) - bbox["x"])
                    trimmed = True
                else:
                    break  # hit garment, stop

            # Right edge
            for step in range(8):
                rx = px_r - (step + 1) * strip_w
                if rx <= mid_x2:
                    break
                new_w = rx / iw - float(bbox["x"])
                if orig_w - new_w > max_trim_w:
                    break
                if _is_background((mid_y1, mid_y2, rx, rx + strip_w)):
                    bbox["w"] = max(0.06, new_w)
                    trimmed = True
                else:
                    break

            # Top edge
            for step in range(8):
                ty = px_y + step * strip_h
                if ty + strip_h >= mid_y1:
                    break
                new_y = (ty + strip_h) / ih
                if new_y - orig_y > max_trim_h:
                    break
                if _is_background((ty, ty + strip_h, mid_x1, mid_x2)):
                    bbox["y"] = new_y
                    bbox["h"] = max(0.06, (orig_y + orig_h) - bbox["y"])
                    trimmed = True
                else:
                    break

            # Bottom edge
            for step in range(8):
                by = px_b - (step + 1) * strip_h
                if by <= mid_y2:
                    break
                new_h = by / ih - float(bbox["y"])
                if orig_h - new_h > max_trim_h:
                    break
                if _is_background((by, by + strip_h, mid_x1, mid_x2)):
                    bbox["h"] = max(0.06, new_h)
                    trimmed = True
                else:
                    break

            if trimmed:
                logger.info("bbox.texture_refined",
                    item_type=item.get("type", ""),
                    orig=f"{orig_w:.2f}x{orig_h:.2f}",
                    new=f"{float(bbox['w']):.2f}x{float(bbox['h']):.2f}")

    except Exception as e:
        logger.warning("bbox.texture_refine_failed", error=str(e))

    return items



# ── Post-Vision reclassification: fix misidentified items ────────────────

_FORCE_BASE_LAYER_TYPES = frozenset({
    "носки", "гольфы", "колготки", "подследники",
    "термоштаны", "термофутболка", "тельняшка",
})

_FORCE_UNDERWEAR_TYPES = frozenset({
    "трусики", "трусы", "майка нижняя", "бюстгальтер",
})


def _reclassify_items(items: list[dict]) -> list[dict]:
    """Fix common Vision classification mistakes using bbox size and context.

    Rules:
    1. Small "шапка" with no outerwear context → носки (threshold 0.25)
    2. Носки/колготки/гольфы → force category_group=base_layer
    3. Трусики/бюстгальтер → force category_group=underwear
    """
    has_outerwear = any(
        item.get("category_group") == "outerwear" for item in items
    )

    for item in items:
        item_type = (item.get("type") or "").lower().strip()
        cg = item.get("category_group", "")
        bbox = item.get("bbox") or {}
        bw = float(bbox.get("w", 0.5))
        bh = float(bbox.get("h", 0.5))

        if (cg == "accessory" and
                any(w in item_type for w in ["шапка", "шапочка", "hat"]) and
                bw <= 0.25 and bh <= 0.25 and
                not has_outerwear):
            logger.info("vision.reclassify",
                from_type=item.get("type"), to_type="носки",
                reason="small_bbox_no_outerwear",
                bbox_w=bw, bbox_h=bh)
            item["category_group"] = "base_layer"
            item["type"] = "носки"
            continue

        if any(t in item_type for t in _FORCE_BASE_LAYER_TYPES) and cg != "base_layer":
            logger.info("vision.reclassify",
                from_type=item.get("type"), from_cg=cg,
                to_cg="base_layer", reason="force_base_layer")
            item["category_group"] = "base_layer"
            continue

        if any(t in item_type for t in _FORCE_UNDERWEAR_TYPES) and cg != "underwear":
            logger.info("vision.reclassify",
                from_type=item.get("type"), from_cg=cg,
                to_cg="underwear", reason="force_underwear")
            item["category_group"] = "underwear"

    return items


def _default_score() -> tuple[dict, float]:
    breakdown = {
        "safety": 1, "practicality": 1, "durability": 1,
        "age_authenticity": 1, "ease_of_care": 1, "colortype": 1,
        "comfort": 1, "versatility": 1, "condition": 1,
        "size_fit_score": 1, "seasonality": 1,
    }
    return breakdown, round((sum(breakdown.values()) / 15) * 10, 2)


def _crop_bbox(image_bytes: bytes, bbox: dict, padding: float = 0.05) -> bytes:
    """Вырезает вещь из фото по нормализованным координатам bbox.

    Args:
        padding: fractional padding around bbox (0.05 = 5%). Use smaller values
                 for multi-item photos to avoid capturing neighbor items.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        iw, ih = img.size
        x = max(0.0, min(1.0, float(bbox.get("x", 0.0))))
        y = max(0.0, min(1.0, float(bbox.get("y", 0.0))))
        w = max(0.01, min(1.0 - x, float(bbox.get("w", 1.0))))
        h = max(0.01, min(1.0 - y, float(bbox.get("h", 1.0))))
        # Apply padding
        pad_x = w * padding
        pad_y = h * padding
        x = max(0.0, x - pad_x)
        y = max(0.0, y - pad_y)
        w = min(1.0 - x, w + 2 * pad_x)
        h = min(1.0 - y, h + 2 * pad_y)
        left = int(x * iw)
        top = int(y * ih)
        right = int((x + w) * iw)
        bottom = int((y + h) * ih)
        cropped = img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except (ValueError, TypeError):
        return image_bytes


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


# ── Post-validation: fix Vision mistakes using weather context ──────────────

def _post_validate_vision(
    items: list[dict],
    temp: float | None = None,
    season: str | None = None,
) -> list[dict]:
    """Fix common Vision misclassifications using weather/season context.

    Rules:
    - "шорты" at temp < 10°C for children → reclassify to "штаны"
    - "сандалии" at temp < 5°C → reclassify to "кроссовки"
    """
    if temp is None:
        return items

    for item in items:
        item_type = (item.get("type") or "").lower()
        cg = item.get("category_group", "")

        # Shorts at cold temperatures → pants
        if cg == "bottom" and "шорт" in item_type and temp < 10:
            logger.info(
                "vision.post_validate.reclassify",
                from_type=item["type"],
                to_type="штаны",
                reason=f"shorts_at_{temp}C",
            )
            item["type"] = "штаны"
            # Update season to include cold seasons
            if item.get("season") and "winter" not in item["season"]:
                item["season"] = ["spring", "summer", "autumn", "winter"]

        # Sandals at very cold temps → sneakers
        if cg == "footwear" and "сандал" in item_type and temp < 5:
            logger.info(
                "vision.post_validate.reclassify",
                from_type=item["type"],
                to_type="кроссовки",
                reason=f"sandals_at_{temp}C",
            )
            item["type"] = "кроссовки"
            if item.get("season"):
                item["season"] = ["spring", "summer", "autumn", "winter"]

        # Heavy outerwear in hot weather → reduce warmth_level
        warmth = item.get("warmth_level", 3)
        if cg == "outerwear" and isinstance(warmth, (int, float)) and warmth >= 4 and temp > 25:
            logger.info(
                "vision.post_validate.warmth_reduced",
                from_type=item["type"],
                warmth_from=warmth,
                warmth_to=2,
                reason=f"heavy_outerwear_at_{temp}C",
            )
            item["warmth_level"] = 2

        # Gloves/scarf in warm weather → warning only (don't reclassify)
        if cg == "accessory" and temp > 20:
            if any(w in item_type for w in ["перчатк", "варежк", "шарф"]):
                logger.warning(
                    "vision.post_validate.warm_weather_accessory",
                    item_type=item["type"],
                    temp=temp,
                    reason="winter_accessory_in_warm_weather",
                )

    return items


# ── Claude Vision calls ────────────────────────────────────────────────────

async def _call_vision(
    photo_bytes: bytes,
    *,
    owner_type: str = "child",
    age: int | None = None,
    season: str | None = None,
    temp: float | None = None,
    city: str | None = None,
) -> list[dict]:
    """Analyze photo with Claude Vision. Context improves accuracy.

    Args:
        owner_type: "child" or "user" (adult)
        age: child's age in years (None for adults)
        season: current season name
        temp: current temperature in Celsius
        city: user's city for weather context
    """
    pool = get_anthropic_pool()

    # Build context-aware user message
    context_parts = []
    if owner_type == "child" and age is not None:
        context_parts.append(f"Вещь для ребёнка {age} лет.")
    elif owner_type == "user":
        context_parts.append("Вещь для взрослой женщины.")

    if season and temp is not None:
        _season_ru = {"winter": "зима", "spring": "весна", "summer": "лето", "autumn": "осень"}.get(season, season)
        _city_part = f" в {city}" if city else ""
        context_parts.append(f"Сейчас {_season_ru}, {temp:+.0f}°C{_city_part}.")

    user_text = "Определи все вещи на фото."
    if context_parts:
        user_text = " ".join(context_parts) + "\n" + user_text

    async with asyncio.timeout(60):
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
                    {"type": "text", "text": user_text},
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

    # Validate each item before storage
    from services.validation import validate_vision_item
    validated = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        item = validate_vision_item(item)
        validated.append(item)

    if not validated and parsed:
        logger.warning("vision.all_items_invalid", original_count=len(parsed))

    # Cap at 8 items per photo to prevent abuse / hallucination
    if len(validated) > 8:
        logger.warning("vision.too_many_items", count=len(validated), capped=8)
        validated = validated[:8]

    # Reclassify misidentified items (bbox-based + type-based)
    validated = _reclassify_items(validated)

    # Post-validation: fix misclassifications using weather context
    validated = _post_validate_vision(validated, temp=temp, season=season)

    return validated


async def _call_rate_vision(
    photo_bytes_list: list[bytes],
    owner_id=None,
    owner_type: str | None = None,
    *,
    colortype: str | None = None,
    body_type: str | None = None,
    segment: str | None = None,
    child_age: int | None = None,
) -> str:
    """Evaluate outfit photo using structured professional analysis.

    Returns formatted text for the user (never raw JSON).
    Uses new structured prompt → JSON → cross-validation → formatted text.
    """
    from services.outfit_evaluator import (
        build_eval_prompt,
        parse_eval_response,
        format_eval_text,
        cross_validate_colors,
    )

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

    # Load wardrobe for swap suggestions
    wardrobe_items = []
    if owner_id and owner_type:
        async with AsyncReadSession() as session:
            wardrobe_items = await get_owner_items(session, owner_id, owner_type)

    # Build structured evaluation prompt
    system_prompt = build_eval_prompt(
        owner_type=owner_type or "user",
        wardrobe_items=wardrobe_items,
        colortype=colortype,
        body_type=body_type,
        segment=segment,
        child_age=child_age,
    )

    response = await pool.create_message(
        model="claude-sonnet-4-6",
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
        max_tokens=1024,
    )
    raw = response.content[0].text.strip() if response.content else ""

    if not raw:
        return "Не удалось оценить образ. Попробуй ещё раз."

    # Parse structured response
    eval_data = parse_eval_response(raw)
    if eval_data is None:
        # Fallback: return raw text if JSON parsing failed, truncated
        logger.warning("rate_vision.json_fallback", raw=raw[:200])
        return raw[:500] if len(raw) > 500 else raw

    # Cross-validate colors with local harmony engine
    detected = eval_data.get("detected_items", [])
    if detected and eval_data.get("dimensions", {}).get("color_harmony"):
        original_color_score = eval_data["dimensions"]["color_harmony"]
        adjusted = cross_validate_colors(detected, original_color_score)
        if adjusted != original_color_score:
            eval_data["dimensions"]["color_harmony"] = adjusted
            # Recalculate overall score with adjusted color
            dims = eval_data["dimensions"]
            if dims:
                # Simple weighted average
                from services.outfit_evaluator import EVAL_DIMENSIONS
                total_weight = sum(d["weight"] for d in EVAL_DIMENSIONS.values())
                weighted = sum(
                    dims.get(k, 5) * EVAL_DIMENSIONS[k]["weight"]
                    for k in EVAL_DIMENSIONS
                    if k in dims
                )
                used_weight = sum(
                    EVAL_DIMENSIONS[k]["weight"]
                    for k in EVAL_DIMENSIONS
                    if k in dims
                )
                if used_weight > 0:
                    eval_data["score"] = round(weighted / used_weight, 1)

    return format_eval_text(eval_data, owner_type=owner_type or "user")
