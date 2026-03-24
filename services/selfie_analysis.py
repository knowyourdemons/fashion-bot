"""Selfie analysis — colortype detection, card rendering, style passport."""
import base64
import json

import sentry_sdk
import structlog
import sqlalchemy as sa

from core.anthropic_client import get_anthropic_pool
from db.base import AsyncWriteSession
from db.models.user import User
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = structlog.get_logger()


_COLORTYPE_CARD_HEX = {
    "spring": ["#FFD1A9", "#FF9966", "#FFCC66", "#99CC66", "#FFE0B2", "#FFAB91"],
    "summer": ["#B2A4D4", "#E8B4C8", "#A0C4D8", "#C8E0D8", "#D8C0D8", "#B0D0E0"],
    "autumn": ["#CC9933", "#CC6633", "#8B8B00", "#996633", "#CC9966", "#8B6914"],
    "winter": ["#FFFFFF", "#000000", "#3366CC", "#CC0066", "#C0C0C0", "#003366"],
}

_COLORTYPE_NAMES_RU = {
    "spring": "Весна 🌸",
    "summer": "Лето ☀️",
    "autumn": "Осень 🍂",
    "winter": "Зима ❄️",
}


async def _save_colortype_to_user(user, colortype: str) -> None:
    """Save colortype to user record."""
    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(User).where(User.id == user.id)
            .values(colortype=colortype)
        )
        await session.commit()
    user.colortype = colortype


async def _analyze_selfie_colortype(photo_bytes: bytes) -> dict:
    """Call Vision (Sonnet) to determine 12-season colortype from selfie.

    Returns {colortype, sub_season, confidence}.
    colortype: one of 4 base seasons (backward compat)
    sub_season: one of 12 sub-seasons for precise palette selection

    LIMITATION: Does not detect group photos — if multiple people are in the
    selfie, Vision will analyze the most prominent face. A future improvement
    would add face-count detection and ask the user to retake with one person.
    """
    pool = get_anthropic_pool()
    prompt = (
        "Определи цветотип человека на фото по 12-сезонной системе.\n\n"
        "Анализируй:\n"
        "1. Тон кожи (тёплый / холодный / нейтральный)\n"
        "2. Цвет волос (от платины до чёрного, тёплый/холодный подтон)\n"
        "3. Контраст между кожей и волосами (низкий / средний / высокий)\n"
        "4. Общая яркость и насыщенность внешности\n\n"
        "12 подтипов:\n"
        "- Bright Spring, True Spring, Light Spring\n"
        "- Light Summer, True Summer, Soft Summer\n"
        "- Soft Autumn, True Autumn, Deep Autumn\n"
        "- Deep Winter, True Winter, Bright Winter\n\n"
        "Дополнительно определи:\n\n"
        "## Contrast level\n"
        "Разница между самым тёмным и светлым элементом (волосы vs кожа):\n"
        "- HIGH: сильный контраст (тёмные волосы + светлая кожа)\n"
        "- MEDIUM: умеренный\n"
        "- LOW: слабый (блондинка + светлая кожа, или тёмная кожа + тёмные волосы)\n\n"
        "## Kibbe family (тип силуэта)\n"
        "По видимым чертам:\n"
        "- DRAMATIC: sharp, angular, длинная вертикаль, узкий\n"
        "- NATURAL: broad, blunt, расслабленный, moderate\n"
        "- CLASSIC: симметричный, сбалансированный\n"
        "- GAMINE: компактный, микс sharp+soft, юношеская энергия\n"
        "- ROMANTIC: округлый, soft, curvy, деликатный\n\n"
        "## Style essence (по лицу)\n"
        "- DRAMATIC: striking, intense\n"
        "- NATURAL: warm, approachable\n"
        "- CLASSIC: refined, elegant\n"
        "- GAMINE: playful, animated\n"
        "- ROMANTIC: soft, feminine\n\n"
        "Также определи цветовую глубину:\n"
        "- tonal_depth: LIGHT / MEDIUM-LIGHT / MEDIUM / MEDIUM-DEEP / DEEP (общая тональность)\n"
        "- chroma: BRIGHT / MODERATE / MUTED (яркость/приглушённость черт)\n"
        "- flow_to: если на границе сезонов — укажи второй сезон (напр. True Summer -> Soft Autumn)\n"
        "- flow_strength: 0.0-0.4 (0 = чисто основной, 0.4 = сильно на границе)\n\n"
        'Ответь JSON: {"sub_season": "True Summer", "confidence": 0.8, '
        '"contrast_level": "HIGH/MEDIUM/LOW", '
        '"kibbe_family": "DRAMATIC/NATURAL/CLASSIC/GAMINE/ROMANTIC", '
        '"style_essence": "DRAMATIC/NATURAL/CLASSIC/GAMINE/ROMANTIC", '
        '"tonal_depth": "MEDIUM", "chroma": "MUTED", '
        '"flow_to": "Soft Autumn", "flow_strength": 0.2}\n'
        "Только JSON, без пояснений."
    )
    try:
        response = await pool.create_message(
            model="claude-sonnet-4-6",
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
                    {"type": "text", "text": prompt},
                ],
            }],
            system="Ты эксперт по 12-сезонному цветотипированию. Отвечай только JSON.",
            max_tokens=300,
        )
        text = response.content[0].text.strip()
        import re as _re
        json_match = _re.search(r'\{[^}]+\}', text)
        if json_match:
            result = json.loads(json_match.group())
            sub_season = result.get("sub_season", "True Summer")

            # Map sub-season → base season for backward compat
            _BASE_SEASON_MAP = {
                "Bright Spring": "Весна", "True Spring": "Весна", "Light Spring": "Весна",
                "Light Summer": "Лето", "True Summer": "Лето", "Soft Summer": "Лето",
                "Soft Autumn": "Осень", "True Autumn": "Осень", "Deep Autumn": "Осень",
                "Deep Winter": "Зима", "True Winter": "Зима", "Bright Winter": "Зима",
            }
            base = _BASE_SEASON_MAP.get(sub_season, "Лето")

            return {
                "colortype": base,
                "sub_season": sub_season,
                "confidence": float(result.get("confidence", 0.5)),
                "contrast_level": result.get("contrast_level"),
                "kibbe_family": result.get("kibbe_family"),
                "style_essence": result.get("style_essence"),
                "tonal_depth": result.get("tonal_depth"),
                "chroma": result.get("chroma"),
                "flow_to": result.get("flow_to"),
                "flow_strength": result.get("flow_strength"),
            }
        return {"colortype": "Лето", "sub_season": "True Summer", "confidence": 0.0}
    except Exception as e:
        logger.warning("selfie_colortype.vision_failed", error=str(e))
        sentry_sdk.capture_exception(e)
        return {"colortype": "Лето", "sub_season": "True Summer", "confidence": 0.0}


async def _build_colortype_card(name: str, colortype: str) -> bytes | None:
    """Render a colortype card via Satori: 440x300 with gradient, name, and 6 swatches."""
    from services.image_builder import _render_satori
    from services.brief_card import _div, _text, _row, _col

    hex_colors = _COLORTYPE_CARD_HEX.get(colortype, _COLORTYPE_CARD_HEX["summer"])
    ct_label = _COLORTYPE_NAMES_RU.get(colortype, colortype)

    # Gradient backgrounds per colortype
    _GRADIENTS = {
        "spring": ("linear-gradient(135deg, #FFF8E7, #FFE8D0)", "#8B6B4A"),
        "summer": ("linear-gradient(135deg, #F0E8F8, #E0F0F8)", "#5B4A6B"),
        "autumn": ("linear-gradient(135deg, #FFF0E0, #F0E0C8)", "#6B4A2A"),
        "winter": ("linear-gradient(135deg, #E8EDF8, #D8E0F0)", "#2A3A5B"),
    }
    gradient, text_color = _GRADIENTS.get(colortype, _GRADIENTS["summer"])

    # Build swatches
    swatches = []
    for hx in hex_colors[:6]:
        swatches.append(
            _div([], width=48, height=48, borderRadius=8,
                 backgroundColor=hx,
                 border="1px solid rgba(0,0,0,0.08)")
        )

    root = _div(
        [
            _col(
                [
                    _text(name, 24, text_color, fontWeight=700,
                          textAlign="center", justifyContent="center", width="100%"),
                    _text(ct_label, 18, text_color,
                          textAlign="center", justifyContent="center", width="100%",
                          marginTop=4),
                ],
                gap=4,
                alignItems="center",
                padding="24px 20px 8px",
            ),
            _text("Твоя палитра:", 13, text_color,
                  textAlign="center", justifyContent="center", width="100%",
                  opacity=0.7),
            _row(swatches, gap=10, justifyContent="center", padding="8px 20px"),
            _text("Буду учитывать при подборе образов", 12, text_color,
                  textAlign="center", justifyContent="center", width="100%",
                  opacity=0.5, padding="0 20px 16px"),
        ],
        flexDirection="column",
        width="100%",
        height="100%",
        backgroundImage=gradient,
        borderRadius=20,
        alignItems="center",
    )

    return await _render_satori(root, 440, 300)


# ── Style passport (Stories card) ──────────────────────────────────────────

# Hex lookup for palette color names → hex values
_PASSPORT_HEX: dict[str, str] = {
    "белый": "#F5F5F5", "чёрный": "#2C2C2C", "серый": "#9E9E9E",
    "бежевый": "#D4C5A9", "синий": "#1565C0", "голубой": "#64B5F6",
    "красный": "#D32F2F", "розовый": "#F48FB1", "зелёный": "#388E3C",
    "коричневый": "#795548", "бордовый": "#800020", "хаки": "#827717",
    "лавандовый": "#B39DDB", "мятный": "#80CBC4", "персиковый": "#FFAB91",
    "горчичный": "#F9A825", "терракотовый": "#BF360C", "navy": "#1A237E",
    "изумрудный": "#00695C", "коралловый": "#FF7043", "сливовый": "#6A1B9A",
    "золотистый": "#FFD54F", "абрикосовый": "#FFCC80", "кремовый": "#FFF8E1",
    "пудровый": "#F8BBD0", "серо-голубой": "#90A4AE", "тёплый розовый": "#EF9A9A",
    "нежно-розовый": "#F8BBD0", "светло-голубой": "#B3E5FC", "лимонный": "#FFF9C4",
    "бирюзовый": "#4DB6AC", "дымчато-розовый": "#CE93D8",
}

_PASSPORT_CONTRAST_MAP = {"HIGH": 8, "MEDIUM": 5, "LOW": 3}

_PASSPORT_KIBBE_DESC: dict[str, str] = {
    "DRAMATIC": "структурные линии, выразительность",
    "NATURAL": "расслабленный силуэт, текстура",
    "CLASSIC": "сбалансированный силуэт, элегантность",
    "GAMINE": "компактный крой, смелые детали",
    "ROMANTIC": "мягкие линии, женственность",
}

_PASSPORT_ESSENCE_LABELS: dict[str, str] = {
    "DRAMATIC": "Bold Presence",
    "NATURAL": "Effortless Warmth",
    "CLASSIC": "Refined Elegance",
    "GAMINE": "Playful Edge",
    "ROMANTIC": "Soft Femininity",
}

_DEFAULT_PASSPORT_PALETTE = [
    "#B39DDB", "#64B5F6", "#80CBC4", "#F48FB1", "#FFAB91", "#FFF59D",
]


def _build_passport_palette(user) -> list[str]:
    """Extract up to 6 hex colors from user's colortype palette."""
    from worker.tasks.style_config import COLORTYPE_PALETTES

    colortype = getattr(user, "colortype", "") or ""
    palette_raw = COLORTYPE_PALETTES.get(colortype, {})
    if not palette_raw:
        return list(_DEFAULT_PASSPORT_PALETTE)

    palette_hex: list[str] = []
    for slot_colors in list(palette_raw.values())[:3]:
        for c in (slot_colors or [])[:3]:
            # Strip gender suffixes for lookup: "коралловая" → "коралловый"
            c_base = c.lower()
            for suffix in ("ая", "ое", "ый", "ий", "ые", "ие"):
                if c_base.endswith(suffix):
                    c_base = c_base[:-len(suffix)]
                    break
            # Try exact, then base form with common endings
            hex_val = _PASSPORT_HEX.get(c.lower())
            if not hex_val:
                for key, val in _PASSPORT_HEX.items():
                    if key.startswith(c_base) or c_base.startswith(key.rstrip("ый").rstrip("ий")):
                        hex_val = val
                        break
            hex_val = hex_val or "#BDBDBD"
            if hex_val not in palette_hex:
                palette_hex.append(hex_val)
            if len(palette_hex) >= 6:
                break
        if len(palette_hex) >= 6:
            break

    return palette_hex[:6] if len(palette_hex) >= 3 else list(_DEFAULT_PASSPORT_PALETTE)


async def _send_style_passport(message, user, lang: str = "ru") -> None:
    """Send style passport as Stories-ready photo (1080x1920)."""
    from services.brief_renderer import render_style_passport

    palette_hex = _build_passport_palette(user)

    kf = getattr(user, "kibbe_family", "") or ""
    ks = getattr(user, "kibbe_secondary", "") or ""
    se = getattr(user, "style_essence", "") or ""

    contrast_level = getattr(user, "contrast_level", "") or ""
    contrast_filled = _PASSPORT_CONTRAST_MAP.get(contrast_level, 5)

    png = await render_style_passport(
        name=user.name or "---",
        lang=lang,
        sub_season=getattr(user, "colortype", "") or "",
        palette=palette_hex,
        contrast_level=contrast_level,
        contrast_filled=contrast_filled,
        kibbe_primary=kf,
        kibbe_secondary=ks,
        kibbe_desc=_PASSPORT_KIBBE_DESC.get(kf, ""),
        essence_label=_PASSPORT_ESSENCE_LABELS.get(se, ""),
        tonal_depth=getattr(user, "tonal_depth", "") or "",
        chroma=getattr(user, "chroma", "") or "",
    )

    if not png:
        logger.warning("style_passport.render_failed", user_id=str(user.id))
        return

    caption_parts = [f"Стилевой профиль: {user.name}"]
    if user.colortype:
        caption_parts.append(f"\nЦветотип: {user.colortype}")
    if kf:
        arch = kf + (f" / {ks}" if ks else "")
        caption_parts.append(f"Архетип: {arch}")
    if se:
        caption_parts.append(f"Сущность: {_PASSPORT_ESSENCE_LABELS.get(se, se)}")
    caption_parts.append("\nСохрани в Stories -- пусть подруги тоже узнают свой тип!")
    caption = "\n".join(caption_parts)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Поделиться",
            switch_inline_query="Мой стиль от Касси! Узнай свой: t.me/fashioncastle_bot",
        )],
        [
            InlineKeyboardButton("Сохранить", callback_data="noop"),
            InlineKeyboardButton("Подобрать образы", callback_data="start_wardrobe"),
        ],
    ])

    from io import BytesIO
    await message.reply_photo(photo=BytesIO(png), caption=caption, reply_markup=kb)
