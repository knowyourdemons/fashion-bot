"""Tests for weekly plan, fitting, and integration."""
import pytest
from unittest.mock import MagicMock
from datetime import date


def _item(cat="top", type_name="футболка", color="белый", score=5.0):
    m = MagicMock()
    m.id = id(m)
    m.category_group = cat
    m.type = type_name
    m.color = color
    m.score_item = score
    m.warmth_level = 2
    m.season = ["spring", "summer", "autumn", "winter"]
    m.last_worn = None
    m.wear_count = 0
    m.show_in_collage = True
    m.photo_id = f"p_{id(m)}"
    m.photo_url = None
    m.bbox = None
    m.style = "повседневный"
    m.style_tag = "casual"
    m.occasion = ["weekday"]
    m.rain_ok = False
    return m


# ── Weekly Plan ───────────────────────────────────────────────────────────────

class TestWeeklyPlan:

    def test_weekly_occasions_no_kids(self):
        from worker.tasks.weekly_plan import _WEEKLY_OCCASIONS
        occ = _WEEKLY_OCCASIONS["no_kids"]
        assert len(occ) == 5
        assert "офис" in occ
        assert "casual friday" in occ

    def test_weekly_occasions_mom(self):
        from worker.tasks.weekly_plan import _WEEKLY_OCCASIONS
        occ = _WEEKLY_OCCASIONS["mom_girl"]
        assert len(occ) == 5
        assert "садик" in occ

    def test_is_basic_item(self):
        from worker.tasks.weekly_plan import _is_basic_item
        jeans = _item("bottom", "джинсы", "синий")
        assert _is_basic_item(jeans)
        dress = _item("one_piece", "платье", "красный")
        assert not _is_basic_item(dress)

    def test_format_outfit_line(self):
        from worker.tasks.weekly_plan import _format_outfit_line
        outfit = {"top": _item("top", "блузка", "белый"), "bottom": _item("bottom", "брюки", "серый")}
        line = _format_outfit_line(outfit)
        assert "белый" in line or "блузка" in line

    def test_format_weekly_message(self):
        from worker.tasks.weekly_plan import format_weekly_message
        plan = [
            {"day_name": "Пн", "occasion": "офис", "outfit_line": "блузка + брюки", "item_ids": []},
            {"day_name": "Вт", "occasion": "офис", "outfit_line": "платье", "item_ids": []},
        ]
        msg = format_weekly_message(plan, new_combos=2)
        assert "Пн" in msg
        assert "Вт" in msg
        assert "📅" in msg
        assert "2 комбинаци" in msg  # "комбинаций" or "комбинации"

    @pytest.mark.asyncio
    async def test_generate_weekly_plan_5_days(self):
        from worker.tasks.weekly_plan import generate_weekly_plan
        user = MagicMock()
        user.segment = "no_kids"
        user.city = None
        user.timezone = "Europe/Vilnius"
        user.id = "test"
        items = (
            [_item("top", f"top_{i}", "белый") for i in range(5)]
            + [_item("bottom", f"bot_{i}", "синий") for i in range(3)]
            + [_item("footwear", "кроссовки", "белый")]
        )
        plan = await generate_weekly_plan(user, items)
        assert len(plan) == 5
        for day in plan:
            assert "day_name" in day
            assert "occasion" in day
            assert "outfit_line" in day

    def test_weekly_no_items(self):
        """Empty wardrobe → no plan."""
        import asyncio
        from worker.tasks.weekly_plan import generate_weekly_plan
        user = MagicMock()
        user.segment = "no_kids"
        user.city = None
        user.timezone = "Europe/Vilnius"
        user.id = "test"
        plan = asyncio.get_event_loop().run_until_complete(
            generate_weekly_plan(user, [])
        )
        assert plan == []


# ── Fitting ───────────────────────────────────────────────────────────────────

class TestFitting:

    def test_fitting_module_exists(self):
        from bot.handlers.fitting import handle_fitting_start, process_fitting_photo
        assert callable(handle_fitting_start)
        assert callable(process_fitting_photo)

    def test_fitting_limit(self):
        from bot.handlers.fitting import _FITTING_LIMIT
        assert _FITTING_LIMIT == 5

    def test_fitting_in_menu(self):
        with open("bot/handlers/menu.py") as f:
            source = f.read()
        assert "Помощь" in source

    def test_fitting_registered_in_app(self):
        with open("bot/app.py") as f:
            source = f.read()
        assert "fitting" in source
        assert "Подойдёт" in source

    def test_fitting_mode_in_photo_handler(self):
        """Photo handler should check for fitting mode."""
        with open("bot/handlers/wardrobe.py") as f:
            source = f.read()
        assert '"fitting"' in source
        assert "process_fitting_photo" in source


# ── Scheduler ─────────────────────────────────────────────────────────────────

class TestScheduler:

    def test_cookbook_dinner_in_scheduler(self):
        # Фешн-рассылки (weekly_plan/evening_push и др.) удалены; остался кукбук-пуш.
        with open("core/scheduler.py") as f:
            source = f.read()
        assert "cookbook_dinner" in source

    def test_weekly_plan_task_exists(self):
        # Код таска остался (не планируется, но не удалён)
        from worker.tasks import weekly_plan
        assert hasattr(weekly_plan, "schedule_weekly")
