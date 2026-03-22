"""Tests for style quiz and typing indicators."""
import pytest
from pathlib import Path


class TestQuizPairs:
    """Verify quiz data integrity."""

    def test_10_pairs_defined(self):
        from bot.handlers.style_quiz import QUIZ_PAIRS
        assert len(QUIZ_PAIRS) == 10

    def test_pair_nums_sequential(self):
        from bot.handlers.style_quiz import QUIZ_PAIRS
        for i, pair in enumerate(QUIZ_PAIRS, 1):
            assert pair["num"] == i

    def test_all_axes_unique_per_pair(self):
        from bot.handlers.style_quiz import QUIZ_PAIRS
        for pair in QUIZ_PAIRS:
            assert pair["left_axis"] != pair["right_axis"]

    def test_all_images_exist(self):
        from bot.handlers.style_quiz import ASSETS_DIR
        for i in range(1, 11):
            assert (ASSETS_DIR / f"pair_{i:02d}_a.jpg").exists(), f"Missing pair_{i:02d}_a.jpg"
            assert (ASSETS_DIR / f"pair_{i:02d}_b.jpg").exists(), f"Missing pair_{i:02d}_b.jpg"


class TestQuizScoring:

    def test_elegant_classic(self):
        from bot.handlers.style_quiz import compute_style_type
        scores = {"classic": 1, "minimalist": 1, "timeless": 1, "structured": 1, "neutral": 1}
        assert compute_style_type(scores) == "elegant_classic"

    def test_street_casual(self):
        from bot.handlers.style_quiz import compute_style_type
        scores = {"edgy": 1, "athletic": 1, "oversized": 1, "bold": 1, "trendy": 1}
        assert compute_style_type(scores) == "street_casual"

    def test_romantic_soft(self):
        from bot.handlers.style_quiz import compute_style_type
        scores = {"romantic": 1, "feminine": 1, "flowy": 1, "warm": 1, "layered": 1}
        assert compute_style_type(scores) == "romantic_soft"

    def test_sporty_minimal(self):
        from bot.handlers.style_quiz import compute_style_type
        scores = {"sporty": 1, "minimalist": 1, "fitted": 1, "simple": 1, "cool": 1}
        assert compute_style_type(scores) == "sporty_minimal"

    def test_bold_creative(self):
        from bot.handlers.style_quiz import compute_style_type
        scores = {"maximalist": 1, "trendy": 1, "bold": 1, "edgy": 1, "layered": 1}
        assert compute_style_type(scores) == "bold_creative"

    def test_relaxed_natural(self):
        from bot.handlers.style_quiz import compute_style_type
        scores = {"athletic": 1, "neutral": 1, "warm": 1, "simple": 1, "flowy": 1}
        assert compute_style_type(scores) == "relaxed_natural"

    def test_all_types_reachable(self):
        """Each of the 6 style types can be achieved."""
        from bot.handlers.style_quiz import compute_style_type, STYLE_TYPES
        for type_name, type_info in STYLE_TYPES.items():
            scores = {axis: 2 for axis in type_info["axes"]}
            result = compute_style_type(scores)
            assert result == type_name, f"Expected {type_name}, got {result}"

    def test_empty_scores_returns_something(self):
        from bot.handlers.style_quiz import compute_style_type
        result = compute_style_type({})
        assert result in ("elegant_classic", "romantic_soft", "street_casual",
                         "sporty_minimal", "bold_creative", "relaxed_natural")


class TestQuizImage:

    def test_build_quiz_image_pair_01(self):
        from bot.handlers.style_quiz import build_quiz_image
        img_bytes = build_quiz_image(1)
        assert img_bytes[:2] == b"\xff\xd8"  # JPEG magic
        assert len(img_bytes) > 1000  # not empty

    def test_image_dimensions(self):
        from bot.handlers.style_quiz import build_quiz_image
        from PIL import Image
        import io
        img_bytes = build_quiz_image(1)
        img = Image.open(io.BytesIO(img_bytes))
        assert img.size == (440, 280)


class TestCallbackParse:

    def test_quiz_callback_left(self):
        data = "quiz:3:left"
        parts = data.split(":")
        assert parts[0] == "quiz"
        assert int(parts[1]) == 3
        assert parts[2] == "left"

    def test_quiz_callback_right(self):
        data = "quiz:7:right"
        parts = data.split(":")
        assert int(parts[1]) == 7
        assert parts[2] == "right"


class TestStyleTypes:

    def test_all_types_have_required_fields(self):
        from bot.handlers.style_quiz import STYLE_TYPES
        for name, info in STYLE_TYPES.items():
            assert "axes" in info, f"{name} missing axes"
            assert "label" in info, f"{name} missing label"
            assert "desc" in info, f"{name} missing desc"
            assert "tone_words" in info, f"{name} missing tone_words"
            assert "palette" in info, f"{name} missing palette"
            assert len(info["palette"]) == 4, f"{name} palette should have 4 colors"
            assert len(info["axes"]) == 5, f"{name} should have 5 axes"


class TestStyleInPrompts:

    def test_outfit_engine_uses_style_type(self):
        """outfit_engine should have style_type handling in _build_user_prompt."""
        with open("services/outfit_engine.py") as f:
            source = f.read()
        assert "style_type" in source
        assert "elegant_classic" in source

    def test_text_handler_uses_style_type(self):
        """text.py should reference style_type for system prompt."""
        with open("bot/handlers/text.py") as f:
            source = f.read()
        assert "style_type" in source

    def test_wardrobe_passes_style_preferences(self):
        """wardrobe.py should pass style_preferences to select_outfit_ai."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert "style_preferences=" in source


class TestTypingIndicators:

    def test_text_handler_has_typing(self):
        with open("bot/handlers/text.py") as f:
            source = f.read()
        assert "send_chat_action" in source

    def test_reroll_has_typing(self):
        with open("bot/handlers/brief.py") as f:
            source = f.read()
        assert "send_chat_action" in source

    def test_rate_photos_has_typing(self):
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        # Should appear in _rate_photos function
        assert 'send_chat_action(message.chat_id, "typing")' in source


class TestQuizCaption:

    def test_caption_normal(self):
        from bot.handlers.style_quiz import _quiz_caption
        assert "(3/10)" in _quiz_caption(3)
        assert "Почти" not in _quiz_caption(3)

    def test_caption_almost_done(self):
        from bot.handlers.style_quiz import _quiz_caption
        assert "Почти" in _quiz_caption(7)
        assert "(7/10" in _quiz_caption(7)
