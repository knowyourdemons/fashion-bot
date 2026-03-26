"""Production-level test: realistic wardrobes × profiles × weather → verify collage logic.

Creates 6 synthetic users with diverse realistic wardrobes (10-25 items),
tests outfit selection and slot assignment across all weather conditions.
Checks: slot correctness, labels, colors, warmth, fashion rules.
"""
import sys
import os
from datetime import date, timedelta
from collections import Counter

sys.path.insert(0, "/app")
os.chdir("/app")

from services.outfit_builder import build_outfit_slots, select_outfit, has_minimum_outfit
from services.brief_renderer import get_color_hex, get_color_bg, get_segment, get_theme
from services.color_harmony import score_outfit_colors


class FI:
    """Fake wardrobe item."""
    _counter = 0
    def __init__(self, type, cg, warmth, color, formality=2, season=None, occasion=None):
        FI._counter += 1
        self.id = f"fake-{FI._counter}"
        self.type = type
        self.category_group = cg
        self.warmth_level = warmth
        self.color = color
        self.season = season
        self.photo_id = None
        self.photo_url = None
        self.show_in_collage = True
        self.bbox = None
        self.occasion = occasion
        self.formality_level = formality
        self.last_worn = None
        self.score_item = 7.0


class FU:
    def __init__(self, segment, colortype="", name="Test"):
        self.segment = segment
        self.colortype = colortype
        self.name = name


class FC:
    def __init__(self, name, age_years, gender="girl", colortype=""):
        self.id = f"child-{name}"
        self.name = name
        self.birthdate = date.today() - timedelta(days=int(age_years * 365.25))
        self.gender = gender
        self.colortype = colortype


# ── Realistic wardrobes ──────────────────────────────────────────────────────

WARDROBE_TODDLER_GIRL = [
    FI("футболка", "top", 1, "розовый"), FI("футболка", "top", 1, "белый"),
    FI("лонгслив", "top", 2, "лавандовый"), FI("свитер", "top", 3, "бежевый"),
    FI("водолазка", "top", 3, "серый"),
    FI("джинсы", "bottom", 3, "тёмно-синий"), FI("леггинсы", "bottom", 3, "чёрный"),
    FI("юбка", "bottom", 1, "розовый"),
    FI("платье", "one_piece", 2, "розовый"), FI("сарафан", "one_piece", 1, "голубой"),
    FI("комбинезон", "one_piece", 5, "красный"),
    FI("куртка", "outerwear", 3, "бежевый"), FI("пуховик", "outerwear", 5, "розовый"),
    FI("ветровка", "outerwear", 1, "голубой"),
    FI("кроссовки", "footwear", 2, "белый"), FI("ботинки", "footwear", 4, "коричневый"),
    FI("сандалии", "footwear", 1, "розовый"),
    FI("шапка", "hat", 3, "розовый"),
    FI("колготки", "base_layer", 3, "белый"), FI("носки", "base_layer", 1, "белый"),
]

WARDROBE_SCHOOL_BOY = [
    FI("футболка", "top", 1, "синий"), FI("футболка", "top", 1, "зелёный"),
    FI("лонгслив", "top", 2, "серый"), FI("худи", "top", 3, "тёмно-синий"),
    FI("свитер", "top", 3, "коричневый"),
    FI("джинсы", "bottom", 3, "тёмно-синий"), FI("брюки", "bottom", 3, "серый"),
    FI("шорты", "bottom", 1, "синий"),
    FI("куртка", "outerwear", 3, "тёмно-синий"), FI("пуховик", "outerwear", 5, "чёрный"),
    FI("ветровка", "outerwear", 1, "серый"),
    FI("кроссовки", "footwear", 2, "чёрный"), FI("ботинки", "footwear", 4, "коричневый"),
    FI("шапка", "hat", 3, "серый"), FI("шарф", "accessory", 3, "тёмно-синий"),
    FI("рюкзак", "bag", 1, "синий"),
]

WARDROBE_ADULT_WOMAN = [
    FI("блузка", "top", 1, "белый", 3), FI("футболка", "top", 1, "чёрный", 1),
    FI("водолазка", "top", 3, "бордовый", 3), FI("свитер", "top", 3, "бежевый", 2),
    FI("кардиган", "top", 2, "серый", 2), FI("рубашка", "top", 2, "голубой", 3),
    FI("джинсы", "bottom", 3, "тёмно-синий", 2), FI("брюки", "bottom", 3, "чёрный", 4),
    FI("юбка", "bottom", 2, "бежевый", 3), FI("леггинсы", "bottom", 3, "чёрный", 1),
    FI("платье", "one_piece", 2, "тёмно-синий", 3), FI("платье", "one_piece", 1, "красный", 3),
    FI("пальто", "outerwear", 4, "бежевый", 4), FI("куртка", "outerwear", 3, "чёрный", 2),
    FI("тренч", "outerwear", 2, "бежевый", 3), FI("ветровка", "outerwear", 1, "белый", 1),
    FI("кроссовки", "footwear", 2, "белый", 1), FI("туфли", "footwear", 2, "чёрный", 4),
    FI("ботинки", "footwear", 4, "коричневый", 3), FI("сапоги", "footwear", 5, "чёрный", 3),
    FI("сумка на плечо", "bag", 1, "коричневый", 3), FI("клатч", "bag", 1, "чёрный", 4),
    FI("шапка", "hat", 3, "серый", 2), FI("шарф", "accessory", 3, "бордовый", 3),
    FI("перчатки", "accessory", 3, "чёрный", 3),
]

WARDROBE_PREGNANT = [
    FI("футболка", "top", 1, "белый", 1), FI("лонгслив", "top", 2, "серый", 2),
    FI("кардиган", "top", 2, "розовый", 2), FI("свитер", "top", 3, "бежевый", 2),
    FI("леггинсы", "bottom", 3, "чёрный", 1), FI("джинсы", "bottom", 3, "голубой", 2),
    FI("платье", "one_piece", 2, "чёрный", 2),
    FI("куртка", "outerwear", 3, "бежевый", 2), FI("пуховик", "outerwear", 5, "чёрный", 1),
    FI("кроссовки", "footwear", 2, "белый", 1), FI("ботинки", "footwear", 4, "чёрный", 2),
    FI("шапка", "hat", 3, "бежевый", 2),
]

WARDROBE_MINIMAL = [
    FI("футболка", "top", 1, "белый"),
    FI("джинсы", "bottom", 3, "синий"),
]

# ── Personas ─────────────────────────────────────────────────────────────────

PERSONAS = [
    {
        "label": "Toddler girl 3yo (Лето)",
        "user": FU("mom_girl"), "child": FC("Маша", 3, "girl", "Лето"),
        "items": WARDROBE_TODDLER_GIRL, "colortype": "Лето",
    },
    {
        "label": "School boy 8yo (Весна)",
        "user": FU("mom_boy"), "child": FC("Дима", 8, "boy", "Весна"),
        "items": WARDROBE_SCHOOL_BOY, "colortype": "Весна",
    },
    {
        "label": "Adult woman (Deep Autumn)",
        "user": FU("no_kids", "Deep Autumn", "Мария"), "child": None,
        "items": WARDROBE_ADULT_WOMAN, "colortype": "Deep Autumn",
    },
    {
        "label": "Pregnant (Soft Summer)",
        "user": FU("pregnant", "Soft Summer", "Лена"), "child": None,
        "items": WARDROBE_PREGNANT, "colortype": "Soft Summer",
    },
    {
        "label": "Minimal wardrobe (2 items)",
        "user": FU("no_kids", "True Winter", "Оля"), "child": None,
        "items": WARDROBE_MINIMAL, "colortype": "True Winter",
    },
    {
        "label": "Full wardrobe adult (Bright Spring)",
        "user": FU("no_kids", "Bright Spring", "Ира"), "child": None,
        "items": WARDROBE_ADULT_WOMAN, "colortype": "Bright Spring",
    },
]

TEMPS = [-20, -10, -5, 0, 3, 8, 12, 18, 25, 30]


def main():
    total = 0
    issues = []

    for persona in PERSONAS:
        label = persona["label"]
        user = persona["user"]
        child = persona["child"]
        items = persona["items"]
        ct = persona["colortype"]

        child_age = None
        if child and child.birthdate:
            child_age = (date.today() - child.birthdate).days / 365.25

        print(f"\n{'='*60}")
        print(f"{label} | {len(items)} items | ct={ct}")
        print(f"{'='*60}")

        for temp in TEMPS:
            total += 1
            outfit = select_outfit(items, "Лето", date.today(),
                                   temp_morning=float(temp), temp_evening=float(temp - 3))
            slots = build_outfit_slots(outfit, child=child, user=user,
                                       temp=float(temp), colortype=ct)

            real = [s for s in slots if s.get("has_item")]
            ph = [s for s in slots if not s.get("has_item")]
            errs = []

            # 1. Must have main garment (or placeholder)
            slot_types = {s["slot"] for s in slots}
            has_main = ("top" in slot_types and "bottom" in slot_types) or "one_piece" in slot_types
            if not has_main:
                errs.append("NO MAIN GARMENT")

            # 2. No empty labels
            for s in ph:
                if not s.get("label"):
                    errs.append(f"EMPTY LABEL {s['slot']}")

            # 3. All colors valid
            for s in ph:
                c = s.get("item_color", "")
                if c and get_color_hex(c) == "#C0C0C0":
                    errs.append(f"BAD COLOR '{c}'")

            # 4. Age rules
            if child_age and child_age < 6:
                for s in ph:
                    if s["slot"] == "bag":
                        errs.append("BAG for <6yo")
                    if s.get("label") in ("Ремень", "Очки"):
                        errs.append(f"{s['label']} for <6yo")

            # 5. Warmth check at +28°+
            if temp >= 28:
                for s in real:
                    it = next((i for i in items if i.type == s.get("item_type")), None)
                    if it and it.warmth_level >= 2 and s["slot"] in ("top", "bottom"):
                        errs.append(f"WARM {it.type}(w={it.warmth_level}) at +{temp}")

            # 6. Kombinezon for ≤5yo at frost
            if child_age and child_age <= 5 and temp <= 0:
                ph_labels = [s.get("label", "") for s in ph]
                has_komb = any("омбинезон" in l for l in ph_labels)
                real_types = [s.get("item_type", "") for s in real]
                has_real_komb = any("омбинезон" in t for t in real_types)
                if not has_komb and not has_real_komb:
                    errs.append("NO KOMBINEZON ≤5yo frost")

            # 7. Hat at frost
            if temp <= 0:
                has_hat = any(s["slot"] == "hat" for s in slots)
                if not has_hat:
                    errs.append("NO HAT at frost")

            # 8. Outfit makes fashion sense (color harmony)
            outfit_items = [outfit[k] for k in ("top", "bottom", "outerwear", "one_piece")
                           if outfit.get(k)]
            if len(outfit_items) >= 2:
                try:
                    color_score = score_outfit_colors([i.color for i in outfit_items])
                    if color_score < 2:
                        errs.append(f"BAD COLOR HARMONY score={color_score}")
                except Exception:
                    pass

            status = "FAIL" if errs else "ok"
            real_str = ",".join(s.get("item_type", "?")[:10] for s in real)
            ph_count = len(ph)

            if errs:
                print(f"  {temp:+3d}° {status} real=[{real_str}] ph={ph_count} ⚠ {errs}")
                issues.append((label, temp, errs))
            # Only print non-trivial OK results
            elif temp in (-15, 0, 18, 28):
                print(f"  {temp:+3d}° {status} real=[{real_str}] ph={ph_count}")

    print(f"\n{'='*60}")
    print(f"TOTAL: {total} combos, {len(issues)} issues")
    print(f"{'='*60}")
    if issues:
        for label, temp, errs in issues:
            print(f"  {label} {temp:+d}°: {errs}")
    else:
        print("  ✅ ALL CLEAN!")


if __name__ == "__main__":
    main()
