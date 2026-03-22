"""
Tests for services/normalize.py — type and color normalization.

Validates that unusual/rare clothing types and colors are mapped
to canonical forms that the outfit selector understands.
"""
import pytest

pytest.importorskip("structlog", reason="structlog not installed")

from services.normalize import normalize_type, normalize_color


# ══════════════════════════════════════════════════════════════════════════════
# TYPE NORMALIZATION
# ══════════════════════════════════════════════════════════════════════════════


class TestTypeNormalization:
    """Unusual clothing types → canonical forms."""

    # ── Headwear ──

    @pytest.mark.parametrize("raw,expected_type,expected_cg", [
        ("капор", "шапка", "accessory"),
        ("балаклава", "шапка", "accessory"),
        ("тюбетейка", "шапка", "accessory"),
        ("берет", "шапка", "accessory"),
        ("бини", "шапка", "accessory"),
        ("бейсболка", "шапка", "accessory"),
        ("кепка", "шапка", "accessory"),
        ("панама", "шапка", "accessory"),
        ("бандана", "шапка", "accessory"),
        ("косынка", "шапка", "accessory"),
        ("чепчик", "шапка", "accessory"),
        ("ушанка", "шапка", "accessory"),
        ("шляпа", "шапка", "accessory"),
        ("федора", "шапка", "accessory"),
        ("пилотка", "шапка", "accessory"),
        ("фуражка", "шапка", "accessory"),
        ("канотье", "шапка", "accessory"),
        ("тиара", "украшения", "accessory"),
        ("диадема", "украшения", "accessory"),
    ])
    def test_headwear_variants(self, raw, expected_type, expected_cg):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type, f"'{raw}' → '{norm_type}', expected '{expected_type}'"
        assert norm_cg == expected_cg

    # ── Footwear ──

    @pytest.mark.parametrize("raw,expected_type", [
        ("валенки", "зимние сапоги"),
        ("дутики", "зимние сапоги"),
        ("унты", "зимние сапоги"),
        ("кеды", "кроссовки"),
        ("слипоны", "кроссовки"),
        ("хайтопы", "кроссовки"),
        ("балетки", "туфли"),
        ("мокасины", "туфли"),
        ("лоферы", "туфли"),
        ("оксфорды", "туфли"),
        ("броги", "туфли"),
        ("лодочки", "туфли"),
        ("мери джейн", "туфли"),
        ("шлёпки", "сандалии"),
        ("вьетнамки", "сандалии"),
        ("кроксы", "сандалии"),
        ("мюли", "сандалии"),
        ("эспадрильи", "сандалии"),
        ("босоножки", "сандалии"),
        ("ботильоны", "ботинки"),
        ("челси", "ботинки"),
        ("тимберленды", "ботинки"),
        ("берцы", "ботинки"),
        ("мартинсы", "ботинки"),
        ("ботфорты", "сапоги"),
        ("пинетки", "тапочки"),
    ])
    def test_footwear_variants(self, raw, expected_type):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type, f"'{raw}' → '{norm_type}', expected '{expected_type}'"
        assert norm_cg == "footwear"

    # ── Tops ──

    @pytest.mark.parametrize("raw,expected_type", [
        ("олимпийка", "худи"),
        ("толстовка", "худи"),
        ("свитшот", "худи"),
        ("поло", "рубашка"),
        ("джемпер", "свитер"),
        ("пуловер", "свитер"),
        ("кофта", "свитер"),
        ("гольф", "водолазка"),
        ("бадлон", "водолазка"),
        ("баска", "блузка"),
        ("туника", "блузка"),
        ("болеро", "кардиган"),
        ("бралетт", "топ"),
        ("бюстье", "топ"),
        ("кроп-топ", "топ"),
        ("реглан", "лонгслив"),
    ])
    def test_top_variants(self, raw, expected_type):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type, f"'{raw}' → '{norm_type}', expected '{expected_type}'"
        assert norm_cg == "top"

    # ── Bottoms ──

    @pytest.mark.parametrize("raw,expected_type", [
        ("бриджи", "шорты"),
        ("бермуды", "шорты"),
        ("кюлоты", "брюки"),
        ("лосины", "леггинсы"),
        ("треники", "брюки"),
        ("joggers", "брюки"),
        ("джоггеры", "брюки"),
        ("карго", "брюки"),
        ("чиносы", "брюки"),
        ("палаццо", "брюки"),
        ("скинни", "джинсы"),
        ("бойфренды", "джинсы"),
        ("плиссе", "юбка"),
        ("юбка-карандаш", "юбка"),
    ])
    def test_bottom_variants(self, raw, expected_type):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type
        assert norm_cg == "bottom"

    # ── Outerwear ──

    @pytest.mark.parametrize("raw,expected_type", [
        ("парка", "куртка"),
        ("анорак", "куртка"),
        ("бомбер", "куртка"),
        ("косуха", "кожаная куртка"),
        ("кожанка", "кожаная куртка"),
        ("шуба", "пальто"),
        ("дублёнка", "пальто"),
        ("пелерина", "пальто"),
        ("манто", "пальто"),
        ("тренчкот", "тренч"),
        ("пиджак", "пиджак"),
        ("жакет", "пиджак"),
        ("блейзер", "пиджак"),
    ])
    def test_outerwear_variants(self, raw, expected_type):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type
        assert norm_cg == "outerwear"

    # ── One piece ──

    @pytest.mark.parametrize("raw,expected_type", [
        ("сарафан", "платье"),
        ("ромпер", "комбинезон"),
        ("слип", "комбинезон"),
        ("песочник", "комбинезон"),
    ])
    def test_one_piece_variants(self, raw, expected_type):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type
        assert norm_cg == "one_piece"

    # ── Accessories ──

    @pytest.mark.parametrize("raw,expected_type", [
        ("снуд", "шарф"),
        ("манишка", "шарф"),
        ("палантин", "шарф"),
        ("муфта", "перчатки"),
        ("рюкзак", "сумка"),
        ("клатч", "сумка"),
    ])
    def test_accessory_variants(self, raw, expected_type):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type
        assert norm_cg == "accessory"

    # ── Baby / Toddler ──

    @pytest.mark.parametrize("raw,expected_type,expected_cg", [
        ("ползунки", "комбинезон", "one_piece"),
        ("человечек", "комбинезон", "one_piece"),
        ("распашонка", "футболка", "top"),
        ("конверт", "комбинезон", "outerwear"),
        ("царапки", "перчатки", "accessory"),
        ("слюнявчик", "нагрудник", "accessory"),
    ])
    def test_baby_items(self, raw, expected_type, expected_cg):
        norm_type, norm_cg = normalize_type(raw)
        assert norm_type == expected_type, f"'{raw}' → '{norm_type}', expected '{expected_type}'"
        assert norm_cg == expected_cg

    # ── Known items pass through unchanged ──

    @pytest.mark.parametrize("raw", [
        "футболка", "свитер", "джинсы", "платье", "куртка",
        "кроссовки", "ботинки", "шапка", "шарф",
    ])
    def test_known_types_unchanged(self, raw):
        norm_type, _ = normalize_type(raw)
        assert norm_type == raw, f"Known type '{raw}' was changed to '{norm_type}'"

    # ── Edge cases ──

    def test_empty_type(self):
        norm_type, norm_cg = normalize_type("", "top")
        assert norm_type == ""
        assert norm_cg == "top"

    def test_none_type(self):
        norm_type, norm_cg = normalize_type(None, "top")
        assert norm_type is None

    def test_substring_match(self):
        """'зимняя парка с мехом' should match 'парка'."""
        norm_type, norm_cg = normalize_type("зимняя парка с мехом")
        assert norm_type == "куртка"
        assert norm_cg == "outerwear"

    def test_case_insensitive(self):
        norm_type, _ = normalize_type("БАЛАКЛАВА")
        assert norm_type == "шапка"

    def test_corrects_category_group(self):
        """Vision might misclassify 'берет' as 'top' — normalize fixes it."""
        norm_type, norm_cg = normalize_type("берет", "top")
        assert norm_cg == "accessory", "берет should be accessory, not top"


# ══════════════════════════════════════════════════════════════════════════════
# COLOR NORMALIZATION
# ══════════════════════════════════════════════════════════════════════════════


class TestColorNormalization:
    """Unusual colors → canonical forms."""

    @pytest.mark.parametrize("raw,expected", [
        # Complex Russian colors
        ("цвет морской волны", "бирюзовый"),
        ("морская волна", "бирюзовый"),
        ("маренго", "тёмно-серый"),
        ("мокрый асфальт", "тёмно-серый"),
        ("экрю", "кремовый"),
        ("шампань", "кремовый"),
        ("айвори", "слоновая кость"),

        # Wine/berry family
        ("марсала", "бордовый"),
        ("бургунди", "бордовый"),
        ("винный", "бордовый"),

        # Earth tones
        ("какао", "коричневый"),
        ("мокко", "коричневый"),
        ("охра", "горчичный"),
        ("янтарный", "золотистый"),

        # Nature colors
        ("фисташковый", "светло-зелёный"),
        ("салатовый", "светло-зелёный"),
        ("болотный", "хаки"),

        # Flower colors
        ("сухая роза", "пыльно-розовый"),
        ("пудра", "пудровый"),
        ("васильковый", "голубой"),

        # NEW: previously missing
        ("сиреневый", "лавандовый"),
        ("лиловый", "фиолетовый"),
        ("фуксия", "розовый"),
        ("малиновый", "розовый"),
        ("баклажан", "фиолетовый"),
        ("шоколадный", "коричневый"),
        ("графитовый", "графит"),
        ("жемчужный", "белый"),
        ("рубиновый", "красный"),
        ("травяной", "зелёный"),
        ("мшистый", "хаки"),
        ("замшевый", "бежевый"),
        ("грязно-розовый", "пыльно-розовый"),

        # English → Russian
        ("white", "белый"),
        ("black", "чёрный"),
        ("navy", "тёмно-синий"),
        ("burgundy", "бордовый"),
        ("teal", "бирюзовый"),
        ("coral", "коралловый"),
        ("dusty pink", "пыльно-розовый"),
    ])
    def test_color_synonyms(self, raw, expected):
        result = normalize_color(raw)
        assert result == expected, f"'{raw}' → '{result}', expected '{expected}'"

    # ── Known colors unchanged ──

    @pytest.mark.parametrize("raw", [
        "белый", "чёрный", "серый", "красный", "синий",
        "розовый", "бежевый", "зелёный", "голубой",
    ])
    def test_known_colors_unchanged(self, raw):
        result = normalize_color(raw)
        assert result == raw

    # ── Edge cases ──

    def test_empty_color(self):
        assert normalize_color("") == ""

    def test_none_color(self):
        assert normalize_color(None) is None

    def test_unknown_color_returned_as_is(self):
        """Truly unknown color → return lowercase original."""
        result = normalize_color("переливающийся хамелеон")
        assert result == "переливающийся хамелеон"

    def test_case_insensitive(self):
        assert normalize_color("МАРЕНГО") == "тёмно-серый"

    def test_substring_match(self):
        """'нежный цвет морской волны' should match."""
        result = normalize_color("нежный цвет морской волны")
        assert result == "бирюзовый"


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION: Normalized items work in outfit selector
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizedItemsInSelector:
    """After normalization, items should be findable by outfit selector."""

    def test_normalized_headwear_found_as_hat(self):
        """After normalizing 'капор' → 'шапка', selector finds it as hat."""
        import uuid
        from unittest.mock import MagicMock
        from datetime import date
        from services.outfit_selector import _select_outfit

        kapor = MagicMock()
        kapor.id = uuid.uuid4()
        raw_type = "капор"
        norm_type, norm_cg = normalize_type(raw_type)
        kapor.type = norm_type  # "шапка"
        kapor.category_group = norm_cg  # "accessory"
        kapor.color = "серая"
        kapor.season = ["autumn", "winter"]
        kapor.last_worn = None
        kapor.score_item = 7.0
        kapor.warmth_level = 4
        kapor.style_tag = "casual"

        items = [
            _make_item("top", "свитер", warmth=4),
            _make_item("bottom", "джинсы", warmth=3),
            _make_item("footwear", "ботинки", warmth=4),
            _make_item("outerwear", "куртка", warmth=4),
            _make_item("underwear", "трусики", warmth=1),
            kapor,
        ]
        outfit = _select_outfit(items, "winter", date.today(), 5.0, 2.0, 0)
        assert outfit.get("hat") is not None, (
            "Normalized 'капор' → 'шапка' should be found as hat at 5°C"
        )
        assert outfit["hat"].id == kapor.id

    def test_normalized_footwear_found(self):
        """After normalizing 'кеды' → 'кроссовки', selector finds them."""
        import uuid
        from unittest.mock import MagicMock
        from datetime import date
        from services.outfit_selector import _select_outfit

        kedy = MagicMock()
        kedy.id = uuid.uuid4()
        norm_type, norm_cg = normalize_type("кеды")
        kedy.type = norm_type  # "кроссовки"
        kedy.category_group = norm_cg  # "footwear"
        kedy.color = "белые"
        kedy.season = ["spring", "summer", "autumn"]
        kedy.last_worn = None
        kedy.score_item = 7.0
        kedy.warmth_level = 2
        kedy.style_tag = "casual"

        items = [
            _make_item("top", "футболка", warmth=1),
            _make_item("bottom", "джинсы", warmth=3),
            _make_item("underwear", "трусики", warmth=1),
            kedy,
        ]
        outfit = _select_outfit(items, "spring", date.today(), 18.0, 15.0, 0)
        assert outfit.get("footwear") is not None
        assert outfit["footwear"].id == kedy.id

    def test_normalized_color_in_harmony(self):
        """After normalizing 'маренго' → 'тёмно-серый', it gets HSL."""
        from services.color_harmony import _find_color_hsl
        raw = "маренго"
        canonical = normalize_color(raw)
        hsl = _find_color_hsl(canonical)
        assert hsl is not None, f"Normalized '{raw}' → '{canonical}' should have HSL"


def _make_item(cg, type_, warmth=3):
    """Helper for integration tests."""
    import uuid
    from unittest.mock import MagicMock
    i = MagicMock()
    i.id = uuid.uuid4()
    i.category_group = cg
    i.type = type_
    i.color = "белый"
    i.season = ["spring", "summer", "autumn", "winter"]
    i.last_worn = None
    i.score_item = 7.0
    i.warmth_level = warmth
    i.style_tag = "casual"
    return i
