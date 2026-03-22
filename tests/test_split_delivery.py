"""Tests for split delivery (photo + text as separate messages) and Kassi tone."""
import pytest


# ── Split delivery: templates should NOT contain kassi/base_layer ──────────

class TestTemplatesClean:
    """Verify kassi_comment and base_layer blocks removed from templates."""

    TEMPLATES = [
        "renderer/templates/tpl_hybrid.html",
        "renderer/templates/tpl_full.html",
        "renderer/templates/tpl_morning.html",
        "renderer/templates/tpl_weather.html",
    ]

    @pytest.mark.parametrize("path", TEMPLATES)
    def test_no_kassi_block(self, path):
        with open(path) as f:
            html = f.read()
        assert 'class="kassi"' not in html, f"{path} still contains kassi block"
        assert "kassi-t" not in html, f"{path} still contains kassi-t class"

    @pytest.mark.parametrize("path", [
        "renderer/templates/tpl_hybrid.html",
        "renderer/templates/tpl_full.html",
    ])
    def test_no_base_layer_block(self, path):
        with open(path) as f:
            html = f.read()
        assert 'class="base"' not in html, f"{path} still contains base_layer block"

    @pytest.mark.parametrize("path", TEMPLATES)
    def test_still_has_header(self, path):
        """Templates should still have header with name/date/weather."""
        with open(path) as f:
            html = f.read()
        assert "hdr" in html, f"{path} missing header"
        assert "{{ name }}" in html, f"{path} missing name variable"

    def test_hybrid_still_has_progress(self):
        with open("renderer/templates/tpl_hybrid.html") as f:
            html = f.read()
        assert "progress_pct" in html, "hybrid template missing progress bar"

    def test_hybrid_still_has_missing(self):
        with open("renderer/templates/tpl_hybrid.html") as f:
            html = f.read()
        assert "missing" in html, "hybrid template missing 'missing items' section"

    def test_hybrid_still_has_palette(self):
        with open("renderer/templates/tpl_hybrid.html") as f:
            html = f.read()
        assert "palette" in html, "hybrid template missing palette dots"


# ── Kassi tone: system prompts should NOT contain forbidden words ──────────

FORBIDDEN_WORDS = ["критически", "обязательно", "срочно"]


class TestKassiTone:
    """Verify Kassi prompts use positive framing."""

    def test_outfit_engine_mom_has_forbidden_list(self):
        """Prompt should LIST forbidden words (as a rule), not USE them."""
        from services.outfit_engine import _SYSTEM_MOM_BASE
        assert "ЗАПРЕЩЁННЫЕ слова" in _SYSTEM_MOM_BASE

    def test_outfit_engine_woman_has_forbidden_list(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        assert "ЗАПРЕЩЁННЫЕ слова" in _SYSTEM_WOMAN

    def test_outfit_engine_mom_has_positive(self):
        from services.outfit_engine import _SYSTEM_MOM_BASE
        assert "попробуй" in _SYSTEM_MOM_BASE.lower() or "добавь" in _SYSTEM_MOM_BASE.lower()

    def test_outfit_engine_woman_has_positive(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        assert "попробуй" in _SYSTEM_WOMAN.lower() or "добавь" in _SYSTEM_WOMAN.lower()

    def test_outfit_engine_mom_max_2_sentences(self):
        from services.outfit_engine import _SYSTEM_MOM_BASE
        assert "2 предложения" in _SYSTEM_MOM_BASE or "1-2 предложения" in _SYSTEM_MOM_BASE

    def test_outfit_engine_woman_max_2_sentences(self):
        from services.outfit_engine import _SYSTEM_WOMAN
        assert "2 предложения" in _SYSTEM_WOMAN or "1-2 предложения" in _SYSTEM_WOMAN

    def test_kassi_is_podruga(self):
        """Kassi should be 'подруга-стилист' not just 'стилист'."""
        from services.outfit_engine import _SYSTEM_MOM_BASE, _SYSTEM_WOMAN
        assert "подруга" in _SYSTEM_MOM_BASE.lower()
        assert "подруга" in _SYSTEM_WOMAN.lower()

    def test_outfit_engine_max_tokens_limited(self):
        """Max tokens for outfit engine should be <= 300."""
        import ast
        with open("services/outfit_engine.py") as f:
            source = f.read()
        # Find max_tokens value
        assert "max_tokens=300" in source or "max_tokens=250" in source

    def test_scoring_comment_max_tokens_limited(self):
        """Max tokens for scoring comment should be <= 150."""
        with open("services/scoring_comment.py") as f:
            source = f.read()
        assert "max_tokens=150" in source


class TestTextHandlerTone:
    """Verify text handler (chat) uses positive tone."""

    def test_text_system_has_forbidden_words_list(self):
        with open("bot/handlers/text.py") as f:
            source = f.read()
        assert "ЗАПРЕЩЁННЫЕ слова" in source

    def test_text_system_has_positive_alternatives(self):
        with open("bot/handlers/text.py") as f:
            source = f.read()
        assert "попробуй" in source
        assert "будет здорово" in source
