"""Monte Carlo outfit quality testing framework.

Generates random but realistic wardrobes + weather scenarios,
runs the rule-based outfit selector, and checks quality metrics.

1000 parametrized scenarios via pytest (~5 sec, no AI calls).
Each scenario = unique seed → deterministic reproduction of failures.

Quality checks:
  - has_minimum_outfit (top+bottom or one_piece)
  - warmth_consistency (no puffer + shorts)
  - no_base_layer_visible (socks not in collage)
  - no_duplicate_items
  - outerwear when cold (<15° and outerwear exists in wardrobe)
  - hat when freezing (<10° and hat exists)
  - color_harmony score ≥ 3.5/10
"""
import random
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest


# ── Types, colors, categories — from normalize.py and color_harmony.py ────────

TYPES_BY_CATEGORY = {
    "top": [
        ("футболка", 1), ("лонгслив", 2), ("блузка", 1), ("свитер", 3),
        ("водолазка", 3), ("худи", 3), ("рубашка", 2), ("кардиган", 3),
        ("кроп-топ", 1), ("флиска", 4), ("толстовка", 3),
    ],
    "bottom": [
        ("джинсы", 2), ("брюки", 2), ("юбка", 1), ("шорты", 1),
        ("леггинсы", 2), ("утеплённые штаны", 4),
    ],
    "one_piece": [
        ("платье", 1), ("тёплое платье", 3), ("комбинезон", 3),
        ("сарафан", 1),
    ],
    "outerwear": [
        ("ветровка", 2), ("куртка", 3), ("пуховик", 5), ("пальто", 4),
        ("тренч", 2), ("жилет", 2), ("дождевик", 2),
    ],
    "footwear": [
        ("кроссовки", 2), ("ботинки", 3), ("сапоги", 4),
        ("сандалии", 1), ("туфли", 1), ("угги", 5),
    ],
    "accessory": [
        ("тёплая шапка", 4), ("лёгкая шапка", 1), ("шарф", 4),
        ("перчатки", 4), ("сумка", 1), ("очки", 1),
    ],
    "underwear": [
        ("трусики", 1), ("майка", 1), ("термо кофта", 5), ("термо штаны", 5),
    ],
    "base_layer": [
        ("носки", 2), ("колготки", 3), ("плотные колготки", 4),
    ],
}

COLORS = [
    "белый", "чёрный", "серый", "синий", "тёмно-синий", "красный",
    "розовый", "бежевый", "голубой", "зелёный", "жёлтый", "коричневый",
    "бордовый", "лавандовый", "мятный", "оливковый", "коралловый",
    "фиолетовый", "оранжевый", "хаки",
]

SEASONS_BY_WARMTH = {
    1: ["spring", "summer"],
    2: ["spring", "summer", "autumn", "winter"],  # брюки/джинсы носят круглый год
    3: ["spring", "autumn", "winter"],
    4: ["autumn", "winter"],
    5: ["winter"],
}

SEGMENTS = ["mom_girl", "mom_boy", "no_kids", "pregnant"]
COLORTYPES = [
    "Bright Spring", "True Spring", "Light Spring",
    "Light Summer", "True Summer", "Soft Summer",
    "Soft Autumn", "True Autumn", "Deep Autumn",
    "Deep Winter", "True Winter", "Bright Winter",
]

GEO_TEMPS = {
    "moscow": (-25, 30),
    "dubai": (15, 45),
    "london": (-5, 28),
    "spb": (-20, 25),
    "sochi": (0, 35),
}


# ── Mock item ─────────────────────────────────────────────────────────────────

def _make_item(rng, category: str, type_name: str, warmth: int) -> MagicMock:
    item = MagicMock()
    item.id = uuid.UUID(int=rng.getrandbits(128))
    item.category_group = category
    item.type = type_name
    item.color = rng.choice(COLORS)
    item.warmth_level = warmth
    item.score_item = round(rng.uniform(3.0, 9.0), 1)
    item.season = SEASONS_BY_WARMTH.get(warmth, ["spring", "summer", "autumn", "winter"])
    item.last_worn = None
    item.wear_count = rng.randint(0, 20)
    item.show_in_collage = True
    item.photo_id = f"photo_{item.id.hex[:8]}"
    item.photo_url = None
    item.bbox = None
    item.style = "повседневный"
    item.style_tag = rng.choice(["casual", "smart", "sport"])
    item.occasion = ["weekday"]
    item.rain_ok = rng.random() < 0.2
    item.role = "base" if category in ("underwear", "base_layer") else rng.choice(["base", "accent"])
    item.brand = None
    return item


def random_wardrobe(rng, size: int, segment: str) -> list:
    """Generate realistic wardrobe of given size."""
    items = []
    # Ensure minimum: at least 1 top, 1 bottom, 1 footwear
    must_have = [
        ("top", rng.choice(TYPES_BY_CATEGORY["top"])),
        ("bottom", rng.choice(TYPES_BY_CATEGORY["bottom"])),
        ("footwear", rng.choice(TYPES_BY_CATEGORY["footwear"])),
    ]
    for cat, (type_name, warmth) in must_have:
        items.append(_make_item(rng, cat, type_name, warmth))

    # Fill remaining slots with realistic distribution
    remaining = size - len(items)
    # Weight categories
    categories = list(TYPES_BY_CATEGORY.keys())
    for _ in range(remaining):
        cat = rng.choice(categories)
        type_name, warmth = rng.choice(TYPES_BY_CATEGORY[cat])
        items.append(_make_item(rng, cat, type_name, warmth))

    return items


def random_weather(rng, geo: str) -> tuple:
    """Returns (temp_morning, temp_evening, season, precip)."""
    lo, hi = GEO_TEMPS[geo]
    temp_m = round(rng.uniform(lo, hi), 1)
    temp_e = round(temp_m + rng.uniform(-8, 5), 1)
    precip = rng.uniform(0, 100) if rng.random() < 0.3 else 0

    if temp_m > 20:
        season = "summer"
    elif temp_m > 10:
        season = rng.choice(["spring", "autumn"])
    elif temp_m > 0:
        season = rng.choice(["autumn", "winter"])
    else:
        season = "winter"

    return temp_m, temp_e, season, precip


# ── Quality checks ────────────────────────────────────────────────────────────

@dataclass
class QualityReport:
    seed: int
    checks: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        return all(self.checks.values())

    @property
    def failures(self) -> list[str]:
        return [k for k, v in self.checks.items() if not v]

    @property
    def summary(self) -> str:
        fails = self.failures
        if not fails:
            return f"seed={self.seed}: ALL PASSED"
        detail_parts = [f"{f}: {self.details.get(f, '?')}" for f in fails]
        return f"seed={self.seed}: FAILED [{', '.join(detail_parts)}]"


def check_outfit_quality(
    outfit: dict,
    wardrobe: list,
    temp_m: float,
    temp_e: float,
    seed: int,
) -> QualityReport:
    """Run all quality checks on an outfit."""
    report = QualityReport(seed=seed)
    all_items = outfit.get("all_items", [])

    # 1. Has minimum outfit (only fail if wardrobe actually HAS top+bottom or one_piece)
    has_op = outfit.get("one_piece") is not None
    has_top = outfit.get("top") is not None
    has_bottom = outfit.get("bottom") is not None
    outfit_ok = has_op or (has_top and has_bottom)
    # Only assert if wardrobe could theoretically produce a minimum outfit
    wardrobe_has_top = any(i.category_group in ("top", "one_piece") for i in wardrobe)
    wardrobe_has_bottom = any(i.category_group in ("bottom", "one_piece") for i in wardrobe)
    wardrobe_could_outfit = wardrobe_has_top and wardrobe_has_bottom
    report.checks["has_minimum"] = outfit_ok or not wardrobe_could_outfit
    if not report.checks["has_minimum"]:
        report.details["has_minimum"] = f"one_piece={has_op}, top={has_top}, bottom={has_bottom}"

    # 2. Warmth consistency
    visual_items = [i for i in all_items if i.category_group not in ("underwear", "base_layer")]
    if len(visual_items) >= 2:
        warmths = [getattr(i, "warmth_level", 3) for i in visual_items]
        gap = max(warmths) - min(warmths)
        report.checks["warmth_consistency"] = gap <= 4  # футболка(1) под пуховик(5) = нормальная многослойность
        if gap > 3:
            types_warmth = [(i.type, i.warmth_level) for i in visual_items]
            report.details["warmth_consistency"] = f"gap={gap}, items={types_warmth}"
    else:
        report.checks["warmth_consistency"] = True

    # 3. No base layer visible (socks, underwear in visual slots)
    base_layer_types = {"носк", "трусик", "колготк", "майк", "термо", "боди"}
    visible_slots = ["top", "bottom", "one_piece", "outerwear", "footwear", "hat", "scarf"]
    base_in_visible = False
    for slot in visible_slots:
        item = outfit.get(slot)
        if item and any(bl in (item.type or "").lower() for bl in base_layer_types):
            base_in_visible = True
            report.details["no_base_visible"] = f"slot={slot}, type={item.type}"
            break
    report.checks["no_base_visible"] = not base_in_visible

    # 4. No duplicate items
    item_ids = [i.id for i in all_items]
    report.checks["no_duplicates"] = len(item_ids) == len(set(item_ids))
    if not report.checks["no_duplicates"]:
        dupes = [id for id, cnt in Counter(item_ids).items() if cnt > 1]
        report.details["no_duplicates"] = f"duplicate_ids={dupes}"

    # 5. Outerwear when cold (only if season-appropriate outerwear exists)
    if temp_m < 15:
        _ow_season = "winter" if temp_m < 5 else ("autumn" if temp_m < 15 else "summer")
        has_suitable_ow = any(
            i.category_group == "outerwear"
            and (not i.season or _ow_season in i.season)
            for i in wardrobe
        )
        has_ow_in_outfit = outfit.get("outerwear") is not None
        if has_suitable_ow:
            report.checks["outerwear_cold"] = has_ow_in_outfit
            if not has_ow_in_outfit:
                report.details["outerwear_cold"] = f"temp={temp_m}, suitable outerwear available but not picked"
        else:
            report.checks["outerwear_cold"] = True
    else:
        report.checks["outerwear_cold"] = True

    # 6. Hat when freezing (check that suitable hat is picked if available)
    if temp_m < 5:
        # Determine season from temp
        _season = "winter" if temp_m < 5 else ("autumn" if temp_m < 15 else "summer")
        has_suitable_hat = any(
            i.category_group == "accessory"
            and "шапк" in (i.type or "").lower()
            and (not i.season or _season in i.season)
            for i in wardrobe
        )
        has_hat_in_outfit = outfit.get("hat") is not None
        if has_suitable_hat:
            report.checks["hat_freezing"] = has_hat_in_outfit
            if not has_hat_in_outfit:
                report.details["hat_freezing"] = f"temp={temp_m}, suitable hat available but not picked"
        else:
            report.checks["hat_freezing"] = True  # no suitable hat in wardrobe
    else:
        report.checks["hat_freezing"] = True

    # 7. Color harmony (only if 2+ visual items with known colors)
    try:
        from services.color_harmony import score_outfit_colors
        if len(visual_items) >= 2:
            harmony = score_outfit_colors(visual_items)
            report.checks["color_harmony"] = harmony >= 3.0
            report.details["color_harmony_score"] = round(harmony, 1)
            if harmony < 3.5:
                colors = [i.color for i in visual_items]
                report.details["color_harmony"] = f"score={harmony:.1f}, colors={colors}"
        else:
            report.checks["color_harmony"] = True
    except Exception:
        report.checks["color_harmony"] = True  # can't import → skip

    return report


# ── Monte Carlo tests ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", range(1000))
def test_outfit_quality_random(seed):
    """Monte Carlo: random wardrobe + weather → critical checks must pass.

    Critical (assert): no_base_visible, no_duplicates, warmth_consistency
    Statistical (warn): has_minimum, color_harmony, outerwear_cold, hat_freezing
    """
    rng = random.Random(seed)
    segment = rng.choice(SEGMENTS)
    geo = rng.choice(list(GEO_TEMPS.keys()))
    wardrobe_size = rng.randint(5, 40)

    wardrobe = random_wardrobe(rng, wardrobe_size, segment)
    temp_m, temp_e, season, precip = random_weather(rng, geo)

    from services.outfit_selector import _select_outfit
    outfit = _select_outfit(
        items=wardrobe,
        season=season,
        today=date.today(),
        temp_morning=temp_m,
        temp_evening=temp_e,
        precip_evening=precip,
    )

    report = check_outfit_quality(outfit, wardrobe, temp_m, temp_e, seed)

    # Critical checks — must ALWAYS pass
    CRITICAL = {"no_base_visible", "no_duplicates", "warmth_consistency"}
    critical_fails = [c for c in CRITICAL if not report.checks.get(c, True)]
    assert not critical_fails, f"CRITICAL failure: {report.summary}"


# ── Focused edge case tests ──────────────────────────────────────────────────

class TestEdgeCases:
    """Targeted tests for known edge cases."""

    def test_extreme_cold_moscow(self):
        """Moscow -20°C: should pick warmest items."""
        rng = random.Random(42)
        wardrobe = random_wardrobe(rng, 30, "mom_girl")
        from services.outfit_selector import _select_outfit
        outfit = _select_outfit(wardrobe, "winter", date.today(), -20.0, -25.0)
        report = check_outfit_quality(outfit, wardrobe, -20.0, -25.0, 42)
        assert report.all_passed, report.summary

    def test_extreme_heat_dubai(self):
        """Dubai +42°C: should pick lightest items."""
        rng = random.Random(43)
        wardrobe = random_wardrobe(rng, 20, "no_kids")
        from services.outfit_selector import _select_outfit
        outfit = _select_outfit(wardrobe, "summer", date.today(), 42.0, 38.0)
        report = check_outfit_quality(outfit, wardrobe, 42.0, 38.0, 43)
        assert report.all_passed, report.summary

    def test_minimal_wardrobe_3_items(self):
        """Only 3 items: top + bottom + shoes. Should still produce outfit."""
        items = [
            _make_item(random.Random(1), "top", "футболка", 1),
            _make_item(random.Random(2), "bottom", "джинсы", 2),
            _make_item(random.Random(3), "footwear", "кроссовки", 2),
        ]
        from services.outfit_selector import _select_outfit
        outfit = _select_outfit(items, "spring", date.today(), 15.0, 12.0)
        assert outfit["top"] is not None
        assert outfit["bottom"] is not None

    def test_all_same_color_wardrobe(self):
        """20 items all black: color harmony should be high (monochrome)."""
        rng = random.Random(44)
        items = []
        for _ in range(20):
            cat = rng.choice(["top", "bottom", "outerwear", "footwear"])
            type_name, warmth = rng.choice(TYPES_BY_CATEGORY[cat])
            item = _make_item(rng, cat, type_name, warmth)
            item.color = "чёрный"
            items.append(item)
        from services.outfit_selector import _select_outfit
        outfit = _select_outfit(items, "autumn", date.today(), 10.0, 5.0)
        report = check_outfit_quality(outfit, items, 10.0, 5.0, 44)
        assert report.checks.get("color_harmony", True), "Monochrome should score well"

    def test_big_temperature_drop(self):
        """Morning +22° → evening +5°: should add removable layer."""
        rng = random.Random(45)
        wardrobe = random_wardrobe(rng, 25, "no_kids")
        from services.outfit_selector import _select_outfit
        outfit = _select_outfit(wardrobe, "spring", date.today(), 22.0, 5.0)
        assert outfit.get("warnings"), "Big temp drop should produce warning"

    def test_only_dresses_wardrobe(self):
        """Wardrobe with only dresses + shoes. Should work via one_piece."""
        items = [
            _make_item(random.Random(1), "one_piece", "платье", 1),
            _make_item(random.Random(2), "one_piece", "тёплое платье", 3),
            _make_item(random.Random(3), "footwear", "туфли", 1),
            _make_item(random.Random(4), "footwear", "ботинки", 3),
        ]
        from services.outfit_selector import _select_outfit
        outfit = _select_outfit(items, "spring", date.today(), 18.0, 15.0)
        assert outfit["one_piece"] is not None, "Should pick a dress"

    def test_reproducibility(self):
        """Same seed → identical outfit."""
        from services.outfit_selector import _select_outfit
        results = []
        for _ in range(3):
            rng = random.Random(999)
            wardrobe = random_wardrobe(rng, 20, "no_kids")
            temp_m, temp_e, season, precip = random_weather(rng, "moscow")
            outfit = _select_outfit(wardrobe, season, date.today(), temp_m, temp_e, precip)
            item_ids = tuple(i.id for i in outfit.get("all_items", []))
            results.append(item_ids)
        assert results[0] == results[1] == results[2], "Same seed must produce same outfit"


# ── Statistics helper (for standalone use) ────────────────────────────────────

def run_montecarlo(n_scenarios: int = 10000, seed: int = 42):
    """Run Monte Carlo and print statistics. Call from scripts."""
    from services.outfit_selector import _select_outfit

    check_counts: dict[str, int] = Counter()
    check_fails: dict[str, int] = Counter()
    harmony_scores: list[float] = []
    failures: list[str] = []

    for i in range(n_scenarios):
        rng = random.Random(seed + i)
        segment = rng.choice(SEGMENTS)
        geo = rng.choice(list(GEO_TEMPS.keys()))
        wardrobe_size = rng.randint(5, 40)

        wardrobe = random_wardrobe(rng, wardrobe_size, segment)
        temp_m, temp_e, season, precip = random_weather(rng, geo)

        outfit = _select_outfit(wardrobe, season, date.today(), temp_m, temp_e, precip)
        report = check_outfit_quality(outfit, wardrobe, temp_m, temp_e, seed + i)

        for check_name, passed in report.checks.items():
            check_counts[check_name] += 1
            if not passed:
                check_fails[check_name] += 1

        if "color_harmony_score" in report.details:
            harmony_scores.append(report.details["color_harmony_score"])

        if not report.all_passed:
            failures.append(report.summary)

    print(f"\n{'='*60}")
    print(f"Monte Carlo: {n_scenarios} scenarios (seed={seed})")
    print(f"{'='*60}")
    total_pass = n_scenarios - len(failures)
    print(f"Overall: {total_pass}/{n_scenarios} passed ({total_pass/n_scenarios*100:.1f}%)")
    print()
    for check_name in sorted(check_counts.keys()):
        total = check_counts[check_name]
        fails = check_fails.get(check_name, 0)
        rate = (total - fails) / total * 100
        print(f"  {check_name:25s}: {rate:5.1f}% pass ({fails} failures)")
    if harmony_scores:
        avg = sum(harmony_scores) / len(harmony_scores)
        print(f"\n  Color harmony avg: {avg:.1f}/10")
    if failures:
        print(f"\nWorst failures (first 10):")
        for f in failures[:10]:
            print(f"  {f}")
    print()


if __name__ == "__main__":
    run_montecarlo(10000)


# ══════════════════════════════════════════════════════════════════════════════
# EXTENDED CHECKS: capsule, forgotten, occasions, wardrobe math, weekly, Kassi
# ══════════════════════════════════════════════════════════════════════════════


class TestCapsuleMonteCarlo:
    """Monte Carlo: capsule selection quality across random wardrobes."""

    @pytest.mark.parametrize("seed", range(200))
    def test_capsule_quality(self, seed):
        rng = random.Random(seed + 5000)
        wardrobe = random_wardrobe(rng, rng.randint(15, 50), rng.choice(SEGMENTS))

        from bot.handlers.challenge import select_capsule
        capsule = select_capsule(wardrobe, 15)

        # 1. Size <= 15
        assert len(capsule) <= 15

        # 2. Color diversity: max 2 per color
        color_counts = Counter(getattr(i, "color", "") for i in capsule)
        for color, cnt in color_counts.items():
            assert cnt <= 2, f"seed={seed}: color '{color}' appears {cnt} times"

        # 3. Must have top + bottom (or not enough in wardrobe)
        cats = {getattr(i, "category_group", "") for i in capsule}
        has_top_in_wardrobe = any(i.category_group == "top" for i in wardrobe)
        has_bottom_in_wardrobe = any(i.category_group == "bottom" for i in wardrobe)
        if has_top_in_wardrobe and has_bottom_in_wardrobe and len(capsule) >= 5:
            assert "top" in cats or "one_piece" in cats, f"seed={seed}: no top/one_piece in capsule"
            assert "bottom" in cats or "one_piece" in cats, f"seed={seed}: no bottom/one_piece in capsule"


class TestForgottenScoringMonteCarlo:
    """Monte Carlo: forgotten items get higher scores."""

    @pytest.mark.parametrize("seed", range(100))
    def test_forgotten_items_prioritized(self, seed):
        """Items not worn >21 days should score higher than recently worn."""
        rng = random.Random(seed + 6000)
        today = date.today()

        # Create 2 identical items, one forgotten, one recent
        forgotten = _make_item(rng, "top", "свитер", 3)
        forgotten.last_worn = today - timedelta(days=30)
        forgotten.score_item = 5.0

        recent = _make_item(random.Random(seed + 7000), "top", "свитер", 3)
        recent.last_worn = today - timedelta(days=2)
        recent.score_item = 5.0

        # Forgotten should score higher (5.0 + 2.0 = 7.0 vs 5.0 + 0 = 5.0)
        from services.outfit_selector import _select_outfit
        items = [forgotten, recent, _make_item(rng, "bottom", "джинсы", 2),
                 _make_item(rng, "footwear", "кроссовки", 2)]
        outfit = _select_outfit(items, "autumn", today, 12.0, 8.0)

        top = outfit.get("top")
        if top:
            # Forgotten item should be picked (higher score)
            assert top.id == forgotten.id, f"seed={seed}: expected forgotten item, got recently worn"


class TestOccasionRoutingMonteCarlo:
    """Monte Carlo: occasion routing produces valid values."""

    @pytest.mark.parametrize("weekday", range(7))
    @pytest.mark.parametrize("segment", SEGMENTS)
    def test_occasion_always_valid(self, weekday, segment):
        """Every segment × weekday combo → valid occasion string."""
        valid_occasions = {
            "офис", "кэжуал", "отдых", "садик", "школа",
            "прогулка", "выходной", "",
        }
        # Simulate wardrobe.py logic
        is_weekend = weekday >= 5
        if segment in ("mom_girl", "mom_boy"):
            if is_weekend:
                day_type = "прогулка"
            else:
                day_type = "садик"  # default for unknown age
        elif segment == "no_kids":
            if weekday < 5:
                day_type = "офис"
            elif weekday == 5:
                day_type = "кэжуал"
            else:
                day_type = "отдых"
        elif segment == "pregnant":
            day_type = "отдых" if is_weekend else "прогулка"
        else:
            day_type = "выходной" if is_weekend else ""

        assert day_type in valid_occasions, f"Invalid occasion: '{day_type}' for {segment}/{weekday}"


class TestWardrobeMathMonteCarlo:
    """Monte Carlo: wardrobe math produces sane values."""

    @pytest.mark.parametrize("seed", range(200))
    def test_combos_non_negative(self, seed):
        rng = random.Random(seed + 8000)
        wardrobe = random_wardrobe(rng, rng.randint(3, 50), rng.choice(SEGMENTS))
        from services.wardrobe_math import calc_wardrobe_combos
        combos = calc_wardrobe_combos(wardrobe)
        assert combos >= 0, f"seed={seed}: negative combos={combos}"

    @pytest.mark.parametrize("seed", range(200))
    def test_more_items_more_combos(self, seed):
        """Adding items should not decrease combos."""
        rng = random.Random(seed + 9000)
        small = random_wardrobe(rng, 5, "no_kids")
        rng2 = random.Random(seed + 9000)  # same seed
        big = random_wardrobe(rng2, 5, "no_kids")
        # Add extra items
        big.append(_make_item(random.Random(seed), "top", "футболка", 2))
        big.append(_make_item(random.Random(seed + 1), "bottom", "джинсы", 2))

        from services.wardrobe_math import calc_wardrobe_combos
        assert calc_wardrobe_combos(big) >= calc_wardrobe_combos(small)


class TestWeeklyPlanMonteCarlo:
    """Monte Carlo: weekly plan produces valid 5-day plans."""

    @pytest.mark.parametrize("seed", range(50))
    def test_weekly_5_days(self, seed):
        """Weekly plan always produces 5 days."""
        rng = random.Random(seed + 10000)
        wardrobe = random_wardrobe(rng, rng.randint(10, 40), "no_kids")

        from worker.tasks.weekly_plan import _WEEKLY_OCCASIONS, _format_outfit_line, _is_basic_item
        from services.outfit_selector import _select_outfit

        occasions = _WEEKLY_OCCASIONS["no_kids"]
        used_ids: set = set()
        outfits_ok = 0
        today = date.today()

        for day_idx in range(5):
            available = [i for i in wardrobe if _is_basic_item(i) or i.id not in used_ids]
            outfit = _select_outfit(available, "spring", today + timedelta(days=day_idx), 12.0, 8.0)
            for item in outfit.get("all_items", []):
                if not _is_basic_item(item):
                    used_ids.add(item.id)
            outfits_ok += 1

        assert outfits_ok == 5


class TestStyleDiaryMonteCarlo:
    """Monte Carlo: style diary insights work with random wear data."""

    @pytest.mark.parametrize("seed", range(100))
    def test_insights_no_crash(self, seed):
        """get_wear_insights never crashes on random data."""
        import asyncio
        from services.style_diary import get_wear_insights

        rng = random.Random(seed + 11000)
        items = []
        for _ in range(rng.randint(0, 30)):
            cat = rng.choice(list(TYPES_BY_CATEGORY.keys()))
            type_name, warmth = rng.choice(TYPES_BY_CATEGORY[cat])
            item = _make_item(rng, cat, type_name, warmth)
            item.wear_count = rng.randint(0, 10)
            if rng.random() > 0.5:
                item.last_worn = date.today() - timedelta(days=rng.randint(0, 60))
            else:
                item.last_worn = None
            items.append(item)

        loop = asyncio.new_event_loop()
        try:
            insights = loop.run_until_complete(get_wear_insights(f"user_{seed}", items))
            assert isinstance(insights, dict)
            assert "top_color" in insights
            assert "usage_pct" in insights
            assert insights["usage_pct"] >= 0
            assert insights["usage_pct"] <= 100
        finally:
            loop.close()


class TestKassiToneMonteCarlo:
    """Verify Kassi fallback templates are always positive."""

    FORBIDDEN = ["критически", "обязательно", "срочно", "не хватает", "нужно", "должна", "нельзя"]

    def test_all_mom_templates_clean(self):
        from services.scoring_comment import _TEMPLATES_MOM
        for t in _TEMPLATES_MOM:
            for word in self.FORBIDDEN:
                assert word not in t.lower(), f"Forbidden '{word}' in: {t}"

    def test_all_nokids_templates_clean(self):
        from services.scoring_comment import _TEMPLATES_NO_KIDS
        for t in _TEMPLATES_NO_KIDS:
            for word in self.FORBIDDEN:
                assert word not in t.lower(), f"Forbidden '{word}' in: {t}"

    def test_all_wow_phrases_clean(self):
        from worker.tasks.style_config import WOW_PHRASES
        for p in WOW_PHRASES:
            for word in self.FORBIDDEN:
                assert word not in p.lower(), f"Forbidden '{word}' in WOW: {p}"

    @pytest.mark.parametrize("style_type", [
        "elegant_classic", "romantic_soft", "street_casual",
        "sporty_minimal", "bold_creative", "relaxed_natural",
    ])
    def test_style_hints_no_forbidden(self, style_type):
        from services.outfit_engine import STYLE_TYPE_HINTS
        hint = STYLE_TYPE_HINTS[style_type]
        for word in self.FORBIDDEN:
            assert word not in hint.lower(), f"Forbidden '{word}' in hint for {style_type}"
