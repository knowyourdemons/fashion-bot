"""Tests: Kassi positive framing across ALL text outputs.

Checks fallback templates, WOW phrases, milestone texts, CTA texts —
everything the user can see from Kassi must be positive.
"""
import pytest

FORBIDDEN_WORDS = [
    "критически", "обязательно", "срочно", "не хватает",
    "нужно", "должна", "нельзя", "плохо", "ужасно",
]


def _check_no_forbidden(texts: list[str], source: str):
    """Assert none of the texts contain forbidden words."""
    for text in texts:
        lower = text.lower()
        for word in FORBIDDEN_WORDS:
            assert word not in lower, (
                f"'{word}' found in {source}: '{text[:80]}...'"
            )


class TestFallbackTemplates:
    """scoring_comment.py fallback templates must be positive."""

    def test_mom_templates_positive(self):
        from services.scoring_comment import _TEMPLATES_MOM
        _check_no_forbidden(_TEMPLATES_MOM, "_TEMPLATES_MOM")

    def test_no_kids_templates_positive(self):
        from services.scoring_comment import _TEMPLATES_NO_KIDS
        _check_no_forbidden(_TEMPLATES_NO_KIDS, "_TEMPLATES_NO_KIDS")

    def test_mom_templates_count(self):
        from services.scoring_comment import _TEMPLATES_MOM
        assert len(_TEMPLATES_MOM) >= 10, "Need variety in fallback templates"

    def test_no_kids_templates_count(self):
        from services.scoring_comment import _TEMPLATES_NO_KIDS
        assert len(_TEMPLATES_NO_KIDS) >= 10


class TestWowPhrases:
    """WOW_PHRASES in style_config must be enthusiastic, no forbidden words."""

    def test_wow_phrases_positive(self):
        from worker.tasks.style_config import WOW_PHRASES
        _check_no_forbidden(WOW_PHRASES, "WOW_PHRASES")

    def test_wow_phrases_have_emoji(self):
        from worker.tasks.style_config import WOW_PHRASES
        for phrase in WOW_PHRASES:
            # At least one non-ASCII character (emoji)
            has_emoji = any(ord(c) > 127 for c in phrase)
            assert has_emoji, f"WOW phrase missing emoji: '{phrase}'"

    def test_wow_phrases_count(self):
        from worker.tasks.style_config import WOW_PHRASES
        assert len(WOW_PHRASES) >= 8, "Need variety in WOW phrases"


class TestMilestoneTexts:
    """Milestone messages in wardrobe.py must be encouraging."""

    def test_milestone_texts_in_source(self):
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        # All milestone messages should use positive language
        milestone_markers = [
            "Мини-образ разблокирован",
            "Гардероб собран",
            "классная база",
        ]
        for marker in milestone_markers:
            assert marker in source, f"Expected milestone text '{marker}' in wardrobe.py"

    def test_no_forbidden_in_milestones(self):
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        # Extract lines containing milestone emoji
        lines = [l.strip() for l in source.split("\n") if "🎉" in l and '"' in l]
        texts = []
        for line in lines:
            # Extract quoted strings
            import re
            strings = re.findall(r'"([^"]*🎉[^"]*)"', line) or re.findall(r'"([^"]+)"', line)
            texts.extend(strings)
        if texts:
            _check_no_forbidden(texts, "milestone texts")


class TestSuggestNextItem:
    """CTA suggestions after adding items must be encouraging, not demanding."""

    def test_cta_uses_positive_language(self):
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        # "Сфоткай" is a soft imperative (OK)
        # "нужно сфоткать" would be bad
        assert "нужно сфоткать" not in source
        assert "обязательно сфоткай" not in source


class TestKassiSystemPromptCompleteness:
    """All Kassi-facing system prompts must have the full positive framing block."""

    @pytest.mark.parametrize("file_path,marker", [
        ("services/outfit_engine.py", "ЗАПРЕЩЁННЫЕ слова"),
        ("services/scoring_comment.py", "ЗАПРЕЩЁННЫЕ слова"),
        ("bot/handlers/text.py", "ЗАПРЕЩЁННЫЕ слова"),
    ])
    def test_has_forbidden_list(self, file_path, marker):
        with open(file_path) as f:
            source = f.read()
        assert marker in source, f"{file_path} missing forbidden words list"

    @pytest.mark.parametrize("file_path", [
        "services/outfit_engine.py",
        "services/scoring_comment.py",
        "bot/handlers/text.py",
    ])
    def test_has_positive_alternatives(self, file_path):
        with open(file_path) as f:
            source = f.read()
        assert "попробуй" in source, f"{file_path} missing positive alternative 'попробуй'"
