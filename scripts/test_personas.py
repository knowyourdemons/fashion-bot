"""Test collage generation for synthetic personas across age groups and colortypes."""
import asyncio
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, "/app")
os.chdir("/app")


# Synthetic wardrobe items
class FakeItem:
    def __init__(self, type, cg, warmth, color, season=None):
        self.id = f"fake-{type}-{color}"
        self.type = type
        self.category_group = cg
        self.warmth_level = warmth
        self.color = color
        self.season = season
        self.photo_id = None
        self.photo_url = None
        self.show_in_collage = True
        self.bbox = None
        self.occasion = None
        self.formality_level = 2
        self.last_worn = None
        self.score_item = 7.0


class FakeUser:
    def __init__(self, segment="no_kids", colortype="", name="Test"):
        self.segment = segment
        self.colortype = colortype
        self.name = name
        self.city = "Vilnius"
        self.timezone = "Europe/Vilnius"


class FakeChild:
    def __init__(self, name, birthdate, gender="girl", colortype=""):
        self.id = f"fake-child-{name}"
        self.name = name
        self.birthdate = birthdate
        self.gender = gender
        self.colortype = colortype


# Wardrobe sets
BASIC_WARDROBE = [
    FakeItem("футболка", "top", 1, "белый"),
    FakeItem("лонгслив", "top", 2, "голубой"),
    FakeItem("свитер", "top", 3, "бежевый"),
    FakeItem("кофта", "top", 3, "розовый"),
    FakeItem("шорты", "bottom", 1, "синий"),
    FakeItem("джинсы", "bottom", 3, "тёмно-синий"),
    FakeItem("леггинсы", "bottom", 3, "чёрный"),
    FakeItem("платье", "one_piece", 2, "розовый"),
    FakeItem("кроссовки", "footwear", 2, "белый"),
    FakeItem("ботинки", "footwear", 4, "коричневый"),
    FakeItem("куртка", "outerwear", 3, "бежевый"),
    FakeItem("пуховик", "outerwear", 5, "чёрный"),
    FakeItem("шапка", "hat", 3, "серый"),
]


PERSONAS = [
    {
        "label": "Baby 1yo girl",
        "user": FakeUser("mom_girl"),
        "child": FakeChild("Маша", date.today() - timedelta(days=365), "girl", "Лето"),
        "items": BASIC_WARDROBE,
        "temps": [-15, 0, 18, 28],
    },
    {
        "label": "Toddler 3yo boy",
        "user": FakeUser("mom_boy"),
        "child": FakeChild("Дима", date.today() - timedelta(days=365*3), "boy", "Весна"),
        "items": BASIC_WARDROBE,
        "temps": [-15, 0, 18, 28],
    },
    {
        "label": "School 8yo girl",
        "user": FakeUser("mom_girl"),
        "child": FakeChild("Соня", date.today() - timedelta(days=365*8), "girl", "Soft Summer"),
        "items": BASIC_WARDROBE,
        "temps": [-15, 8, 18, 28],
    },
    {
        "label": "Teen 14yo girl",
        "user": FakeUser("mom_girl"),
        "child": FakeChild("Аня", date.today() - timedelta(days=365*14), "girl", "Bright Spring"),
        "items": BASIC_WARDROBE,
        "temps": [-15, 8, 18, 28],
    },
    {
        "label": "Adult woman",
        "user": FakeUser("no_kids", "Deep Autumn", "Мария"),
        "child": None,
        "items": BASIC_WARDROBE,
        "temps": [-15, 0, 8, 18, 28],
    },
    {
        "label": "Pregnant",
        "user": FakeUser("pregnant", "True Winter", "Лена"),
        "child": None,
        "items": BASIC_WARDROBE,
        "temps": [0, 18],
    },
]


async def main():
    from config import settings
    from telegram import Bot
    from core.redis import init_redis
    from services.brief_card import build_brief_card
    from services.brief_renderer import prepare_weather_data
    from services.outfit_builder import build_outfit_slots, select_outfit

    await init_redis()
    bot = Bot(token=settings.telegram_bot_token)
    CHAT = 195169

    for persona in PERSONAS:
        label = persona["label"]
        user = persona["user"]
        child = persona["child"]
        items = persona["items"]

        await bot.send_message(CHAT, f"═══ {label} (colortype={child.colortype if child else user.colortype}) ═══")

        for temp in persona["temps"]:
            wx = {
                "temp_now": float(temp), "temp_morning": float(temp - 1),
                "temp_day": float(temp + 2), "temp_evening": float(temp - 3),
                "precip_evening": 0, "precip_max": 5,
                "wmo_morning": 71 if temp < 0 else 3 if temp < 15 else 0,
                "wmo_day": 71 if temp < 0 else 3 if temp < 15 else 0,
                "wmo_evening": 71 if temp < 0 else 51 if temp < 15 else 0,
            }

            outfit = select_outfit(items, "Лето", date.today(),
                                   temp_morning=float(temp), temp_evening=float(temp - 3))
            colortype = child.colortype if child else user.colortype
            slots = build_outfit_slots(outfit, child=child, user=user,
                                       temp=float(temp), colortype=colortype)

            real = [s["slot"] for s in slots if s.get("has_item")]
            ph = [(s["slot"], s.get("label", "")) for s in slots if not s.get("has_item")]

            png = await build_brief_card(user, child, outfit, wx, slots,
                                         advice_text=f"{temp:+d}°", colortype=colortype)
            if png:
                caption = f"{label} {temp:+d}° | real={real} | ph={len(ph)}"
                await bot.send_photo(chat_id=CHAT, photo=png, caption=caption[:1024])

    await bot.send_message(CHAT, "═══ DONE ═══")
    print("SENT all!")


if __name__ == "__main__":
    asyncio.run(main())
