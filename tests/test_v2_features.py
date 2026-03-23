"""Tests for v2.0: Capsule Builder, Travel Capsule, Boost, Monthly Report, i18n, CI/CD."""
import pytest
from unittest.mock import MagicMock
from datetime import date


def _item(cat="top", type_name="футболка", color="белый", score=5.0, warmth=2, wear_count=0):
    m = MagicMock()
    m.id = str(id(m))
    m.category_group = cat
    m.type = type_name
    m.color = color
    m.score_item = score
    m.warmth_level = warmth
    m.wear_count = wear_count
    m.last_worn = None
    m.season = ["spring", "summer", "autumn", "winter"]
    return m


# ── Capsule Builder ──────────────────────────────────────────────────────────

class TestCapsuleBuilder:

    def test_seasonal_capsule_size(self):
        from services.wardrobe_math import build_seasonal_capsule
        items = (
            [_item("top", f"t{i}", c) for i, c in enumerate(["белый", "синий", "чёрный", "серый", "красный", "бежевый", "голубой"])]
            + [_item("bottom", f"b{i}", c) for i, c in enumerate(["синий", "чёрный", "серый", "бежевый", "коричневый"])]
            + [_item("outerwear", f"o{i}", c) for i, c in enumerate(["чёрный", "серый", "бежевый", "синий"])]
            + [_item("footwear", f"f{i}", c) for i, c in enumerate(["белый", "чёрный", "коричневый", "бежевый"])]
            + [_item("one_piece", f"p{i}", c) for i, c in enumerate(["красный", "синий", "чёрный"])]
            + [_item("accessory", f"a{i}", c) for i, c in enumerate(["чёрный", "серый", "белый", "красный", "синий"])]
        )
        result = build_seasonal_capsule(items, "spring", 25)
        assert len(result["items"]) <= 25
        assert result["total_combos"] > 0
        assert result["season"] == "spring"
        assert len(result["palette_colors"]) > 0

    def test_capsule_color_diversity(self):
        from services.wardrobe_math import build_seasonal_capsule
        items = [_item("top", f"t{i}", "красный") for i in range(10)]
        items += [_item("bottom", f"b{i}", "красный") for i in range(5)]
        result = build_seasonal_capsule(items, "spring", 15)
        from collections import Counter
        counts = Counter(getattr(i, "color", "") for i in result["items"])
        for color, cnt in counts.items():
            assert cnt <= 3, f"Color '{color}' appears {cnt} times"

    def test_capsule_empty_wardrobe(self):
        from services.wardrobe_math import build_seasonal_capsule
        result = build_seasonal_capsule([], "spring", 25)
        assert result["items"] == []
        assert result["total_combos"] == 0

    def test_capsule_card_template_exists(self):
        from pathlib import Path
        assert Path("renderer/templates/tpl_capsule_card.html").exists()


# ── Travel Capsule ───────────────────────────────────────────────────────────

class TestTravelCapsule:

    def test_travel_compact(self):
        from services.wardrobe_math import build_travel_capsule
        items = (
            [_item("top", f"t{i}", "белый") for i in range(5)]
            + [_item("bottom", f"b{i}", "синий") for i in range(3)]
            + [_item("footwear", f"f{i}", "чёрный") for i in range(2)]
            + [_item("outerwear", "ветровка", "серый")]
        )
        result = build_travel_capsule(items, days=5, occasions=["работа", "культура"])
        assert len(result["items"]) <= 10  # days + 5
        assert result["total_combos"] > 0

    def test_travel_warm_destination(self):
        from services.wardrobe_math import build_travel_capsule
        items = [
            _item("outerwear", "пуховик", "чёрный", warmth=5),
            _item("top", "футболка", "белый", warmth=1),
            _item("bottom", "шорты", "синий", warmth=1),
            _item("footwear", "сандалии", "бежевый", warmth=1),
        ]
        result = build_travel_capsule(items, days=3, occasions=["пляж"], temp_range=(25, 35))
        # Пуховик не должен попасть (warmth=5 > 3)
        types = [getattr(i, "type", "") for i in result["items"]]
        assert "пуховик" not in types

    def test_format_packing(self):
        from services.wardrobe_math import format_travel_packing
        capsule = {
            "items": [_item("top", "блузка", "белый"), _item("bottom", "джинсы", "синий")],
            "total_combos": 5,
            "days": 3,
            "occasions": ["работа"],
        }
        text = format_travel_packing(capsule)
        assert "Чемодан" in text
        assert "5 образов" in text


# ── Outfit Boost ─────────────────────────────────────────────────────────────

class TestOutfitBoost:

    def test_boost_module_exists(self):
        from bot.handlers.boost import handle_boost_start, process_boost_photo
        assert callable(handle_boost_start)
        assert callable(process_boost_photo)

    def test_boost_registered_in_app(self):
        with open("bot/app.py") as f:
            source = f.read()
        assert "boost" in source.lower()
        assert "Как я" in source

    def test_boost_in_photo_handler(self):
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert '"boost"' in source
        assert "process_boost_photo" in source

    def test_boost_prompt_no_score(self):
        """Boost prompt must explicitly forbid numeric scores."""
        with open("bot/handlers/boost.py") as f:
            source = f.read()
        assert "НЕ давай цифровой score" in source
        assert "НИКОГДА" in source

    def test_boost_positive_only(self):
        """Boost prompt must start with enthusiasm."""
        with open("bot/handlers/boost.py") as f:
            source = f.read()
        assert "восторга" in source or "Огонь" in source
        assert "уверенност" in source


# ── Monthly Report ───────────────────────────────────────────────────────────

class TestMonthlyReport:

    @pytest.mark.asyncio
    async def test_report_data(self):
        from services.wardrobe_math import build_monthly_report
        items = [
            _item("top", "свитер", "синий", wear_count=5),
            _item("bottom", "джинсы", "чёрный", wear_count=3),
            _item("footwear", "кроссовки", "белый", wear_count=0),
        ]
        report = await build_monthly_report("user1", items)
        assert report["wardrobe_size"] == 3
        assert report["unique_items_used"] == 2
        assert report["usage_pct"] > 0
        assert report["forgotten_count"] == 1
        assert report["total_combos"] >= 0

    def test_report_template_exists(self):
        from pathlib import Path
        assert Path("renderer/templates/tpl_monthly_report.html").exists()

    def test_report_template_has_stats(self):
        with open("renderer/templates/tpl_monthly_report.html") as f:
            html = f.read()
        assert "usage_pct" in html
        assert "estimated_savings" in html
        assert "fashioncastle.app" in html


# ── i18n ─────────────────────────────────────────────────────────────────────

class TestI18n:

    def test_ru_strings_exist(self):
        from services.i18n.ru import STRINGS
        assert "error.generic" in STRINGS
        assert len(STRINGS) >= 10

    def test_en_strings_exist(self):
        from services.i18n.en import STRINGS
        assert "error.generic" in STRINGS
        assert "Kassi" in STRINGS.get("onboarding.welcome", "")

    def test_t_function_ru(self):
        from services.i18n import t
        result = t("error.generic", "ru")
        assert "Что-то" in result

    def test_t_function_en(self):
        from services.i18n import t
        result = t("error.generic", "en")
        assert "Something" in result

    def test_t_fallback_to_ru(self):
        from services.i18n import t
        result = t("error.generic", "fr")  # unknown lang
        assert "Что-то" in result  # falls back to Russian

    def test_t_unknown_key(self):
        from services.i18n import t
        result = t("nonexistent.key", "ru")
        assert result == "nonexistent.key"

    def test_t_format(self):
        from services.i18n import t
        result = t("brief.good_morning", "en", name="Alice")
        assert "Alice" in result

    def test_get_user_lang(self):
        from services.i18n import get_user_lang
        user = MagicMock()
        user.language = "en"
        assert get_user_lang(user) == "en"
        user.language = None
        assert get_user_lang(user) == "ru"


# ── CI/CD ────────────────────────────────────────────────────────────────────

class TestCICD:

    def test_deploy_workflow_exists(self):
        from pathlib import Path
        assert Path(".github/workflows/deploy.yml").exists()

    def test_test_workflow_exists(self):
        from pathlib import Path
        assert Path(".github/workflows/test.yml").exists()

    def test_deploy_uses_ssh(self):
        with open(".github/workflows/deploy.yml") as f:
            source = f.read()
        assert "ssh" in source.lower()
        assert "docker compose" in source

    def test_deploy_on_test_success(self):
        with open(".github/workflows/deploy.yml") as f:
            source = f.read()
        assert "workflow_run" in source
        assert "completed" in source
