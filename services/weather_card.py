"""
Погодная карточка для режима B (мало вещей в гардеробе).
PIL render: 440x500 PNG.
"""
import io
from datetime import date

from PIL import Image, ImageDraw, ImageFont
import structlog

logger = structlog.get_logger()

_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

_DAY_NAMES = {0: "понедельник", 1: "вторник", 2: "среда", 3: "четверг", 4: "пятница", 5: "суббота", 6: "воскресенье"}

# ── Season palette ────────────────────────────────────────────────────────────

def season_palette(temp: float) -> list[dict]:
    """Рекомендуемая палитра по температуре."""
    if temp < 0:
        return [
            {"hex": "#8B4513", "name": "тёплый", "desc": "куртка/пуховик"},
            {"hex": "#F5F5DC", "name": "база", "desc": "флис/кофта"},
            {"hex": "#CD5C5C", "name": "акцент", "desc": "шапка/шарф"},
            {"hex": "#696969", "name": "нейтр", "desc": "штаны/обувь"},
        ]
    elif temp < 10:
        return [
            {"hex": "#D2B48C", "name": "тёплый", "desc": "куртка/ветровка"},
            {"hex": "#F0E68C", "name": "светлый", "desc": "кофта/лонгслив"},
            {"hex": "#8FBC8F", "name": "акцент", "desc": "юбка/шарф"},
            {"hex": "#778899", "name": "база", "desc": "леггинсы/обувь"},
        ]
    elif temp < 20:
        return [
            {"hex": "#FFB6C1", "name": "нежный", "desc": "платье/топ"},
            {"hex": "#E6E6FA", "name": "светлый", "desc": "кофта"},
            {"hex": "#98FB98", "name": "свежий", "desc": "юбка/шорты"},
            {"hex": "#FFDEAD", "name": "тёплый", "desc": "сандалии"},
        ]
    else:
        return [
            {"hex": "#FFFFFF", "name": "белый", "desc": "футболка"},
            {"hex": "#87CEEB", "name": "голубой", "desc": "шорты"},
            {"hex": "#FFD700", "name": "яркий", "desc": "акцент"},
            {"hex": "#F5DEB3", "name": "песочный", "desc": "сандалии"},
        ]


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _precip_text(precip_max: float) -> str:
    if precip_max >= 70:
        return "Дождь вероятен"
    elif precip_max >= 40:
        return "Возможен дождь"
    else:
        return "Без осадков"


def _sign(t: float) -> str:
    return "+" if t >= 0 else ""


def build_weather_card(
    child_name: str,
    day_type: str,
    temp_morning: float,
    temp_day: float | None,
    temp_evening: float,
    precip_max: float,
    advice_text: str,
    items_count: int,
    items_needed: int = 8,
    temp_now: float | None = None,
) -> bytes:
    """Рендерит погодную карточку 440x520 PNG через PIL."""
    W, H = 440, 520
    card = Image.new("RGB", (W, H), (255, 252, 248))
    draw = ImageDraw.Draw(card)

    try:
        font_title = ImageFont.truetype(_DEJAVU_BOLD, 20)
        font_sub = ImageFont.truetype(_DEJAVU, 14)
        font_weather = ImageFont.truetype(_DEJAVU, 16)
        font_palette_name = ImageFont.truetype(_DEJAVU, 11)
        font_advice = ImageFont.truetype(_DEJAVU, 13)
        font_cta = ImageFont.truetype(_DEJAVU_BOLD, 12)
        font_footer = ImageFont.truetype(_DEJAVU, 11)
    except Exception:
        font_title = font_sub = font_weather = font_palette_name = ImageFont.load_default()
        font_advice = font_cta = font_footer = font_title

    y = 20

    # ── Header ──
    draw.text((20, y), "Доброе утро!", fill=(80, 60, 80), font=font_title)
    y += 28
    today = date.today()
    day_name = _DAY_NAMES.get(today.weekday(), "")
    subtitle = f"{child_name} · {day_type} · {day_name}"
    draw.text((20, y), subtitle, fill=(140, 120, 140), font=font_sub)
    y += 30

    # ── Weather box ──
    box_x, box_y = 20, y
    box_w, box_h = W - 40, 95
    draw.rounded_rectangle(
        [(box_x, box_y), (box_x + box_w, box_y + box_h)],
        radius=12, fill=(248, 245, 252),
    )

    wy = box_y + 12
    if temp_now is not None:
        sn = _sign(temp_now)
        draw.text((35, wy), f"Сейчас  {sn}{temp_now:.0f}°C", fill=(70, 50, 70), font=font_weather)
    else:
        sm = _sign(temp_morning)
        draw.text((35, wy), f"Утро    {sm}{temp_morning:.0f}°C", fill=(70, 50, 70), font=font_weather)
    wy += 22
    if temp_day is not None:
        sd = _sign(temp_day)
        draw.text((35, wy), f"День    {sd}{temp_day:.0f}°C", fill=(70, 50, 70), font=font_weather)
    wy += 22
    se = _sign(temp_evening)
    draw.text((35, wy), f"Вечер   {se}{temp_evening:.0f}°C", fill=(70, 50, 70), font=font_weather)

    # Precip on the right
    precip_label = _precip_text(precip_max)
    draw.text((260, box_y + 40), precip_label, fill=(120, 100, 130), font=font_sub)

    y = box_y + box_h + 15

    # ── Palette ──
    draw.text((20, y), "Рекомендуемая палитра:", fill=(100, 80, 100), font=font_sub)
    y += 22
    palette = season_palette(temp_morning)
    block_size = 50
    gap = 15
    start_x = 20
    for i, p in enumerate(palette):
        bx = start_x + i * (block_size + gap)
        rgb = _hex_to_rgb(p["hex"])
        draw.rounded_rectangle(
            [(bx, y), (bx + block_size, y + block_size)],
            radius=8, fill=rgb, outline=(220, 210, 225), width=1,
        )
        # Name below block
        draw.text((bx + 2, y + block_size + 3), p["name"], fill=(140, 120, 140), font=font_palette_name)
    y += block_size + 22

    # ── Advice ──
    draw.text((20, y), "Совет Касси:", fill=(100, 80, 100), font=font_sub)
    y += 20

    # Word-wrap advice text
    max_w = W - 40
    words = advice_text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        try:
            tw = font_advice.getbbox(test)[2]
        except Exception:
            tw = len(test) * 7
        if tw > max_w and current_line:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test
    if current_line:
        lines.append(current_line)

    for line in lines[:5]:
        draw.text((20, y), line, fill=(80, 60, 80), font=font_advice)
        y += 18

    y += 10

    # ── CTA ──
    needed = max(0, items_needed - items_count)
    if needed > 0:
        cta = f"Добавь ещё {needed} вещей — соберу образ из ТВОИХ вещей!"
        draw.text((20, y), cta, fill=(140, 80, 160), font=font_cta)
        y += 22

    # ── Footer ──
    y = H - 25
    draw.text((20, y), "Касси · твой личный стилист", fill=(180, 165, 190), font=font_footer)

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()


async def generate_weather_advice(
    pool,
    child_name: str,
    temp_morning: float,
    temp_day: float | None,
    temp_evening: float,
    precip_max: float,
    day_type: str,
) -> str:
    """Haiku генерирует совет по одежде на основе погоды."""
    sm = _sign(temp_morning)
    se = _sign(temp_evening)
    sd = _sign(temp_day) if temp_day is not None else ""
    day_str = f"{sd}{temp_day:.0f}°C" if temp_day is not None else "нет данных"

    prompt = (
        f"Ты Касси — детский стилист. Коротко (3-4 предложения) посоветуй "
        f"что надеть ребёнку {child_name}.\n\n"
        f"Погода:\n"
        f"- Утро: {sm}{temp_morning:.0f}°C\n"
        f"- День: {day_str}\n"
        f"- Вечер: {se}{temp_evening:.0f}°C\n"
        f"- Осадки: {_precip_text(precip_max)}\n\n"
        f"Контекст: {day_type}\n\n"
        f"Формат: практичный совет, как подруга. Не перечисляй все вещи — выдели главное. "
        f"Упомяни если к вечеру похолодает (надо взять что-то с собой). "
        f"Не используй markdown символы."
    )

    try:
        resp = await pool.create_message(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.warning("weather_card.haiku_failed", error=str(e))
        if temp_morning <= 5:
            return f"Сегодня холодно ({sm}{temp_morning:.0f}°C) — куртка и шапка обязательно. Под куртку кофту или лонгслив. К вечеру похолодает — возьми шарф."
        elif temp_morning <= 15:
            return f"Прохладно ({sm}{temp_morning:.0f}°C) — лёгкая куртка или ветровка. Под неё кофту. К вечеру прохладнее — возьми запасной слой."
        else:
            return f"Тепло ({sm}{temp_morning:.0f}°C) — лёгкая одежда. Если к вечеру прохладнее — возьми кофту с собой."
