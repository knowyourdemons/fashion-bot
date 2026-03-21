"""Onboarding flow — simplified 3-step flow tests."""
import pathlib
import pytest


class TestOnboardingStates:
    """Onboarding states and handlers are properly defined."""

    def test_states_defined(self):
        from bot.handlers.onboarding import (
            WELCOME, WHO_FOR, CHILD_GENDER, CHILD_NAME,
            CHILD_BIRTHDATE, CITY, CITY_SUGGEST, RESUME_CONFIRM,
            PREGNANT_TRIMESTER,
        )
        # All states are unique integers
        states = [WELCOME, WHO_FOR, CHILD_GENDER, CHILD_NAME,
                  CHILD_BIRTHDATE, CITY, CITY_SUGGEST, RESUME_CONFIRM,
                  PREGNANT_TRIMESTER]
        assert len(states) == len(set(states)), "States must be unique"
        assert all(isinstance(s, int) for s in states)

    def test_step_to_state_mapping(self):
        from bot.handlers.onboarding import (
            _STEP_TO_STATE, WHO_FOR, CHILD_GENDER, CHILD_NAME,
            CHILD_AGE, SELF_NAME, CITY,
        )
        assert _STEP_TO_STATE["segment"] == WHO_FOR
        assert _STEP_TO_STATE["child_gender"] == CHILD_GENDER
        assert _STEP_TO_STATE["child_name"] == CHILD_NAME
        assert _STEP_TO_STATE["child_age"] == CHILD_AGE
        assert _STEP_TO_STATE["child_birthdate"] == CHILD_AGE  # legacy mapping
        assert _STEP_TO_STATE["self_name"] == SELF_NAME
        assert _STEP_TO_STATE["city"] == CITY
        assert _STEP_TO_STATE["pregnant_trimester"] == CITY  # legacy: skip to city

    def test_no_old_states(self):
        """Old states (size, shoe, colortype, selfie) must not exist."""
        import bot.handlers.onboarding as ob
        for attr in ("CHILD_SIZE", "CHILD_SHOE_SIZE", "ASK_COLORTYPE", "SELFIE_COLORTYPE"):
            assert not hasattr(ob, attr), f"{attr} should be removed"

    def test_handler_functions_exist(self):
        from bot.handlers.onboarding import (
            handle_start, handle_welcome, handle_who_for,
            handle_child_gender, handle_child_name,
            handle_child_birthdate, handle_city_location,
            handle_city_text, handle_city_suggest,
            handle_resume_confirm, handle_cancel,
            handle_pregnant_trimester,
        )
        assert all(callable(fn) for fn in [
            handle_start, handle_welcome, handle_who_for,
            handle_child_gender, handle_child_name,
            handle_child_birthdate, handle_city_location,
            handle_city_text, handle_city_suggest,
            handle_resume_confirm, handle_cancel,
            handle_pregnant_trimester,
        ])

    def test_helper_functions_preserved(self):
        from bot.handlers.onboarding import (
            _reverse_geocode, _nominatim_search, _extract_city_tz,
            parse_birthdate, _save_user_fields, progress_bar,
        )
        assert callable(_reverse_geocode)
        assert callable(_nominatim_search)
        assert callable(_extract_city_tz)
        assert callable(parse_birthdate)
        assert callable(_save_user_fields)
        assert callable(progress_bar)

    def test_progress_bar_total_3(self):
        from bot.handlers.onboarding import progress_bar
        bar = progress_bar(1)
        assert bar.count("🟪") == 1
        assert bar.count("⬜") == 2  # total=3 by default

    def test_pregnant_trimester_state_in_conversation(self):
        """PREGNANT_TRIMESTER must be in ConversationHandler states."""
        content = pathlib.Path("bot/handlers/onboarding.py").read_text()
        assert "PREGNANT_TRIMESTER:" in content
        assert 'pattern="^trimester:"' in content

    def test_who_for_handles_pregnant(self):
        """WHO_FOR handler must handle pregnant choice (backward compat)."""
        content = pathlib.Path("bot/handlers/onboarding.py").read_text()
        assert '"pregnant"' in content  # handler still processes pregnant choice

    def test_city_transitions_to_finish(self):
        """City handlers should go to _finish_onboarding, not selfie/colortype."""
        content = pathlib.Path("bot/handlers/onboarding.py").read_text()
        for fn in ["handle_city_location", "handle_city_text", "handle_city_suggest"]:
            start = content.find(f"async def {fn}")
            end = content.find("\nasync def ", start + 1)
            fn_body = content[start:end] if end > start else content[start:start + 500]
            assert "_finish_onboarding" in fn_body, \
                f"{fn} should call _finish_onboarding"
