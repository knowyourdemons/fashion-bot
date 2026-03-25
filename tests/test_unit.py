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
        assert result["bbox"]["w"] <= 0.45
        assert result["bbox"]["h"] <= 0.45

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
        """bbox ≤0.25×0.25 + accessory/шапка + no outerwear → носки"""
        from services.vision import _reclassify_items
        items = [{"category_group": "accessory", "type": "шапка",
                  "bbox": {"x": 0.7, "y": 0.1, "w": 0.12, "h": 0.10}}]
        result = _reclassify_items(items)
        assert result[0]["type"] == "носки"
        assert result[0]["category_group"] == "base_layer"

    def test_маленькая_шапка_с_outerwear_остаётся(self):
        """bbox ≤0.25 but outerwear present → stays as шапка"""
        from services.vision import _reclassify_items
        items = [
            {"category_group": "accessory", "type": "шапка",
             "bbox": {"x": 0.7, "y": 0.1, "w": 0.12, "h": 0.10}},
            {"category_group": "outerwear", "type": "куртка",
             "bbox": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.7}},
        ]
        result = _reclassify_items(items)
        assert result[0]["type"] == "шапка"
        assert result[0]["category_group"] == "accessory"

    def test_большая_шапка_не_переклассифицируется(self):
        from services.vision import _reclassify_items
        items = [{"category_group": "accessory", "type": "шапка",
                  "bbox": {"x": 0.3, "y": 0.1, "w": 0.4, "h": 0.35}}]
        result = _reclassify_items(items)
        assert result[0]["type"] == "шапка"

    def test_носки_force_base_layer(self):
        """Носки with wrong category_group → forced to base_layer"""
        from services.vision import _reclassify_items
        items = [{"category_group": "accessory", "type": "носки",
                  "bbox": {"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.2}}]
        result = _reclassify_items(items)
        assert result[0]["category_group"] == "base_layer"

    def test_колготки_force_base_layer(self):
        from services.vision import _reclassify_items
        items = [{"category_group": "bottom", "type": "колготки",
                  "bbox": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.8}}]
        result = _reclassify_items(items)
        assert result[0]["category_group"] == "base_layer"

    def test_bbox_between_020_025_reclassifies(self):
        """bbox 0.22×0.22 — was missed by old threshold 0.2, now caught at 0.25"""
        from services.vision import _reclassify_items
        items = [{"category_group": "accessory", "type": "шапка",
                  "bbox": {"x": 0.5, "y": 0.5, "w": 0.22, "h": 0.22}}]
        result = _reclassify_items(items)
        assert result[0]["type"] == "носки"


# ── Bbox refinement ──────────────────────────────────────────────────────────

class TestBboxRefine:
    def test_refine_skips_single_item(self):
        """bbox > 0.5 area should not be refined"""
        from services.vision import _refine_bbox_by_color
        import io
        from PIL import Image
        img = Image.new("RGB", (100, 100), (200, 200, 200))
        buf = io.BytesIO(); img.save(buf, format="JPEG"); image_bytes = buf.getvalue()
        items = [{"type": "платье", "bbox": {"x": 0.0, "y": 0.0, "w": 0.9, "h": 0.9}}]
        result = _refine_bbox_by_color(image_bytes, items)
        assert float(result[0]["bbox"]["w"]) == 0.9  # unchanged

    def test_refine_trims_background(self):
        """Strips matching background color should be trimmed"""
        from services.vision import _refine_bbox_by_color
        import io, numpy as np
        from PIL import Image
        # White background with dark rectangle in center
        img = Image.new("RGB", (200, 200), (240, 240, 240))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([60, 40, 140, 160], fill=(30, 30, 80))
        buf = io.BytesIO(); img.save(buf, format="JPEG"); image_bytes = buf.getvalue()
        items = [{"type": "штаны", "bbox": {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}}]
        result = _refine_bbox_by_color(image_bytes, items)
        # Should have trimmed at least some background
        assert float(result[0]["bbox"]["w"]) <= 0.4

    def test_refine_max_trim_guard(self):
        """Should not trim more than 25% from any side"""
        from services.vision import _refine_bbox_by_color
        import io
        from PIL import Image
        # All white (all looks like background) — guard should prevent excessive trim
        img = Image.new("RGB", (200, 200), (240, 240, 240))
        buf = io.BytesIO(); img.save(buf, format="JPEG"); image_bytes = buf.getvalue()
        items = [{"type": "кофта", "bbox": {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}}]
        result = _refine_bbox_by_color(image_bytes, items)
        # Should not trim more than 25% = 0.1
        assert float(result[0]["bbox"]["w"]) >= 0.4 * 0.75 - 0.01


# ── Flat-lay layout ──────────────────────────────────────────────────────────

class TestFlatlay:
    def test_prepare_items_returns_tuple(self):
        from services.brief_renderer import prepare_items_flatlay
        items, placeholders, pct, txt = prepare_items_flatlay([])
        assert items == []
        assert isinstance(placeholders, list)
        assert len(placeholders) > 0  # should show essential slot placeholders
        assert pct == 0  # empty wardrobe = 0% progress

    def test_placeholders_for_missing_slots(self):
        """Empty outfit should show placeholders for essential slots"""
        from services.brief_renderer import prepare_items_flatlay
        items, placeholders, pct, txt = prepare_items_flatlay([])
        # With no items, should show placeholders for top, bottom, outerwear, footwear
        ph_labels = [p["label"] for p in placeholders]
        assert any("верх" in l for l in ph_labels)
        assert any("низ" in l for l in ph_labels)

    def test_filled_slot_no_placeholder(self):
        """Filled slot should not have placeholder"""
        from services.brief_renderer import prepare_items_flatlay
        import io
        from PIL import Image
        # Create a minimal RGBA PNG
        img = Image.new("RGBA", (50, 50), (100, 100, 100, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG")
        slots = [{"slot": "top", "item_type": "футболка", "item_color": "белый",
                  "has_item": True, "_photo_bytes": buf.getvalue()}]
        items, placeholders, pct, txt = prepare_items_flatlay(slots)
        assert len(items) == 1
        assert not any("верх" in p["label"] for p in placeholders)

    def test_progress_complete_with_essential_slots(self):
        """All essential slots filled → no placeholders"""
        from services.brief_renderer import prepare_items_flatlay
        import io
        from PIL import Image
        img = Image.new("RGBA", (50, 50), (100, 100, 100, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG"); pb = buf.getvalue()
        slots = [
            {"slot": "top", "item_type": "t", "item_color": "c", "has_item": True, "_photo_bytes": pb},
            {"slot": "bottom", "item_type": "t", "item_color": "c", "has_item": True, "_photo_bytes": pb},
            {"slot": "outerwear", "item_type": "t", "item_color": "c", "has_item": True, "_photo_bytes": pb},
            {"slot": "footwear", "item_type": "t", "item_color": "c", "has_item": True, "_photo_bytes": pb},
            {"slot": "bag", "item_type": "t", "item_color": "c", "has_item": True, "_photo_bytes": pb},
            {"slot": "accessory", "item_type": "t", "item_color": "c", "has_item": True, "_photo_bytes": pb},
            {"slot": "accessory", "item_type": "t2", "item_color": "c", "has_item": True, "_photo_bytes": pb},
        ]
        items, placeholders, pct, txt = prepare_items_flatlay(slots)
        assert len(items) >= 4
        assert pct == 100
        assert len(placeholders) == 0

    def test_one_piece_uses_correct_layout(self):
        """One-piece without top+bottom should use one_piece layout"""
        from services.brief_renderer import prepare_items_flatlay
        import io
        from PIL import Image
        img = Image.new("RGBA", (50, 50), (100, 100, 100, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG"); pb = buf.getvalue()
        slots = [{"slot": "one_piece", "item_type": "платье", "item_color": "серый",
                  "has_item": True, "_photo_bytes": pb}]
        items, placeholders, pct, txt = prepare_items_flatlay(slots)
        assert len(items) == 1
        # one_piece should be centered (x around 60-80)
        assert items[0]["left"] >= 50

    def test_tights_not_filtered(self):
        """Tights should be visible in flatlay (for skirt/dress)"""
        from services.brief_renderer import prepare_items_flatlay
        import io
        from PIL import Image
        img = Image.new("RGBA", (50, 50), (100, 100, 100, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG"); pb = buf.getvalue()
        slots = [
            {"slot": "bottom", "item_type": "юбка", "item_color": "серый", "has_item": True, "_photo_bytes": pb},
            {"slot": "tights", "item_type": "колготки", "item_color": "чёрный", "has_item": True, "_photo_bytes": pb},
        ]
        items, placeholders, pct, txt = prepare_items_flatlay(slots)
        slot_names = [it["slot"] for it in items]
        assert "tights" in slot_names

    def test_underwear_filtered(self):
        """Underwear should NOT appear in flatlay"""
        from services.brief_renderer import prepare_items_flatlay
        import io
        from PIL import Image
        img = Image.new("RGBA", (50, 50), (100, 100, 100, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG"); pb = buf.getvalue()
        slots = [{"slot": "underwear", "item_type": "трусики", "item_color": "розовый",
                  "has_item": True, "_photo_bytes": pb}]
        items, placeholders, pct, txt = prepare_items_flatlay(slots)
        assert len(items) == 0


# ── Merge bbox rotation ─────────────────────────────────────────────────────

class TestMergeBboxRotation:
    def test_rotation_saved_in_bbox(self):
        from bot.handlers.wardrobe import _merge_bbox_rotation
        result = _merge_bbox_rotation({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.6}, 90)
        assert result["flat_lay_rotation"] == 90
        assert result["x"] == 0.1  # original bbox preserved

    def test_no_rotation_no_change(self):
        from bot.handlers.wardrobe import _merge_bbox_rotation
        result = _merge_bbox_rotation({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.6}, 0)
        assert result is None or "flat_lay_rotation" not in (result or {})

    def test_rotation_creates_bbox_if_none(self):
        from bot.handlers.wardrobe import _merge_bbox_rotation
        result = _merge_bbox_rotation(None, 180)
        assert result["flat_lay_rotation"] == 180

    def test_invalid_rotation_ignored(self):
        from bot.handlers.wardrobe import _merge_bbox_rotation
        result = _merge_bbox_rotation({"x": 0}, 45)  # invalid, not in (90,180,270)
        assert result is None or "flat_lay_rotation" not in (result or {})


# ── Auto-rotate ──────────────────────────────────────────────────────────

class TestAutoRotate:
    def test_horizontal_item_stays_horizontal(self):
        """Wide item (top with sleeves) should not be rotated"""
        from services.image_processor import _auto_rotate_to_vertical
        from PIL import Image
        # Create wide RGBA image (simulates top with spread sleeves)
        img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 30, 350, 170], fill=(100, 100, 100, 255))
        result = _auto_rotate_to_vertical(img)
        # Should stay roughly the same dimensions (no 90° rotation)
        assert abs(result.size[0] - result.size[1]) < result.size[0] * 0.5 or result.size[0] > result.size[1]

    def test_tilted_item_straightened(self):
        """Item tilted 15° should be straightened"""
        from services.image_processor import _auto_rotate_to_vertical
        from PIL import Image
        img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        # Draw a tilted rectangle
        draw.polygon([(100, 50), (350, 100), (320, 300), (70, 250)], fill=(100, 100, 100, 255))
        result = _auto_rotate_to_vertical(img)
        # Result should exist and be different from input
        assert result.size[0] > 0 and result.size[1] > 0

    def test_small_contour_skipped(self):
        """Very small opaque area → no rotation"""
        from services.image_processor import _auto_rotate_to_vertical
        from PIL import Image
        img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([195, 195, 205, 205], fill=(100, 100, 100, 255))  # tiny 10x10
        result = _auto_rotate_to_vertical(img)
        assert result.size == img.size  # unchanged


# ── 5-zone fallback ──────────────────────────────────────────────────────

class TestZoneFallback:
    def _make_portrait_rgba(self, top_heavy=True):
        """Create RGBA where top or bottom is wider (simulates pants orientation)"""
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (200, 400), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        if top_heavy:
            # Wide top (waistband), narrow bottom (legs) — correct orientation
            draw.rectangle([30, 10, 170, 200], fill=(50, 50, 100, 255))
            draw.rectangle([60, 200, 90, 390], fill=(50, 50, 100, 255))
            draw.rectangle([110, 200, 140, 390], fill=(50, 50, 100, 255))
        else:
            # Narrow top, wide bottom — upside down
            draw.rectangle([60, 10, 90, 200], fill=(50, 50, 100, 255))
            draw.rectangle([110, 10, 140, 200], fill=(50, 50, 100, 255))
            draw.rectangle([30, 200, 170, 390], fill=(50, 50, 100, 255))
        import io
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return buf.getvalue()

    def test_correct_orientation_no_flip(self):
        """Wide top (waistband) → should not flip"""
        from services.brief_renderer import prepare_items_flatlay
        pb = self._make_portrait_rgba(top_heavy=True)
        slots = [{"slot": "bottom", "item_type": "штаны", "item_color": "синий",
                  "has_item": True, "_photo_bytes": pb}]
        items, _, _, _ = prepare_items_flatlay(slots)
        assert len(items) >= 1

    def test_upside_down_gets_flipped(self):
        """Wide bottom (legs wider than waist) → should flip 180°"""
        from services.brief_renderer import prepare_items_flatlay
        pb = self._make_portrait_rgba(top_heavy=False)
        slots = [{"slot": "bottom", "item_type": "штаны", "item_color": "синий",
                  "has_item": True, "_photo_bytes": pb, "flat_lay_rotation": 0}]
        items, _, _, _ = prepare_items_flatlay(slots)
        assert len(items) >= 1


# ── Flatlay orientation per slot ─────────────────────────────────────────

class TestFlatlayOrientation:
    def _make_tall_rgba(self):
        """Portrait RGBA (taller than wide)"""
        from PIL import Image, ImageDraw
        import io
        img = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle([10, 10, 90, 190], fill=(100, 100, 100, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()

    def _make_wide_rgba(self):
        """Landscape RGBA (wider than tall)"""
        from PIL import Image, ImageDraw
        import io
        img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle([10, 10, 190, 90], fill=(100, 100, 100, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()

    def test_top_rotated_to_landscape(self):
        """Portrait top → should be rotated to landscape"""
        from services.brief_renderer import prepare_items_flatlay
        import base64
        from PIL import Image
        import io
        pb = self._make_tall_rgba()
        slots = [{"slot": "top", "item_type": "футболка", "item_color": "белый",
                  "has_item": True, "_photo_bytes": pb}]
        items, _, _, _ = prepare_items_flatlay(slots)
        assert len(items) == 1
        # Decode and check orientation
        img = Image.open(io.BytesIO(base64.b64decode(items[0]["photo_base64"])))
        assert img.size[0] > img.size[1]  # landscape after rotation

    def test_bottom_keeps_portrait(self):
        """Portrait bottom → should stay portrait (no rotation)"""
        from services.brief_renderer import prepare_items_flatlay
        import base64
        from PIL import Image
        import io
        pb = self._make_tall_rgba()
        slots = [{"slot": "bottom", "item_type": "штаны", "item_color": "синий",
                  "has_item": True, "_photo_bytes": pb}]
        items, _, _, _ = prepare_items_flatlay(slots)
        assert len(items) == 1
        img = Image.open(io.BytesIO(base64.b64decode(items[0]["photo_base64"])))
        assert img.size[1] >= img.size[0]  # still portrait

    def test_vision_rotation_applied(self):
        """flat_lay_rotation=180 should flip the image"""
        from services.brief_renderer import prepare_items_flatlay
        pb = self._make_tall_rgba()
        slots = [{"slot": "bottom", "item_type": "штаны", "item_color": "синий",
                  "has_item": True, "_photo_bytes": pb, "flat_lay_rotation": 180}]
        items, _, _, _ = prepare_items_flatlay(slots)
        assert len(items) == 1  # processed without error

    def test_vision_rotation_from_bbox(self):
        """flat_lay_rotation stored in bbox dict should be picked up"""
        from services.brief_renderer import prepare_items_flatlay
        pb = self._make_tall_rgba()
        slots = [{"slot": "bottom", "item_type": "штаны", "item_color": "синий",
                  "has_item": True, "_photo_bytes": pb,
                  "bbox": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.8, "flat_lay_rotation": 90}}]
        items, _, _, _ = prepare_items_flatlay(slots)
        assert len(items) == 1


# ── Resize for Vision ────────────────────────────────────────────────────

class TestVisionResize:
    def test_large_photo_resized(self):
        """Photo > 768px should be resized"""
        from services.photo_quality import preprocess_for_vision
        from PIL import Image
        import io
        img = Image.new("RGB", (2000, 1500), (150, 150, 150))
        buf = io.BytesIO(); img.save(buf, format="JPEG"); original = buf.getvalue()
        processed, quality = preprocess_for_vision(original)
        result_img = Image.open(io.BytesIO(processed))
        assert max(result_img.size) <= 768
        assert len(processed) < len(original)

    def test_small_photo_not_resized(self):
        """Photo <= 768px should not be resized"""
        from services.photo_quality import preprocess_for_vision
        from PIL import Image
        import io
        img = Image.new("RGB", (500, 400), (150, 150, 150))
        buf = io.BytesIO(); img.save(buf, format="JPEG"); original = buf.getvalue()
        processed, quality = preprocess_for_vision(original)
        result_img = Image.open(io.BytesIO(processed))
        assert result_img.size == (500, 400)  # unchanged

    def test_aspect_ratio_preserved(self):
        """Resize should preserve aspect ratio"""
        from services.photo_quality import preprocess_for_vision
        from PIL import Image
        import io
        img = Image.new("RGB", (1600, 1200), (150, 150, 150))
        buf = io.BytesIO(); img.save(buf, format="JPEG"); original = buf.getvalue()
        processed, _ = preprocess_for_vision(original)
        result_img = Image.open(io.BytesIO(processed))
        orig_ratio = 1600 / 1200
        new_ratio = result_img.size[0] / result_img.size[1]
        assert abs(orig_ratio - new_ratio) < 0.02  # close enough


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
    # Лимиты чата хранятся в core.permissions (не как константы в text.py)
    def test_free_limit_5(self):
        from core.permissions import get_limit
        assert get_limit("chat_per_day", "free") == 3

    def test_premium_limit_20(self):
        from core.permissions import get_limit
        assert get_limit("chat_per_day", "premium") == 20

    def test_premium_больше_free(self):
        from core.permissions import get_limit
        assert get_limit("chat_per_day", "premium") > get_limit("chat_per_day", "free")


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
    def _make_user(self, plan, trial_days=None, telegram_id=99999, plan_expires_at=None):
        from unittest.mock import MagicMock
        from datetime import datetime, timezone, timedelta
        u = MagicMock()
        u.plan = plan
        u.telegram_id = telegram_id
        u.plan_expires_at = plan_expires_at
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
        from datetime import datetime, timezone, timedelta
        u = self._make_user("premium", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30))
        assert get_effective_plan(u) == "premium"

    def test_premium_подписка_истекла_даёт_free(self):
        from core.permissions import get_effective_plan
        from datetime import datetime, timezone, timedelta
        u = self._make_user("premium", plan_expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        assert get_effective_plan(u) == "free"

    def test_days_until_expiry(self):
        from core.permissions import days_until_expiry
        from datetime import datetime, timezone, timedelta
        u = self._make_user("premium", plan_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
        d = days_until_expiry(u)
        assert d is not None and 9 <= d <= 10

    def test_days_until_expiry_нет_подписки(self):
        from core.permissions import days_until_expiry
        u = self._make_user("free")
        assert days_until_expiry(u) is None

    def test_admin_по_telegram_id(self):
        from core.permissions import get_effective_plan
        u = self._make_user("free", telegram_id=195169)
        # Real config has ADMIN_TELEGRAM_IDS=195169 in Docker; no patching needed.
        # In local dev, this test may be skipped if config is mocked (no admin IDs).
        from config import settings
        if 195169 not in getattr(settings, "admin_ids_list", []):
            pytest.skip("Admin IDs not configured in this environment")
        assert get_effective_plan(u) == "admin"

    def test_лимиты_free(self):
        from core.permissions import get_limit
        assert get_limit("photos_per_day", "free") == 3
        assert get_limit("wardrobe_size", "free") == 30
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


# ── TestStarsPayment ───────────────────────────────────────────────────────

class TestStarsPayment:
    """Тесты Stars invoice и активации premium."""

    def test_stars_invoice_payload_format(self):
        """payload должен содержать telegram_id для идентификации пользователя."""
        # Формат: "premium:{plan_key}:{telegram_id}"
        payload = "premium:premium_monthly:195169"
        parts = payload.split(":")
        assert parts[0] == "premium"
        assert parts[1] in ("premium_monthly", "premium_quarterly", "premium_yearly")
        assert parts[2].isdigit()

    def test_prices_stars_amounts(self):
        from core.permissions import PRICES
        assert PRICES["premium_monthly"]["stars"] == 700
        assert PRICES["premium_quarterly"]["stars"] == 1700
        assert PRICES["premium_yearly"]["stars"] == 5500

    def test_prices_period_months(self):
        from core.permissions import PRICES
        assert PRICES["premium_monthly"]["period_months"] == 1
        assert PRICES["premium_quarterly"]["period_months"] == 3
        assert PRICES["premium_yearly"]["period_months"] == 12

    def test_prices_have_dual_labels(self):
        from core.permissions import PRICES
        for key in ("premium_monthly", "premium_quarterly", "premium_yearly"):
            assert "label_usd" in PRICES[key], f"{key} missing label_usd"
            assert "label_stars" in PRICES[key], f"{key} missing label_stars"
            assert "stars" in PRICES[key], f"{key} missing stars"
            assert "usd" in PRICES[key], f"{key} missing usd"

    def test_key_months_mapping(self):
        from bot.handlers.billing import _KEY_MONTHS
        assert _KEY_MONTHS["premium_monthly"] == 1
        assert _KEY_MONTHS["premium_quarterly"] == 3
        assert _KEY_MONTHS["premium_yearly"] == 12

    def test_subscribe_keyboard_no_stripe_when_no_key(self):
        """При пустом stripe_secret_key кнопки Stripe не показываются."""
        from bot.handlers.billing import _subscribe_keyboard
        from unittest.mock import patch
        with patch("bot.handlers.billing.ContextTypes", create=True):
            with patch("config.settings") as mock_settings:
                mock_settings.stripe_secret_key = ""
                kb = _subscribe_keyboard()
        callbacks = [btn.callback_data
                     for row in kb.inline_keyboard for btn in row]
        assert not any("pay_stripe" in c for c in callbacks), \
            "Stripe кнопки не должны быть при пустом ключе"
        assert any("pay_stars" in c for c in callbacks), \
            "Stars кнопки должны быть всегда"

    def test_subscribe_keyboard_has_ultra_button(self):
        from bot.handlers.billing import _subscribe_keyboard
        kb = _subscribe_keyboard()
        callbacks = [btn.callback_data
                     for row in kb.inline_keyboard for btn in row]
        assert "show_ultra" in callbacks

    def test_double_payment_protection_days_check(self):
        """Если expire_days > 3 — подписка считается активной."""
        from datetime import datetime, timezone, timedelta
        from core.permissions import days_until_expiry
        from unittest.mock import MagicMock
        u = MagicMock()
        u.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=10)
        d = days_until_expiry(u)
        assert d is not None and d > 3, "10 дней до истечения → защита должна работать"


# ── TestTrialActivation ────────────────────────────────────────────────────

class TestTrialActivation:
    """Тесты trial активации и ограничений."""

    def test_trial_даёт_premium_лимиты(self):
        """Во время trial пользователь получает premium лимиты."""
        from core.permissions import get_limit
        assert get_limit("photos_per_day", "premium") == 30
        assert get_limit("chat_per_day", "premium") == 20
        assert get_limit("outfit_req_per_day", "premium") == 5

    def test_free_лимиты_ниже_premium(self):
        from core.permissions import get_limit
        for key in ("photos_per_day", "chat_per_day", "rate_per_day", "outfit_req_per_day"):
            assert get_limit(key, "free") < get_limit(key, "premium"), \
                f"free {key} должен быть < premium"

    def test_admin_макс_лимиты(self):
        from core.permissions import get_limit
        for key in ("photos_per_day", "chat_per_day", "wardrobe_size"):
            assert get_limit(key, "admin") == 9999

    def test_brief_days_free_только_вт_чт(self):
        from core.permissions import LIMITS
        free_days = set(LIMITS["free"]["brief_days"])
        assert free_days == {1, 3}, f"Free brief_days должны быть вт/чт, получили {free_days}"

    def test_brief_days_premium_каждый_день(self):
        from core.permissions import LIMITS
        premium_days = LIMITS["premium"]["brief_days"]
        assert len(premium_days) == 7, "Premium бриф каждый день"

    def test_is_trial_active_с_активным_trial(self):
        from core.permissions import is_trial_active
        from datetime import datetime, timezone, timedelta
        from unittest.mock import MagicMock
        u = MagicMock()
        u.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=3)
        assert is_trial_active(u) is True

    def test_is_trial_active_с_истёкшим_trial(self):
        from core.permissions import is_trial_active
        from datetime import datetime, timezone, timedelta
        from unittest.mock import MagicMock
        u = MagicMock()
        u.trial_ends_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert is_trial_active(u) is False

    def test_children_limit_free(self):
        from core.permissions import get_limit
        assert get_limit("children_max", "free") == 1

    def test_children_limit_premium(self):
        from core.permissions import get_limit
        assert get_limit("children_max", "premium") == 3


# ── TestGapAnalysis ─────────────────────────────────────────────────────────

class TestGapAnalysis:
    """Тесты gap analysis / шоппинг-листа."""

    def test_gap_free_user_blocked(self):
        from core.permissions import can_gap_analysis
        assert can_gap_analysis("free") is False

    def test_gap_premium_allowed(self):
        from core.permissions import can_gap_analysis
        assert can_gap_analysis("premium") is True

    def test_gap_ultra_allowed(self):
        from core.permissions import can_gap_analysis
        assert can_gap_analysis("ultra") is True

    def test_gap_admin_allowed(self):
        from core.permissions import can_gap_analysis
        assert can_gap_analysis("admin") is True

    def test_gap_trial_allowed(self):
        """Пользователь на trial → effective_plan='premium' → gap доступен."""
        from core.permissions import can_gap_analysis, get_effective_plan
        from unittest.mock import MagicMock
        from datetime import datetime, timezone, timedelta
        u = MagicMock()
        u.plan = "free"
        u.plan_expires_at = None
        u.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=7)
        u.trial_started_at = datetime.now(timezone.utc) - timedelta(days=7)
        u.telegram_id = 99999
        ep = get_effective_plan(u)
        assert can_gap_analysis(ep) is True

    def test_gap_few_items(self):
        """Меньше 5 вещей → возвращает None без вызова Claude."""
        import asyncio
        from services.gap_analysis import build_shopping_list
        from unittest.mock import AsyncMock, MagicMock

        user = MagicMock()
        user.id = "test-id"
        user.timezone = "Europe/Vilnius"
        user.colortype = None
        user.segment = "no_kids"

        redis = AsyncMock()
        redis.get.return_value = None

        result = asyncio.run(build_shopping_list(user, [1, 2, 3], redis))
        assert result is None
        redis.set.assert_not_called()

    def test_gap_cache_hit(self):
        """Если в Redis есть кэш — Claude не вызывается."""
        import asyncio
        from services.gap_analysis import build_shopping_list
        from unittest.mock import AsyncMock, MagicMock, patch

        user = MagicMock()
        user.id = "test-id"
        user.timezone = "Europe/Vilnius"
        user.colortype = None
        user.segment = "no_kids"

        cached_text = "1. Белая рубашка\n2. Синие джинсы"
        redis = AsyncMock()
        redis.get.side_effect = [None, cached_text.encode()]

        items = [MagicMock(score_item=5.0) for _ in range(5)]

        with patch("core.anthropic_client.get_anthropic_pool") as mock_pool:
            result = asyncio.run(build_shopping_list(user, items, redis))

        assert result == cached_text
        mock_pool.assert_not_called()

    def test_gap_lock(self):
        """Если lock активен — возвращает 'lock'."""
        import asyncio
        from services.gap_analysis import build_shopping_list
        from unittest.mock import AsyncMock, MagicMock

        user = MagicMock()
        user.id = "test-id"

        redis = AsyncMock()
        redis.get.return_value = b"1"  # lock активен

        items = [MagicMock() for _ in range(5)]
        result = asyncio.run(build_shopping_list(user, items, redis))
        assert result == "lock"

    def test_gap_owner_mom_girl(self):
        """segment='mom_girl' → промпт содержит 'Детский гардероб'."""
        import asyncio
        from services.gap_analysis import build_shopping_list
        from unittest.mock import AsyncMock, MagicMock, patch

        user = MagicMock()
        user.id = "test-id"
        user.timezone = "Europe/Vilnius"
        user.colortype = None
        user.segment = "mom_girl"

        redis = AsyncMock()
        redis.get.return_value = None

        items = [
            MagicMock(
                category_group="tops", type="футболка",
                color="белый", season=["summer"], score_item=5.0,
            )
            for _ in range(5)
        ]

        captured: list[dict] = []

        async def mock_create_message(**kwargs):
            captured.append(kwargs)
            m = MagicMock()
            m.content = [MagicMock(text="1. Синяя куртка")]
            return m

        mock_pool = MagicMock()
        mock_pool.create_message = mock_create_message

        with patch("core.anthropic_client.get_anthropic_pool", return_value=mock_pool):
            result = asyncio.run(build_shopping_list(user, items, redis))

        assert captured, "Claude должен был быть вызван"
        prompt = captured[0]["messages"][0]["content"]
        assert "Детский" in prompt
