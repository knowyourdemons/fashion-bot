"""Selfie colortype detection — onboarding integration."""
import pathlib
import pytest


class TestSelfieColortypeOnboarding:
    """Selfie colortype step is properly wired into onboarding flow."""

    def test_state_exists(self):
        from bot.handlers.onboarding import SELFIE_COLORTYPE
        assert isinstance(SELFIE_COLORTYPE, int)

    def test_step_to_state_mapping(self):
        from bot.handlers.onboarding import _STEP_TO_STATE, SELFIE_COLORTYPE
        assert _STEP_TO_STATE["selfie_colortype"] == SELFIE_COLORTYPE

    def test_handler_functions_exist(self):
        from bot.handlers.onboarding import handle_selfie_colortype, handle_selfie_skip
        assert callable(handle_selfie_colortype)
        assert callable(handle_selfie_skip)

    def test_selfie_prompt_exists(self):
        from bot.handlers.onboarding import _ask_selfie_colortype
        assert callable(_ask_selfie_colortype)

    def test_vision_prompt_defined(self):
        from bot.handlers.onboarding import _COLORTYPE_VISION_PROMPT
        assert "Весна" in _COLORTYPE_VISION_PROMPT
        assert "Лето" in _COLORTYPE_VISION_PROMPT
        assert "Осень" in _COLORTYPE_VISION_PROMPT
        assert "Зима" in _COLORTYPE_VISION_PROMPT

    def test_skip_keyboard_defined(self):
        from bot.handlers.onboarding import _SELFIE_SKIP_KEYBOARD
        assert _SELFIE_SKIP_KEYBOARD is not None

    def test_city_transitions_to_selfie(self):
        """All city→next transitions should go to selfie_colortype, not colortype."""
        content = pathlib.Path("bot/handlers/onboarding.py").read_text()
        # Find handle_city_location, handle_city_text, handle_city_suggest
        # They should save onboarding_step="selfie_colortype"
        for fn in ["handle_city_location", "handle_city_text", "handle_city_suggest"]:
            start = content.find(f"async def {fn}")
            end = content.find("\nasync def ", start + 1)
            fn_body = content[start:end] if end > start else content[start:start+500]
            assert 'onboarding_step="selfie_colortype"' in fn_body, \
                f"{fn} should transition to selfie_colortype"

    def test_conversation_handler_includes_selfie_state(self):
        """SELFIE_COLORTYPE must be in ConversationHandler states."""
        content = pathlib.Path("bot/handlers/onboarding.py").read_text()
        assert "SELFIE_COLORTYPE:" in content
        assert "filters.PHOTO, handle_selfie_colortype" in content

    def test_resume_handles_selfie_step(self):
        """_resume_step must handle selfie_colortype."""
        content = pathlib.Path("bot/handlers/onboarding.py").read_text()
        fn_start = content.find("async def _resume_step")
        fn_end = content.find("\nasync def ", fn_start + 1)
        fn_body = content[fn_start:fn_end] if fn_end > fn_start else content[fn_start:]
        assert '"selfie_colortype"' in fn_body

    def test_colortype_values_are_russian(self):
        """Detected colortype should be Russian: Весна/Лето/Осень/Зима."""
        content = pathlib.Path("bot/handlers/onboarding.py").read_text()
        start = content.find("async def handle_selfie_colortype")
        fn = content[start:start+1500]
        for ct in ["Весна", "Лето", "Осень", "Зима"]:
            assert ct in fn
