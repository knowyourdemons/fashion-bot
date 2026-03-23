"""Mood-aware styling: weather + weekday + context → outfit mood."""

_ENERGY_LEVELS = {"low": 1, "medium": 2, "high": 3}


def _max_energy(a: str, b: str) -> str:
    """Return the higher energy level using numeric comparison."""
    return a if _ENERGY_LEVELS.get(a, 2) >= _ENERGY_LEVELS.get(b, 2) else b


_WEEKDAY_NAMES_RU = {
    0: "понедельник", 1: "вторник", 2: "среда", 3: "четверг",
    4: "пятница", 5: "суббота", 6: "воскресенье",
}


def detect_mood(weather: dict, weekday: int, occasion: str = "") -> dict:
    """Detect mood context for outfit generation."""
    mood = {
        "energy": "medium",
        "color_mood": "neutral",
        "hint": "",
    }

    # Weather influence
    wmo = weather.get("wmo_day", weather.get("wmo_morning", 0))
    temp = weather.get("temp_now") or weather.get("temp_morning") or 15

    # Full WMO code sets
    _RAIN = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    _SNOW = {71, 73, 75, 77, 85, 86}
    _FOG = {45, 48}
    _OVERCAST = {2, 3}

    if wmo in _RAIN:
        mood["energy"] = "low"
        mood["color_mood"] = "warm"
        mood["hint"] = "Дождь — добавим тепла в образ!"
    elif wmo in _FOG:
        mood["energy"] = "low"
        mood["color_mood"] = "warm"
        mood["hint"] = "Туманно — уютный образ!"
    elif wmo in (0, 1) and temp > 15:  # sunny warm
        mood["energy"] = "high"
        mood["color_mood"] = "bright"
        mood["hint"] = "Солнечно — можно смелее!"
    elif wmo in _OVERCAST and temp < 10:
        mood["energy"] = "low"
        mood["color_mood"] = "warm"
        mood["hint"] = "Хмуро — яркий акцент поднимет настроение!"
    elif wmo in _SNOW:
        mood["energy"] = "medium"
        mood["color_mood"] = "warm"
        mood["hint"] = "Снежно — уютный look!"

    # Weekday influence
    if weekday == 0:  # Monday
        if not mood["hint"]:
            mood["hint"] = "Понедельник — начнём уверенно!"
        mood["energy"] = "medium"
    elif weekday == 4:  # Friday
        mood["energy"] = "high"
        if not mood["hint"]:
            mood["hint"] = "Пятница — можно расслабиться!"
        if mood["color_mood"] == "neutral":
            mood["color_mood"] = "bright"
    elif weekday >= 5:  # Weekend
        mood["energy"] = "high"
        if not mood["hint"]:
            mood["hint"] = "Выходной — что душе угодно!"

    # Occasion override
    if occasion in ("офис", "работа", "школа"):
        mood["energy"] = _max_energy(mood["energy"], "medium")
    elif occasion in ("свидание", "событие"):
        mood["energy"] = "high"
        mood["color_mood"] = "bright"

    return mood


def get_mood_prompt(mood: dict) -> str:
    """Format mood for AI prompt. Empty if neutral."""
    if mood["energy"] == "medium" and mood["color_mood"] == "neutral" and not mood["hint"]:
        return ""

    lines = []
    if mood["hint"]:
        lines.append(f"Настроение дня: {mood['hint']}")

    if mood["energy"] == "low":
        lines.append("→ Комфорт, мягкие текстуры, тёплые цвета")
    elif mood["energy"] == "high":
        lines.append("→ Можно экспериментировать, яркие акценты")

    if mood["color_mood"] == "warm":
        lines.append("→ Тёплые цвета: бежевый, горчичный, терракот")
    elif mood["color_mood"] == "bright":
        lines.append("→ Яркий акцент (сумка/шарф/обувь)")

    return "\n".join(lines)
