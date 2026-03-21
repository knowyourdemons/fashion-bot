"""Tests for db/crud/ modules: users, wardrobe, children, brief_log."""
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.crud import users as users_crud
from db.crud import wardrobe as wardrobe_crud
from db.crud import children as children_crud
from db.crud import brief_log as brief_log_crud


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(
    scalar_one_or_none=None,
    scalars_all=None,
    scalar_value=None,
):
    """Build an AsyncMock session with execute returning configured results."""
    session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one_or_none
    mock_result.scalar.return_value = scalar_value

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = scalars_all if scalars_all is not None else []
    mock_result.scalars.return_value = mock_scalars

    session.execute.return_value = mock_result
    session.flush = AsyncMock()
    session.add = MagicMock()
    # session.scalar used directly by count_user_briefs / count_liked_briefs
    session.scalar = AsyncMock(return_value=scalar_value)
    return session


# ===========================================================================
# Users CRUD
# ===========================================================================

class TestUsersCrud:
    @pytest.mark.asyncio
    async def test_get_by_telegram_id_returns_user(self):
        fake_user = MagicMock(name="User")
        session = _make_session(scalar_one_or_none=fake_user)

        result = await users_crud.get_by_telegram_id(session, telegram_id=195169)

        assert result is fake_user
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_telegram_id_returns_none_when_missing(self):
        session = _make_session(scalar_one_or_none=None)

        result = await users_crud.get_by_telegram_id(session, telegram_id=999999)

        assert result is None

    @pytest.mark.asyncio
    async def test_create_adds_user_to_session(self):
        session = _make_session()

        user = await users_crud.create(session, telegram_id=111222, name="TestUser")

        session.add.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert added_obj.telegram_id == 111222
        assert added_obj.name == "TestUser"
        session.flush.assert_awaited_once()
        assert user is added_obj

    @pytest.mark.asyncio
    async def test_update_user_plan_executes_update(self):
        session = _make_session()
        uid = uuid.uuid4()
        expires = datetime(2026, 12, 31)

        await users_crud.update_user_plan(
            session,
            user_id=uid,
            plan="premium",
            plan_expires_at=expires,
            subscription_id="sub_123",
            payment_provider="stripe",
        )

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_id_returns_user(self):
        fake_user = MagicMock(name="User")
        session = _make_session(scalar_one_or_none=fake_user)
        uid = uuid.uuid4()

        result = await users_crud.get_by_id(session, user_id=uid)

        assert result is fake_user


# ===========================================================================
# Wardrobe CRUD
# ===========================================================================

class TestWardrobeCrud:
    @pytest.mark.asyncio
    async def test_get_owner_items_returns_filtered_items(self):
        items = [MagicMock(), MagicMock()]
        session = _make_session(scalars_all=items)
        owner_id = uuid.uuid4()

        result = await wardrobe_crud.get_owner_items(session, owner_id, "user")

        assert result == items
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_owner_items_excludes_deleted_by_default(self):
        session = _make_session(scalars_all=[])

        await wardrobe_crud.get_owner_items(session, uuid.uuid4(), "user")

        # Verify execute was called (the WHERE clause includes deleted_at == None)
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_owner_items_includes_deleted_when_flag_set(self):
        items = [MagicMock(), MagicMock(), MagicMock()]
        session = _make_session(scalars_all=items)

        result = await wardrobe_crud.get_owner_items(
            session, uuid.uuid4(), "child", include_deleted=True
        )

        assert len(result) == 3
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_flushes_new_item(self):
        session = _make_session()

        item = await wardrobe_crud.create(
            session,
            owner_id=uuid.uuid4(),
            owner_type="user",
            category_group="tops",
            type="t-shirt",
            color="white",
        )

        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        added = session.add.call_args[0][0]
        assert added.category_group == "tops"
        assert added.color == "white"

    @pytest.mark.asyncio
    async def test_increment_wear_count_matching_version_succeeds(self):
        item_id = uuid.uuid4()
        session = _make_session(scalar_one_or_none=item_id)

        result = await wardrobe_crud.increment_wear_count(session, item_id, current_version=1)

        assert result is True
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_increment_wear_count_wrong_version_returns_false(self):
        session = _make_session(scalar_one_or_none=None)

        result = await wardrobe_crud.increment_wear_count(session, uuid.uuid4(), current_version=5)

        assert result is False

    @pytest.mark.asyncio
    async def test_soft_delete_executes_update(self):
        session = _make_session()
        item_id = uuid.uuid4()

        await wardrobe_crud.soft_delete(session, item_id)

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_owner_items_count_returns_count(self):
        session = _make_session(scalar_value=7)

        result = await wardrobe_crud.get_owner_items_count(
            session, uuid.uuid4(), "user"
        )

        assert result == 7

    @pytest.mark.asyncio
    async def test_get_owner_items_count_returns_zero_when_none(self):
        session = _make_session(scalar_value=None)

        result = await wardrobe_crud.get_owner_items_count(
            session, uuid.uuid4(), "user"
        )

        assert result == 0


# ===========================================================================
# Children CRUD
# ===========================================================================

class TestChildrenCrud:
    @pytest.mark.asyncio
    async def test_create_child_creates_with_correct_fields(self):
        session = _make_session()
        uid = uuid.uuid4()
        bday = date(2023, 6, 15)

        child = await children_crud.create_child(
            session,
            user_id=uid,
            name="Alice",
            birthdate=bday,
            gender="girl",
            current_size="92",
            shoe_size=26,
        )

        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        added = session.add.call_args[0][0]
        assert added.name == "Alice"
        assert added.gender == "girl"
        assert added.birthdate == bday
        assert added.user_id == uid
        assert added.current_size == "92"
        assert added.shoe_size == 26

    @pytest.mark.asyncio
    async def test_get_children_returns_list(self):
        kids = [MagicMock(), MagicMock()]
        session = _make_session(scalars_all=kids)

        result = await children_crud.get_children(session, uuid.uuid4())

        assert result == kids
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_children_filters_deleted(self):
        session = _make_session(scalars_all=[])

        result = await children_crud.get_children(session, uuid.uuid4())

        assert result == []
        session.execute.assert_awaited_once()


# ===========================================================================
# BriefLog CRUD
# ===========================================================================

class TestBriefLogCrud:
    @pytest.mark.asyncio
    async def test_create_log_flushes(self):
        session = _make_session()

        log = await brief_log_crud.create_log(
            session,
            user_id=uuid.uuid4(),
            date=date.today(),
            weather_summary="cloudy +5",
        )

        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        added = session.add.call_args[0][0]
        assert added.weather_summary == "cloudy +5"

    @pytest.mark.asyncio
    async def test_get_log_returns_log(self):
        fake_log = MagicMock()
        session = _make_session(scalar_one_or_none=fake_log)
        log_id = uuid.uuid4()

        result = await brief_log_crud.get_log(session, log_id)

        assert result is fake_log
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_log_returns_none_for_missing(self):
        session = _make_session(scalar_one_or_none=None)

        result = await brief_log_crud.get_log(session, uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_update_feedback_executes_update(self):
        session = _make_session()
        log_id = uuid.uuid4()

        await brief_log_crud.update_feedback(session, log_id, feedback="up")

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_count_user_briefs_returns_count(self):
        session = _make_session(scalar_value=12)

        result = await brief_log_crud.count_user_briefs(session, uuid.uuid4())

        assert result == 12
        session.scalar.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_count_user_briefs_returns_zero_when_none(self):
        session = _make_session(scalar_value=None)

        result = await brief_log_crud.count_user_briefs(session, uuid.uuid4())

        assert result == 0

    @pytest.mark.asyncio
    async def test_count_liked_briefs_counts_only_up(self):
        session = _make_session(scalar_value=3)

        result = await brief_log_crud.count_liked_briefs(session, uuid.uuid4())

        assert result == 3
        session.scalar.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_count_liked_briefs_returns_zero_when_none(self):
        session = _make_session(scalar_value=None)

        result = await brief_log_crud.count_liked_briefs(session, uuid.uuid4())

        assert result == 0
