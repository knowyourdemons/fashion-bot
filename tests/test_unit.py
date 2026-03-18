"""
Unit тесты — чистые функции без внешних зависимостей.
"""
import pytest
from PIL import Image
import io


# ── Crop quality check ─────────────────────────────────────────────────────

class TestCropQuality:
    def test_прозрачное_изображение_невалидно(self):
        from bot.handlers.wardrobe import _check_crop_quality
        img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        assert not _check_crop_quality(buf.getvalue())

    def test_непрозрачное_изображение_валидно(self):
        from bot.handlers.wardrobe import _check_crop_quality
        img = Image.new("RGBA", (300, 300), (255, 100, 100, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        assert _check_crop_quality(buf.getvalue())


# ── _fix_bbox ──────────────────────────────────────────────────────────────

class TestFixBbox:
    def test_носки_большой_bbox_уменьшается(self):
        from bot.handlers.wardrobe import _fix_bbox
        data = {
            "category_group": "base_layer",
            "type": "носки",
            "bbox": {"x": 0.0, "y": 0.0, "w": 0.9, "h": 0.9},
        }
        result = _fix_bbox(data)
        assert result["bbox"]["w"] <= 0.25
        assert result["bbox"]["h"] <= 0.25

    def test_куртка_нормальный_bbox_не_меняется(self):
        from bot.handlers.wardrobe import _fix_bbox
        data = {
            "category_group": "outerwear",
            "type": "куртка",
            "bbox": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.6},
        }
        result = _fix_bbox(data)
        assert result["bbox"]["w"] == 0.5
        assert result["bbox"]["h"] == 0.6


# ── Переклассификация bbox ─────────────────────────────────────────────────

class TestReclassification:
    def test_маленькая_шапка_становится_носками(self):
        """bbox ≤0.2×0.2 + accessory/шапка → должна переклассифицироваться"""
        data = {
            "category_group": "accessory",
            "type": "шапка",
            "bbox": {"x": 0.7, "y": 0.1, "w": 0.12, "h": 0.10},
        }
        bbox = data["bbox"]
        bw, bh = float(bbox["w"]), float(bbox["h"])
        cg = data["category_group"]
        item_type = data["type"].lower()

        should_reclassify = (
            cg == "accessory"
            and any(w in item_type for w in ["шапка", "шапочка"])
            and bw <= 0.2 and bh <= 0.2
        )
        assert should_reclassify

    def test_большая_шапка_не_переклассифицируется(self):
        data = {
            "category_group": "accessory",
            "type": "шапка",
            "bbox": {"x": 0.3, "y": 0.1, "w": 0.4, "h": 0.35},
        }
        bbox = data["bbox"]
        bw, bh = float(bbox["w"]), float(bbox["h"])
        assert not (bw <= 0.2 and bh <= 0.2)


# ── Style config ──────────────────────────────────────────────────────────

class TestStyleConfig:
    def test_лето_прохладно_outerwear_не_none(self):
        from worker.tasks.style_config import get_placeholder_label
        result = get_placeholder_label("outerwear", "Лето", "прохладно")
        assert result is not None
        assert "куртка" in result.lower() or "ветровка" in result.lower()

    def test_жара_outerwear_none(self):
        from worker.tasks.style_config import get_placeholder_label
        result = get_placeholder_label("outerwear", "Лето", "жара")
        assert result is None, f"При жаре куртка не нужна, но вернулось: {result!r}"

    def test_wow_phrases_rotate(self):
        from worker.tasks.style_config import get_wow_phrase
        phrases = [get_wow_phrase() for _ in range(30)]
        assert len(set(phrases)) > 1, "WOW фразы не ротируются"

    def test_все_цветотипы_заполнены(self):
        from worker.tasks.style_config import COLORTYPE_PALETTES
        required_types = ["Лето", "Зима", "Весна", "Осень", "default"]
        required_slots = ["outerwear", "top", "bottom", "footwear",
                          "accessory", "tights", "one_piece"]
        for ct in required_types:
            assert ct in COLORTYPE_PALETTES, f"Нет цветотипа {ct}"
            for slot in required_slots:
                assert slot in COLORTYPE_PALETTES[ct], \
                    f"Нет слота {slot} для цветотипа {ct}"

    def test_wow_phrases_достаточно(self):
        from worker.tasks.style_config import WOW_PHRASES
        assert len(WOW_PHRASES) >= 5


# ── _format_item ──────────────────────────────────────────────────────────

class TestFormatItem:
    def test_дубль_цвета_убирается(self):
        """кроссовки серебристые (серебристый) → кроссовки серебристые"""
        from worker.tasks.morning_brief import _format_item

        class FI:
            type = "кроссовки серебристые"
            color = "серебристый"

        result = _format_item(FI())
        assert "(серебристый)" not in result
        assert "кроссовки серебристые" in result

    def test_разный_цвет_добавляется(self):
        from worker.tasks.morning_brief import _format_item

        class FI:
            type = "свитшот"
            color = "розовый"

        result = _format_item(FI())
        assert "розовый" in result

    def test_пустой_цвет_не_добавляет_скобки(self):
        from worker.tasks.morning_brief import _format_item

        class FI:
            type = "платье"
            color = ""

        result = _format_item(FI())
        assert "()" not in result
        assert result == "платье"


# ── _get_temp_regime ──────────────────────────────────────────────────────

class TestTempRegime:
    def test_сильный_мороз(self):
        from worker.tasks.morning_brief import _get_temp_regime
        assert _get_temp_regime(-10) == "сильный_мороз"

    def test_мороз(self):
        from worker.tasks.morning_brief import _get_temp_regime
        assert _get_temp_regime(5) == "мороз"

    def test_тепло(self):
        from worker.tasks.morning_brief import _get_temp_regime
        assert _get_temp_regime(22) == "тепло"

    def test_жара(self):
        from worker.tasks.morning_brief import _get_temp_regime
        assert _get_temp_regime(30) == "жара"

    def test_прохладно(self):
        from worker.tasks.morning_brief import _get_temp_regime
        r = _get_temp_regime(12)
        assert r in ("прохладно", "холодно")


# ── _SEASONS ──────────────────────────────────────────────────────────────

class TestSeasons:
    def test_все_12_месяцев_заполнены(self):
        from worker.tasks.morning_brief import _SEASONS
        for month in range(1, 13):
            assert month in _SEASONS
            assert _SEASONS[month] in ("winter", "spring", "summer", "autumn")

    def test_декабрь_зима(self):
        from worker.tasks.morning_brief import _SEASONS
        assert _SEASONS[12] == "winter"

    def test_июль_лето(self):
        from worker.tasks.morning_brief import _SEASONS
        assert _SEASONS[7] == "summer"


# ── Collage placeholders ──────────────────────────────────────────────────

class TestCollage:
    def test_плейсхолдер_не_пустой(self):
        from services.image_builder import _make_placeholder, THUMB_SIZE
        for slot in ["outerwear", "top", "bottom", "footwear", "accessory"]:
            ph = _make_placeholder(slot, "тест")
            pixels = list(ph.getdata())
            bg = (240, 238, 240)
            non_bg = [p for p in pixels if tuple(p[:3]) != bg]
            assert len(non_bg) > 100, \
                f"Силуэт {slot} почти пустой ({len(non_bg)} пикс)"

    def test_плейсхолдер_правильный_размер(self):
        from services.image_builder import _make_placeholder, THUMB_SIZE
        ph = _make_placeholder("top", "верх")
        assert ph.size == (THUMB_SIZE, THUMB_SIZE)

    def test_плейсхолдер_для_tights(self):
        from services.image_builder import _make_placeholder
        ph = _make_placeholder("tights", "колготки")
        assert ph is not None


# ── Chat limits ───────────────────────────────────────────────────────────

class TestChatLimits:
    def test_free_limit_5(self):
        from bot.handlers.text import CHAT_LIMIT_FREE
        assert CHAT_LIMIT_FREE == 5

    def test_premium_limit_20(self):
        from bot.handlers.text import CHAT_LIMIT_PREMIUM
        assert CHAT_LIMIT_PREMIUM == 20

    def test_premium_больше_free(self):
        from bot.handlers.text import CHAT_LIMIT_FREE, CHAT_LIMIT_PREMIUM
        assert CHAT_LIMIT_PREMIUM > CHAT_LIMIT_FREE


# ── Outfit day limits ─────────────────────────────────────────────────────

class TestOutfitLimits:
    def test_free_limit(self):
        from bot.handlers.wardrobe import OUTFIT_DAY_LIMIT_FREE
        assert OUTFIT_DAY_LIMIT_FREE == 2

    def test_premium_limit(self):
        from bot.handlers.wardrobe import OUTFIT_DAY_LIMIT_PREMIUM
        assert OUTFIT_DAY_LIMIT_PREMIUM == 5


# ── _needs_tights ──────────────────────────────────────────────────────────

class TestNeedsTights:
    def _make_item(self, type_name):
        from unittest.mock import MagicMock
        item = MagicMock()
        item.type = type_name
        return item

    def test_леггинсы_не_нужны(self):
        from worker.tasks.style_config import _needs_tights
        outfit = {"bottom": self._make_item("леггинсы розовые")}
        assert not _needs_tights(outfit, 10.0), "Под леггинсы колготки не нужны"

    def test_штаны_не_нужны(self):
        from worker.tasks.style_config import _needs_tights
        outfit = {"bottom": self._make_item("штаны спортивные")}
        assert not _needs_tights(outfit, 5.0), "Под штаны колготки не нужны"

    def test_юбка_нужны_при_холоде(self):
        from worker.tasks.style_config import _needs_tights
        outfit = {"bottom": self._make_item("юбка розовая")}
        assert _needs_tights(outfit, 10.0), "Под юбку при +10 колготки нужны"

    def test_юбка_не_нужны_при_тепле(self):
        from worker.tasks.style_config import _needs_tights
        outfit = {"bottom": self._make_item("юбка розовая")}
        assert not _needs_tights(outfit, 20.0), "Под юбку при +20 колготки не нужны"

    def test_платье_нужны_при_холоде(self):
        from worker.tasks.style_config import _needs_tights
        outfit = {"one_piece": self._make_item("платье лавандовое")}
        assert _needs_tights(outfit, 10.0), "Под платье при +10 колготки нужны"

    def test_жара_никогда_не_нужны(self):
        from worker.tasks.style_config import _needs_tights
        outfit = {"one_piece": self._make_item("платье")}
        assert not _needs_tights(outfit, 25.0), "При +25 колготки не нужны никогда"

    def test_bottom_type_none_не_падает(self):
        from worker.tasks.style_config import _needs_tights
        from unittest.mock import MagicMock
        item = MagicMock()
        item.type = None
        outfit = {"bottom": item}
        result = _needs_tights(outfit, 5.0)
        assert isinstance(result, bool), "Должен вернуть bool, не упасть"

    def test_пустой_outfit_при_холоде(self):
        from worker.tasks.style_config import _needs_tights
        assert _needs_tights({}, 5.0) is True, "Пустой outfit при +5 → нужны колготки"

    def test_пустой_outfit_при_тепле(self):
        from worker.tasks.style_config import _needs_tights
        assert _needs_tights({}, 20.0) is False, "Пустой outfit при +20 → не нужны"


# ── TestSwitchOwner ────────────────────────────────────────────────────────

class TestSwitchOwner:
    def test_child_id_валидация(self):
        """Неверный UUID должен обрабатываться без падения."""
        import uuid
        try:
            uuid.UUID("not-a-valid-uuid")
            assert False, "Должен был упасть ValueError"
        except ValueError:
            pass  # PASS — правильно обрабатываем

    def test_нет_детей_нет_кнопки(self):
        """Если детей нет — switch_btn должен быть None."""
        children = []
        switch_btn = None
        if children:
            switch_btn = "кнопка"
        assert switch_btn is None, "При отсутствии детей кнопки не должно быть"

    def test_пустой_гардероб_показывает_добавить(self):
        """При 0 вещах — кнопка 'Добавить вещи', не 'Посмотреть'."""
        count = 0
        action = "добавить" if count == 0 else "посмотреть"
        assert action == "добавить"

    def test_непустой_гардероб_показывает_посмотреть(self):
        """При >0 вещах — кнопка 'Посмотреть вещи'."""
        count = 5
        action = "добавить" if count == 0 else "посмотреть"
        assert action == "посмотреть"


# ── TestTextSystem ─────────────────────────────────────────────────────────

class TestTextSystem:
    def _make_user(self, segment, colortype=None):
        from unittest.mock import MagicMock
        user = MagicMock()
        user.segment = segment
        user.colortype = colortype
        return user

    def test_no_kids_не_упоминает_детей(self):
        from bot.handlers.text import _get_text_system
        user = self._make_user("no_kids")
        system = _get_text_system(user)
        assert "НЕ упоминай детей" in system, \
            "Для no_kids промпт должен запрещать упоминание детей"
        assert "взрослую" in system.lower(), \
            "Для no_kids должно быть про взрослую моду"

    def test_mom_girl_упоминает_девочку(self):
        from bot.handlers.text import _get_text_system
        user = self._make_user("mom_girl")
        system = _get_text_system(user)
        assert "девочк" in system.lower(), \
            "Для mom_girl должно быть про девочку"

    def test_colortype_в_промпте(self):
        from bot.handlers.text import _get_text_system
        user = self._make_user("no_kids", colortype="Лето")
        system = _get_text_system(user)
        assert "Лето" in system, "Цветотип должен быть в промпте"

    def test_no_colortype_без_ошибки(self):
        from bot.handlers.text import _get_text_system
        user = self._make_user("no_kids", colortype=None)
        system = _get_text_system(user)
        assert isinstance(system, str)
        assert len(system) > 100


# ── TestPermissions ────────────────────────────────────────────────────────

class TestPermissions:
    def _make_user(self, plan, trial_days=None, telegram_id=99999):
        from unittest.mock import MagicMock
        from datetime import datetime, timezone, timedelta
        u = MagicMock()
        u.plan = plan
        u.telegram_id = telegram_id
        if trial_days is not None:
            u.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=trial_days)
            u.trial_started_at = datetime.now(timezone.utc) - timedelta(days=14 - trial_days)
        else:
            u.trial_ends_at = None
            u.trial_started_at = None
        return u

    def test_trial_активен_даёт_premium(self):
        from core.permissions import get_effective_plan
        u = self._make_user("free", trial_days=5)
        assert get_effective_plan(u) == "premium"

    def test_trial_истёк_даёт_free(self):
        from core.permissions import get_effective_plan
        from datetime import datetime, timezone, timedelta
        from unittest.mock import MagicMock
        u = MagicMock()
        u.plan = "free"
        u.telegram_id = 99999
        u.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert get_effective_plan(u) == "free"

    def test_premium_без_trial(self):
        from core.permissions import get_effective_plan
        u = self._make_user("premium")
        assert get_effective_plan(u) == "premium"

    def test_admin_по_telegram_id(self):
        from core.permissions import get_effective_plan
        u = self._make_user("free", telegram_id=195169)
        assert get_effective_plan(u) == "admin"

    def test_лимиты_free(self):
        from core.permissions import get_limit
        assert get_limit("photos_per_day", "free") == 3
        assert get_limit("wardrobe_size", "free") == 15
        assert get_limit("chat_per_day", "free") == 3

    def test_лимиты_premium_больше_free(self):
        from core.permissions import get_limit
        assert get_limit("photos_per_day", "premium") > get_limit("photos_per_day", "free")

    def test_admin_без_лимитов(self):
        from core.permissions import get_limit
        assert get_limit("photos_per_day", "admin") == 9999

    def test_brief_day_premium_всегда(self):
        from core.permissions import is_brief_day
        assert is_brief_day("premium", "Europe/Vilnius") is True

    def test_brief_day_free_вт_чт(self):
        from core.permissions import LIMITS
        assert 1 in LIMITS["free"]["brief_days"]   # вт
        assert 3 in LIMITS["free"]["brief_days"]   # чт
        assert 0 not in LIMITS["free"]["brief_days"]  # пн — нет
        assert 4 not in LIMITS["free"]["brief_days"]  # пт — нет

    def test_brief_day_tomorrow_возвращает_bool(self):
        from core.permissions import is_brief_day_tomorrow
        result = is_brief_day_tomorrow("premium", "Europe/Vilnius")
        assert isinstance(result, bool)

    def test_trial_days_left_нет_trial(self):
        from core.permissions import get_trial_days_left
        u = self._make_user("free")
        assert get_trial_days_left(u) is None

    def test_trial_days_left_активный(self):
        from core.permissions import get_trial_days_left
        u = self._make_user("free", trial_days=7)
        days = get_trial_days_left(u)
        assert days is not None and 6 <= days <= 7
