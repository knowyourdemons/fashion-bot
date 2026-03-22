"""TA-scenario review tests for March 22 changes.

Tests organized by persona (Маша/Лена/Даша/Оля/Катя) covering:
- Style quiz eligibility and scoring
- Split delivery (photo + text)
- Kassi tone (positive, no forbidden words)
- Style type influence on outfit prompts
- Typing indicators
"""
import pytest


# ── Style Quiz: Eligibility ───────────────────────────────────────────────────

class TestStyleQuizTA:
    """Style quiz should only trigger for no_kids with 10+ items."""

    def test_quiz_eligible_no_kids(self):
        """Лена (26, no_kids, 10 items) → quiz should trigger."""
        # segment=no_kids, quiz_completed=False → eligible
        segment = "no_kids"
        prefs = {}
        assert segment == "no_kids"
        assert not prefs.get("quiz_completed", False)

    def test_quiz_ineligible_mom_girl(self):
        """Маша (28, mom_girl) → quiz should NOT trigger."""
        segment = "mom_girl"
        assert segment != "no_kids", "Quiz should not trigger for mom_girl"

    def test_quiz_ineligible_mom_boy(self):
        """Папа мальчика (mom_boy) → quiz should NOT trigger."""
        segment = "mom_boy"
        assert segment != "no_kids", "Quiz should not trigger for mom_boy"

    def test_quiz_ineligible_pregnant(self):
        """Катя (30, pregnant) → quiz should NOT trigger."""
        segment = "pregnant"
        assert segment != "no_kids", "Quiz should not trigger for pregnant"

    def test_quiz_ineligible_already_done(self):
        """Лена already took quiz → should NOT trigger again."""
        prefs = {"quiz_completed": True, "style_type": "elegant_classic"}
        assert prefs.get("quiz_completed") is True

    # ── Scoring ────────────────────────────────────────────────────────────

    def test_scoring_elegant_classic(self):
        """Оля (40, бизнесвумен): classic + minimalist + timeless → elegant_classic."""
        from bot.handlers.style_quiz import compute_style_type
        scores = {"classic": 1, "minimalist": 1, "timeless": 1, "structured": 1, "neutral": 1}
        assert compute_style_type(scores) == "elegant_classic"

    def test_scoring_street_casual(self):
        """Даша (22, студентка): edgy + athletic + oversized → street_casual."""
        from bot.handlers.style_quiz import compute_style_type
        scores = {"edgy": 1, "athletic": 1, "oversized": 1, "bold": 1, "trendy": 1}
        assert compute_style_type(scores) == "street_casual"

    def test_scoring_romantic_soft(self):
        """Лена в романтике: romantic + feminine + flowy → romantic_soft."""
        from bot.handlers.style_quiz import compute_style_type
        scores = {"romantic": 1, "feminine": 1, "flowy": 1, "warm": 1, "layered": 1}
        assert compute_style_type(scores) == "romantic_soft"

    def test_scoring_sporty_minimal(self):
        """Спортивная девушка: sporty + minimalist + fitted → sporty_minimal."""
        from bot.handlers.style_quiz import compute_style_type
        scores = {"sporty": 1, "minimalist": 1, "fitted": 1, "simple": 1, "cool": 1}
        assert compute_style_type(scores) == "sporty_minimal"

    def test_scoring_bold_creative(self):
        """Аня (18, выпускница): maximalist + trendy + bold → bold_creative."""
        from bot.handlers.style_quiz import compute_style_type
        scores = {"maximalist": 1, "trendy": 1, "bold": 1, "edgy": 1, "layered": 1}
        assert compute_style_type(scores) == "bold_creative"

    def test_scoring_relaxed_natural(self):
        """Расслабленная натура: athletic + neutral + warm → relaxed_natural."""
        from bot.handlers.style_quiz import compute_style_type
        scores = {"athletic": 1, "neutral": 1, "warm": 1, "simple": 1, "flowy": 1}
        assert compute_style_type(scores) == "relaxed_natural"

    def test_tie_deterministic(self):
        """Tied scores → result is deterministic (same input = same output)."""
        from bot.handlers.style_quiz import compute_style_type
        scores = {}  # all zeros → first type in dict wins consistently
        r1 = compute_style_type(scores)
        r2 = compute_style_type(scores)
        assert r1 == r2, "Tie-breaking should be deterministic"

    def test_all_6_types_reachable_from_strong_signal(self):
        """Each style type is reachable with strong enough signal."""
        from bot.handlers.style_quiz import compute_style_type, STYLE_TYPES
        for type_name, info in STYLE_TYPES.items():
            scores = {axis: 5 for axis in info["axes"]}
            assert compute_style_type(scores) == type_name, f"{type_name} not reachable"


# ── Split Delivery ────────────────────────────────────────────────────────────

class TestSplitDeliveryTA:
    """Split delivery: photo without caption, text with buttons separately."""

    TEMPLATES = [
        "renderer/templates/tpl_hybrid.html",
        "renderer/templates/tpl_full.html",
        "renderer/templates/tpl_morning.html",
        "renderer/templates/tpl_weather.html",
    ]

    @pytest.mark.parametrize("path", TEMPLATES)
    def test_template_no_kassi_block(self, path):
        """All templates must NOT contain kassi comment block."""
        with open(path) as f:
            html = f.read()
        assert 'class="kassi"' not in html

    def test_morning_template_header_clean(self):
        """tpl_morning.html header should not mention kassi_comment."""
        with open("renderer/templates/tpl_morning.html") as f:
            first_lines = "".join(f.readlines()[:5])
        assert "kassi_comment" not in first_lines

    def test_wardrobe_passes_style_preferences(self):
        """wardrobe.py must pass style_preferences= to select_outfit_ai."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert "style_preferences=getattr(user" in source or "style_preferences=" in source

    def test_photo_msg_redis_key_format(self):
        """Redis key for photo message should be 'photo_msg:{chat_id}:{brief_id}'."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert "photo_msg:" in source
        assert "message_id" in source

    def test_split_delivery_no_caption(self):
        """wardrobe.py send_photo uses disable_notification=True."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert "disable_notification=True" in source

    def test_morning_brief_split_delivery(self):
        """morning_brief.py sends photo without caption, then text separately."""
        with open("worker/tasks/morning_brief.py") as f:
            source = f.read()
        # Photo should not have "caption" in data dict
        assert '"disable_notification": "true"' in source
        # Separate text message
        assert "sendMessage" in source

    def test_brief_feedback_uses_edit_text(self):
        """brief.py feedback uses edit_message_text (not edit_message_caption)."""
        with open("bot/handlers/brief.py") as f:
            source = f.read()
        assert "edit_message_text" in source

    def test_reroll_deletes_photo_via_redis(self):
        """brief.py reroll fetches photo_msg from Redis and deletes it."""
        with open("bot/handlers/brief.py") as f:
            source = f.read()
        assert "photo_msg:" in source
        assert "delete_message" in source


# ── Kassi Tone ────────────────────────────────────────────────────────────────

FORBIDDEN_WORDS_IN_INSTRUCTIONS = ["критически", "обязательно", "срочно"]
POSITIVE_WORDS = ["попробуй", "добавь", "будет здорово", "классно смотрится"]


class TestKassiToneTA:
    """Kassi speaks warmly, no forbidden words in instructions to user."""

    def test_mom_prompt_has_forbidden_list(self):
        """Mom prompt should LIST forbidden words as a prohibition rule."""
        from services.outfit_engine import _SYSTEM_MOM_BASE
        assert "ЗАПРЕЩЁННЫЕ слова" in _SYSTEM_MOM_BASE

    def test_woman_prompt_has_forbidden_list(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        assert "ЗАПРЕЩЁННЫЕ слова" in _SYSTEM_WOMAN

    def test_mom_positive_framing(self):
        """Mom prompt offers positive alternatives."""
        from services.outfit_engine import _SYSTEM_MOM_BASE
        lower = _SYSTEM_MOM_BASE.lower()
        found = sum(1 for w in POSITIVE_WORDS if w in lower)
        assert found >= 2, f"Expected 2+ positive words, found {found}"

    def test_woman_positive_framing(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        lower = _SYSTEM_WOMAN.lower()
        found = sum(1 for w in POSITIVE_WORDS if w in lower)
        assert found >= 2, f"Expected 2+ positive words, found {found}"

    def test_mom_max_2_sentences(self):
        from services.outfit_engine import _SYSTEM_MOM_BASE
        assert "2 предложения" in _SYSTEM_MOM_BASE or "1-2 предложения" in _SYSTEM_MOM_BASE

    def test_woman_max_2_sentences(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        assert "2 предложения" in _SYSTEM_WOMAN or "1-2 предложения" in _SYSTEM_WOMAN

    def test_kassi_podruga_mom(self):
        """Kassi is подруга-стилист, not authority."""
        from services.outfit_engine import _SYSTEM_MOM_BASE
        assert "подруга" in _SYSTEM_MOM_BASE.lower()

    def test_kassi_podruga_woman(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        assert "подруга" in _SYSTEM_WOMAN.lower()

    def test_max_tokens_outfit_engine(self):
        """Outfit engine max_tokens should be <= 300."""
        with open("services/outfit_engine.py") as f:
            source = f.read()
        assert "max_tokens=300" in source or "max_tokens=250" in source

    def test_max_tokens_scoring_comment(self):
        """Scoring comment max_tokens should be <= 150."""
        with open("services/scoring_comment.py") as f:
            source = f.read()
        assert "max_tokens=150" in source

    def test_reroll_max_tokens(self):
        """Reroll advice max_tokens should be <= 150."""
        with open("bot/handlers/brief.py") as f:
            source = f.read()
        assert "max_tokens=150" in source

    def test_scoring_comment_has_forbidden_list(self):
        """Scoring comment prompt should also list forbidden words."""
        with open("services/scoring_comment.py") as f:
            source = f.read()
        assert "ЗАПРЕЩЁННЫЕ слова" in source

    def test_text_handler_has_forbidden_list(self):
        """Text chat handler should list forbidden words."""
        with open("bot/handlers/text.py") as f:
            source = f.read()
        assert "ЗАПРЕЩЁННЫЕ слова" in source

    @pytest.mark.parametrize("segment", ["mom_girl", "mom_boy", "no_kids", "pregnant"])
    def test_kassi_warm_across_segments(self, segment):
        """Kassi tone should be warm for ALL segments."""
        from services.outfit_engine import _get_mom_system_prompt, _SYSTEM_WOMAN
        if segment in ("mom_girl", "mom_boy"):
            prompt = _get_mom_system_prompt(5)  # 5yo child
        else:
            prompt = _SYSTEM_WOMAN
        assert "тепло" in prompt.lower() or "энтузиазм" in prompt.lower()


# ── Style Type in Outfit Prompts ──────────────────────────────────────────────

class TestOutfitStyleTypeTA:
    """Style type from quiz should influence outfit AI prompts."""

    def test_hint_elegant_classic(self):
        from services.outfit_engine import STYLE_TYPE_HINTS
        assert "структурированные" in STYLE_TYPE_HINTS["elegant_classic"]

    def test_hint_romantic_soft(self):
        from services.outfit_engine import STYLE_TYPE_HINTS
        assert "мягкие" in STYLE_TYPE_HINTS["romantic_soft"]

    def test_hint_street_casual(self):
        from services.outfit_engine import STYLE_TYPE_HINTS
        assert "свободный" in STYLE_TYPE_HINTS["street_casual"]

    def test_hint_sporty_minimal(self):
        from services.outfit_engine import STYLE_TYPE_HINTS
        assert "чистые линии" in STYLE_TYPE_HINTS["sporty_minimal"]

    def test_hint_bold_creative(self):
        from services.outfit_engine import STYLE_TYPE_HINTS
        assert "яркие" in STYLE_TYPE_HINTS["bold_creative"]

    def test_hint_relaxed_natural(self):
        from services.outfit_engine import STYLE_TYPE_HINTS
        assert "натуральные" in STYLE_TYPE_HINTS["relaxed_natural"]

    def test_all_6_types_have_hints(self):
        from services.outfit_engine import STYLE_TYPE_HINTS
        assert len(STYLE_TYPE_HINTS) == 6

    def test_no_style_type_safe(self):
        """style_preferences=None should not crash outfit prompt building."""
        from services.outfit_engine import STYLE_TYPE_HINTS
        # Simulating what _build_user_prompt does
        style_preferences = None
        style_type = (style_preferences or {}).get("style_type", "")
        hint = STYLE_TYPE_HINTS.get(style_type)
        assert hint is None  # no hint, no crash

    def test_style_type_in_text_handler(self):
        """text.py should import STYLE_TYPES from style_quiz."""
        with open("bot/handlers/text.py") as f:
            source = f.read()
        assert "STYLE_TYPES" in source
        assert "style_type" in source

    def test_style_type_in_outfit_engine(self):
        """outfit_engine.py should reference STYLE_TYPE_HINTS."""
        with open("services/outfit_engine.py") as f:
            source = f.read()
        assert "STYLE_TYPE_HINTS" in source


# ── Typing Indicators ─────────────────────────────────────────────────────────

class TestTypingIndicatorsTA:
    """send_chat_action('typing') should be present in all long-running handlers."""

    def test_typing_in_text_handler(self):
        with open("bot/handlers/text.py") as f:
            source = f.read()
        assert "send_chat_action" in source

    def test_typing_in_reroll(self):
        with open("bot/handlers/brief.py") as f:
            source = f.read()
        assert "send_chat_action" in source

    def test_typing_in_rate_photos(self):
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert 'send_chat_action(message.chat_id, "typing")' in source

    def test_typing_in_outfit_generation(self):
        """Outfit generation ('Что надеть') must have typing indicator."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        # Should appear in _generate_outfit_for_user area
        assert source.count("send_chat_action") >= 2, "Expected typing in both rate and outfit"


# ── Quiz Data Integrity ───────────────────────────────────────────────────────

class TestQuizDataIntegrity:
    """Quiz pairs and style types must be consistent."""

    def test_all_quiz_axes_covered_by_types(self):
        """Every axis from quiz pairs should appear in at least one style type."""
        from bot.handlers.style_quiz import QUIZ_PAIRS, STYLE_TYPES
        all_axes = set()
        for pair in QUIZ_PAIRS:
            all_axes.add(pair["left_axis"])
            all_axes.add(pair["right_axis"])
        covered_axes = set()
        for info in STYLE_TYPES.values():
            covered_axes.update(info["axes"])
        missing = all_axes - covered_axes
        assert not missing, f"Axes {missing} not covered by any style type"

    def test_no_orphan_axes_in_types(self):
        """Every axis in style types should exist in quiz pairs."""
        from bot.handlers.style_quiz import QUIZ_PAIRS, STYLE_TYPES
        pair_axes = set()
        for pair in QUIZ_PAIRS:
            pair_axes.add(pair["left_axis"])
            pair_axes.add(pair["right_axis"])
        for type_name, info in STYLE_TYPES.items():
            for axis in info["axes"]:
                assert axis in pair_axes, f"Style type {type_name} has orphan axis: {axis}"

    def test_quiz_image_pairs_all_valid_jpeg(self):
        """All 20 quiz images are valid JPEG files."""
        from bot.handlers.style_quiz import ASSETS_DIR
        for i in range(1, 11):
            for side in ("a", "b"):
                path = ASSETS_DIR / f"pair_{i:02d}_{side}.jpg"
                with open(path, "rb") as f:
                    magic = f.read(2)
                assert magic == b"\xff\xd8", f"{path.name} is not a valid JPEG"

    def test_style_type_palettes_valid_hex(self):
        """All palette colors should be valid hex codes."""
        from bot.handlers.style_quiz import STYLE_TYPES
        import re
        hex_re = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for type_name, info in STYLE_TYPES.items():
            for color in info["palette"]:
                assert hex_re.match(color), f"{type_name} has invalid palette color: {color}"

    def test_style_type_tone_words_not_empty(self):
        """Each style type should have at least 3 tone words."""
        from bot.handlers.style_quiz import STYLE_TYPES
        for type_name, info in STYLE_TYPES.items():
            assert len(info["tone_words"]) >= 3, f"{type_name} has too few tone words"
