"""
Fashion Bot — тесты ядра системы.
Покрывают: Vision JSON parsing, scoring, _select_outfit, image_processor.

Запуск:
    docker exec docker-app-1 python -m pytest /app/tests/test_core.py -v
    # или локально из корня проекта:
    pytest tests/test_core.py -v
"""
import io
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock

import pytest
from PIL import Image


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES / HELPERS
# ═══════════════════════════════════════════════════════════════════════

def make_jpeg(width: int = 800, height: int = 600, color=(255, 0, 0)) -> bytes:
    """Создаёт JPEG в памяти заданного размера и цвета."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@dataclass
class FakeItem:
    """Мок WardrobeItem для тестов _select_outfit."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    category_group: str = "top"
    type: str = "футболка"
    color: str = "белый"
    season: list = field(default_factory=lambda: ["spring", "summer", "autumn", "winter"])
    last_worn: Optional[date] = None
    score_item: Optional[Decimal] = Decimal("7.5")


@dataclass
class FakeChild:
    birthdate: date
    gender: str = "girl"


@dataclass
class FakeUser:
    segment: str = "mom_girl"
    age: Optional[int] = None
    trimester: Optional[int] = None


@dataclass
class FakeMatrix:
    """Мок ScoringMatrix для тестов calc_item_score."""
    name: str = "3-7"
    max_score: float = 22.0
    criteria: dict = field(default_factory=lambda: {
        "safety":           {"weight": 2},
        "practicality":     {"weight": 2},
        "durability":       {"weight": 2},
        "age_authenticity": {"weight": 2},
        "ease_of_care":     {"weight": 2},
        "colortype":        {"weight": 2},
        "comfort":          {"weight": 2},
        "versatility":      {"weight": 2},
        "condition":        {"weight": 2},
        "size_fit_score":   {"weight": 2},
        "seasonality":      {"weight": 2},
        "_wow_message":     "WOW!",  # должен игнорироваться
    })
    version: str = "v2.0"
    is_active: bool = True


# ═══════════════════════════════════════════════════════════════════════
# 1. IMAGE PROCESSOR
# ═══════════════════════════════════════════════════════════════════════

class TestImageProcessor:
    def setup_method(self):
        from services.image_processor import preprocess, compute_phash, is_duplicate, remove_exif
        self.preprocess = preprocess
        self.compute_phash = compute_phash
        self.is_duplicate = is_duplicate
        self.remove_exif = remove_exif

    def test_preprocess_returns_bytes_and_hash(self):
        """preprocess возвращает (bytes, str)."""
        jpeg = make_jpeg(800, 600)
        result_bytes, phash = self.preprocess(jpeg)
        assert isinstance(result_bytes, bytes)
        assert len(result_bytes) > 0
        assert isinstance(phash, str)
        assert len(phash) == 16  # imagehash возвращает 16-char hex

    def test_preprocess_resizes_large_image(self):
        """Изображение больше 1024px уменьшается."""
        jpeg = make_jpeg(2048, 2048)
        result_bytes, _ = self.preprocess(jpeg)
        img = Image.open(io.BytesIO(result_bytes))
        assert max(img.size) <= 1024

    def test_preprocess_keeps_small_image_size(self):
        """Маленькое изображение не увеличивается."""
        jpeg = make_jpeg(300, 400)
        result_bytes, _ = self.preprocess(jpeg)
        img = Image.open(io.BytesIO(result_bytes))
        assert img.size == (300, 400)

    def test_preprocess_raises_on_too_large(self):
        """Файл > 20MB вызывает ImageTooLargeError."""
        from exceptions import ImageTooLargeError
        big_bytes = b"x" * (21 * 1024 * 1024)
        with pytest.raises(ImageTooLargeError):
            self.preprocess(big_bytes)

    def test_duplicate_detection(self):
        """Одинаковые фото определяются как дубль."""
        jpeg = make_jpeg(800, 600, color=(100, 150, 200))
        _, phash = self.preprocess(jpeg)
        with pytest.raises(Exception):  # DuplicateItemError
            self.preprocess(jpeg, existing_hashes=[phash])

    def test_different_images_not_duplicate(self):
        """Разные фото не считаются дублями."""
        jpeg1 = make_jpeg(800, 600, color=(255, 0, 0))
        jpeg2 = make_jpeg(800, 600, color=(0, 0, 255))
        _, hash1 = self.preprocess(jpeg1)
        result, hash2 = self.preprocess(jpeg2, existing_hashes=[hash1])
        assert isinstance(result, bytes)
        assert hash1 != hash2

    def test_rgba_image_converted_to_rgb(self):
        """PNG с альфа-каналом (RGBA) конвертируется без ошибок."""
        img = Image.new("RGBA", (400, 400), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result_bytes, _ = self.preprocess(buf.getvalue())
        assert isinstance(result_bytes, bytes)

    def test_is_duplicate_same_hash(self):
        """Одинаковые хеши — дубль."""
        jpeg = make_jpeg(500, 500)
        img = Image.open(io.BytesIO(jpeg))
        phash = self.compute_phash(img)
        assert self.is_duplicate(phash, phash) is True

    def test_is_duplicate_different_hash(self):
        """Совершенно разные хеши — не дубль."""
        img1 = Image.new("RGB", (500, 500), color=(255, 0, 0))
        img2 = Image.new("RGB", (500, 500), color=(0, 0, 0))
        h1 = self.compute_phash(img1)
        h2 = self.compute_phash(img2)
        assert self.is_duplicate(h1, h2) is False

    def test_remove_exif_returns_image(self):
        """remove_exif возвращает Image без ошибок."""
        img = Image.new("RGB", (200, 200), color=(10, 20, 30))
        result = self.remove_exif(img)
        assert isinstance(result, Image.Image)
        assert result.size == img.size


# ═══════════════════════════════════════════════════════════════════════
# 2. SCORING
# ═══════════════════════════════════════════════════════════════════════

class TestScoring:
    def setup_method(self):
        from services.scoring import calc_item_score, matrix_name_for_owner, ScoringService
        self.calc_item_score = calc_item_score
        self.matrix_name_for_owner = matrix_name_for_owner

    def test_perfect_score(self):
        """Все критерии = 2 → score = 10.0."""
        matrix = FakeMatrix()
        breakdown = {k: 2 for k in matrix.criteria if not k.startswith("_")}
        score = self.calc_item_score(breakdown, matrix)
        assert score == 10.0

    def test_zero_score(self):
        """Все критерии = 0 → score = 0.0."""
        matrix = FakeMatrix()
        breakdown = {k: 0 for k in matrix.criteria if not k.startswith("_")}
        score = self.calc_item_score(breakdown, matrix)
        assert score == 0.0

    def test_neutral_score(self):
        """Все критерии = 1 → score = 5.0."""
        matrix = FakeMatrix()
        breakdown = {k: 1 for k in matrix.criteria if not k.startswith("_")}
        score = self.calc_item_score(breakdown, matrix)
        assert score == 5.0

    def test_score_ignores_underscore_keys(self):
        """Ключи начинающиеся с _ игнорируются."""
        matrix = FakeMatrix()
        breakdown = {k: 2 for k in matrix.criteria if not k.startswith("_")}
        breakdown["_wow_message"] = 999  # не должен влиять
        score = self.calc_item_score(breakdown, matrix)
        assert score == 10.0

    def test_score_clamps_values(self):
        """Значения > 2 или < 0 зажимаются."""
        matrix = FakeMatrix()
        breakdown = {k: 5 for k in matrix.criteria if not k.startswith("_")}  # > 2
        score = self.calc_item_score(breakdown, matrix)
        assert score == 10.0  # зажато до 2

        breakdown2 = {k: -1 for k in matrix.criteria if not k.startswith("_")}
        score2 = self.calc_item_score(breakdown2, matrix)
        assert score2 == 0.0  # зажато до 0

    def test_score_uses_default_1_for_missing(self):
        """Отсутствующий критерий = 1 по умолчанию."""
        matrix = FakeMatrix()
        score = self.calc_item_score({}, matrix)  # все отсутствуют → 1
        assert score == 5.0

    def test_matrix_name_child_age_0(self):
        child = FakeChild(birthdate=date.today() - timedelta(days=365))
        assert self.matrix_name_for_owner(FakeUser(), child) == "0-3-girl"

    def test_matrix_name_child_age_3(self):
        child = FakeChild(birthdate=date.today() - timedelta(days=365 * 3 + 1))
        assert self.matrix_name_for_owner(FakeUser(), child) == "3-7-girl"

    def test_matrix_name_child_age_7(self):
        child = FakeChild(birthdate=date.today() - timedelta(days=365 * 7 + 1))
        assert self.matrix_name_for_owner(FakeUser(), child) == "7-12-girl"

    def test_matrix_name_child_age_12(self):
        child = FakeChild(birthdate=date.today() - timedelta(days=365 * 12 + 1))
        assert self.matrix_name_for_owner(FakeUser(), child) == "12-16-girl"

    def test_matrix_name_pregnant(self):
        user = FakeUser(segment="pregnant", trimester=2)
        assert self.matrix_name_for_owner(user) == "pregnant-2"

    def test_matrix_name_adult_25_35(self):
        user = FakeUser(segment="no_kids", age=30)
        assert self.matrix_name_for_owner(user) == "25-35"

    def test_matrix_name_adult_no_age_defaults_30(self):
        user = FakeUser(segment="no_kids", age=None)
        assert self.matrix_name_for_owner(user) == "25-35"


# ═══════════════════════════════════════════════════════════════════════
# 3. VISION JSON PARSING
# ═══════════════════════════════════════════════════════════════════════

class TestVisionParsing:
    """
    Тестирует логику парсинга JSON из ответа Claude Vision.
    Изолирована от реального API — тестируем только парсер.
    """

    def _parse(self, raw: str) -> list[dict]:
        """Воспроизводит логику парсинга из _call_vision."""
        raw = raw.strip()
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
            parsed = []
        for item in parsed:
            if isinstance(item.get("type"), str):
                item["type"] = item["type"].lower()
            if isinstance(item.get("color"), str):
                item["color"] = item["color"].lower()
        return parsed

    def test_clean_json_array(self):
        raw = '[{"type": "Футболка", "color": "Синий", "category_group": "top"}]'
        result = self._parse(raw)
        assert len(result) == 1
        assert result[0]["type"] == "футболка"
        assert result[0]["color"] == "синий"

    def test_markdown_fenced_json(self):
        """Claude иногда оборачивает в ```json ... ```."""
        raw = '```json\n[{"type": "Куртка", "color": "Зелёный"}]\n```'
        result = self._parse(raw)
        assert len(result) == 1
        assert result[0]["type"] == "куртка"

    def test_single_dict_wrapped_in_list(self):
        """Если Claude вернул dict вместо list."""
        raw = '{"type": "Штаны", "color": "Чёрный", "category_group": "bottom"}'
        result = self._parse(raw)
        assert len(result) == 1
        assert result[0]["category_group"] == "bottom"

    def test_truncated_json_recovered(self):
        """Обрезанный JSON — восстанавливаем по последней },."""
        raw = '[{"type": "носки", "color": "белый"}, {"type": "куртка", "color": "синий"'
        result = self._parse(raw)
        assert len(result) == 1
        assert result[0]["type"] == "носки"

    def test_invalid_json_returns_empty(self):
        raw = "not json at all"
        result = self._parse(raw)
        assert result == []

    def test_empty_array(self):
        raw = "[]"
        result = self._parse(raw)
        assert result == []

    def test_multiple_items(self):
        raw = json.dumps([
            {"type": "Футболка", "color": "Белый", "category_group": "top"},
            {"type": "Джинсы", "color": "Синий", "category_group": "bottom"},
            {"type": "Кроссовки", "color": "Серый", "category_group": "footwear"},
        ])
        result = self._parse(raw)
        assert len(result) == 3
        assert result[2]["type"] == "кроссовки"

    def test_score_breakdown_preserved(self):
        """score_breakdown из ответа Claude сохраняется как есть."""
        breakdown = {"safety": 2, "practicality": 1, "durability": 2}
        raw = json.dumps([{"type": "Куртка", "color": "Синий", "score_breakdown": breakdown}])
        result = self._parse(raw)
        assert result[0]["score_breakdown"] == breakdown


# ═══════════════════════════════════════════════════════════════════════
# 4. MORNING BRIEF: _select_outfit
# ═══════════════════════════════════════════════════════════════════════

class TestSelectOutfit:
    def setup_method(self):
        from worker.tasks.morning_brief import _select_outfit
        self._select_outfit = _select_outfit
        self.today = date.today()

    def _items(self, specs: list[dict]) -> list[FakeItem]:
        """Создаёт список FakeItem из спецификаций."""
        return [FakeItem(**s) for s in specs]

    def test_cold_weather_includes_outerwear(self):
        """При -5°C выбирается верхняя одежда."""
        items = self._items([
            {"category_group": "outerwear", "type": "куртка"},
            {"category_group": "top", "type": "свитер"},
            {"category_group": "bottom", "type": "штаны"},
        ])
        result = self._select_outfit(items, "winter", self.today, temp_morning=-5.0)
        assert result["outerwear"] is not None
        assert result["outerwear"].type == "куртка"

    def test_warm_weather_no_outerwear(self):
        """При +28°C верхняя одежда не выбирается."""
        items = self._items([
            {"category_group": "outerwear", "type": "куртка"},
            {"category_group": "top", "type": "футболка"},
            {"category_group": "bottom", "type": "шорты"},
        ])
        result = self._select_outfit(items, "summer", self.today, temp_morning=28.0)
        assert result["outerwear"] is None

    def test_thermals_at_freezing(self):
        """При 0°C добавляется термобельё."""
        items = self._items([
            {"category_group": "underwear", "type": "термолонгслив"},
            {"category_group": "underwear", "type": "термолеггинсы"},
            {"category_group": "top", "type": "свитер"},
            {"category_group": "bottom", "type": "штаны"},
        ])
        result = self._select_outfit(items, "winter", self.today, temp_morning=0.0)
        assert result["thermal_top"] is not None or result["thermal_bottom"] is not None

    def test_no_thermals_at_15_degrees(self):
        """При +15°C термобельё не нужно."""
        items = self._items([
            {"category_group": "underwear", "type": "термолонгслив"},
            {"category_group": "top", "type": "кофта"},
            {"category_group": "bottom", "type": "джинсы"},
        ])
        result = self._select_outfit(items, "spring", self.today, temp_morning=15.0)
        assert result["thermal_top"] is None
        assert result["thermal_bottom"] is None

    def test_rain_warning(self):
        """При осадках > 50% появляется предупреждение."""
        items = self._items([
            {"category_group": "top", "type": "футболка"},
        ])
        result = self._select_outfit(items, "spring", self.today,
                                     temp_morning=15.0, precip_evening=75)
        assert any("дождь" in w for w in result["warnings"])

    def test_no_rain_warning_below_threshold(self):
        """При осадках <= 50% предупреждения нет."""
        items = self._items([
            {"category_group": "top", "type": "футболка"},
        ])
        result = self._select_outfit(items, "spring", self.today,
                                     temp_morning=15.0, precip_evening=30)
        assert not any("дождь" in w for w in result["warnings"])

    def test_temperature_swing_warning(self):
        """Разница утро/вечер > 8°C → предупреждение про слои."""
        items = self._items([{"category_group": "top", "type": "футболка"}])
        result = self._select_outfit(items, "spring", self.today,
                                     temp_morning=5.0, temp_evening=20.0)
        assert any("слоями" in w for w in result["warnings"])

    def test_already_worn_today_skipped(self):
        """Вещь, надетая сегодня, не предлагается."""
        items = self._items([
            {"category_group": "top", "type": "кофта синяя", "last_worn": self.today},
            {"category_group": "top", "type": "свитер красный", "last_worn": None},
            {"category_group": "bottom", "type": "джинсы"},
        ])
        result = self._select_outfit(items, "spring", self.today, temp_morning=10.0)
        if result["top"]:
            assert "синяя" not in result["top"].type

    def test_season_filter(self):
        """Зимняя вещь не предлагается летом."""
        items = self._items([
            {"category_group": "outerwear", "type": "пуховик",
             "season": ["winter"]},
            {"category_group": "top", "type": "майка",
             "season": ["summer"]},
        ])
        result = self._select_outfit(items, "summer", self.today, temp_morning=28.0)
        assert result["outerwear"] is None

    def test_empty_wardrobe(self):
        """Пустой гардероб не падает, возвращает пустой результат."""
        result = self._select_outfit([], "spring", self.today, temp_morning=10.0)
        assert result["top"] is None
        assert result["bottom"] is None
        assert result["all_items"] == []

    def test_underwear_text_fallback(self):
        """Если нет underwear в гардеробе — underwear_text = 'трусики'."""
        items = self._items([
            {"category_group": "top", "type": "футболка"},
        ])
        result = self._select_outfit(items, "spring", self.today, temp_morning=15.0)
        assert result["underwear_text"] == "трусики"

    def test_warm_prefers_shorts_over_pants(self):
        """При жаре предпочитаются шорты перед штанами."""
        items = self._items([
            {"category_group": "top", "type": "футболка"},
            {"category_group": "bottom", "type": "шорты синие"},
            {"category_group": "bottom", "type": "джинсы"},
        ])
        result = self._select_outfit(items, "summer", self.today, temp_morning=28.0)
        if result["bottom"]:
            assert "шорт" in result["bottom"].type.lower()

    def test_cold_prefers_jeans_over_shorts(self):
        """При холоде предпочитаются джинсы перед шортами."""
        items = self._items([
            {"category_group": "top", "type": "кофта"},
            {"category_group": "bottom", "type": "джинсы"},
            {"category_group": "bottom", "type": "шорты"},
        ])
        result = self._select_outfit(items, "spring", self.today, temp_morning=10.0)
        if result["bottom"]:
            assert "джинс" in result["bottom"].type.lower()
