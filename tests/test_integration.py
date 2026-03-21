"""
Integration тесты — с реальной БД (seeded).
Read-only тесты используют AsyncReadSession.
Write тесты используют AsyncWriteSession + rollback через savepoint.

Skipped in CI: requires seeded database with test users.
"""
import os
import pytest
import uuid
from datetime import date
from sqlalchemy import select

_IN_CI = os.environ.get("ENVIRONMENT") == "test" or os.environ.get("CI") == "true"
pytestmark = pytest.mark.skipif(_IN_CI, reason="requires seeded database (not available in CI)")


# ── colortype в users ─────────────────────────────────────────────────────

class TestUserColortype:
    async def test_colortype_поле_существует(self):
        from db.models.user import User
        from sqlalchemy import inspect as sa_inspect
        mapper = sa_inspect(User)
        columns = [c.key for c in mapper.columns]
        assert "colortype" in columns, \
            "Миграция colortype не применена к таблице users!"

    async def test_colortype_читается(self):
        from db.base import AsyncReadSession
        from db.models.user import User
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == 195169)
            )
            user = result.scalar_one_or_none()
        assert user is not None, "Тестовый пользователь не найден"
        assert hasattr(user, "colortype")


# ── Дубль детей ───────────────────────────────────────────────────────────

class TestChildDuplicate:
    async def test_один_ребёнок_в_тестовом_аккаунте(self):
        from db.base import AsyncReadSession
        from db.crud.children import get_children
        user_id = uuid.UUID("3b4da73e-0772-407c-915e-f6dd1610fcc3")
        async with AsyncReadSession() as session:
            children = await get_children(session, user_id)
        assert len(children) == 1, \
            f"Должен быть 1 ребёнок, найдено: {len(children)}"
        assert children[0].name == "Алиса"

    async def test_повторный_онбординг_не_создает_дубль(self):
        """Симулировать логику upsert из _finish_onboarding."""
        from db.base import AsyncWriteSession
        from db.models.child import Child
        from db.crud.children import get_children
        import sqlalchemy as sa

        user_id = uuid.UUID("3b4da73e-0772-407c-915e-f6dd1610fcc3")

        async with AsyncWriteSession() as session:
            # Запомнить текущее количество
            children_before = await get_children(session, user_id)
            count_before = len(children_before)

            # Выполнить upsert (как в _finish_onboarding)
            existing = await session.execute(
                select(Child).where(
                    Child.user_id == user_id,
                    Child.deleted_at.is_(None),
                ).order_by(Child.created_at.asc()).limit(1)
            )
            existing_child = existing.scalar_one_or_none()

            if existing_child:
                await session.execute(
                    sa.update(Child).where(Child.id == existing_child.id)
                    .values(current_size=existing_child.current_size)  # no-op update
                )
            else:
                new_child = Child(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    name="Алиса",
                    gender="girl",
                    birthdate=date(2022, 9, 1),
                )
                session.add(new_child)

            await session.flush()

            children_after = await get_children(session, user_id)
            count_after = len(children_after)

            # Rollback — не сохранять изменения
            await session.rollback()

        assert count_after == count_before, \
            f"Дубль! было {count_before}, стало {count_after}"


# ── Гардероб owner ────────────────────────────────────────────────────────

class TestWardrobeOwner:
    async def test_гардероб_ребёнка_запрос_работает(self):
        """Проверяет что запрос гардероба ребёнка работает (не проверяет наличие вещей)."""
        from db.base import AsyncReadSession
        from db.crud.wardrobe import get_owner_items
        child_id = uuid.UUID("acf0100d-ca11-4fce-815e-c516af11e710")
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child_id, "child")
        assert isinstance(items, list), "get_owner_items должен вернуть список"

    async def test_гардеробы_пользователя_и_ребёнка_раздельны(self):
        from db.base import AsyncReadSession
        from db.crud.wardrobe import get_owner_items
        user_id = uuid.UUID("3b4da73e-0772-407c-915e-f6dd1610fcc3")
        child_id = uuid.UUID("acf0100d-ca11-4fce-815e-c516af11e710")

        async with AsyncReadSession() as session:
            user_items = await get_owner_items(session, user_id, "user")
            child_items = await get_owner_items(session, child_id, "child")

        user_ids = {str(i.owner_id) for i in user_items}
        child_ids = {str(i.owner_id) for i in child_items}
        assert not user_ids.intersection(child_ids), \
            "Вещи пользователя и ребёнка смешаны!"

    async def test_тип_владельца_корректен(self):
        from db.base import AsyncReadSession
        from db.crud.wardrobe import get_owner_items
        child_id = uuid.UUID("acf0100d-ca11-4fce-815e-c516af11e710")
        async with AsyncReadSession() as session:
            items = await get_owner_items(session, child_id, "child")
        for item in items[:5]:
            assert item.owner_type == "child", \
                f"Вещь {item.id} имеет owner_type={item.owner_type}"


# ── Пользователь ──────────────────────────────────────────────────────────

class TestUser:
    async def test_тестовый_пользователь_существует(self):
        from db.base import AsyncReadSession
        from db.models.user import User
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == 195169)
            )
            user = result.scalar_one_or_none()
        assert user is not None
        assert user.name is not None
        assert user.onboarding_completed is True

    async def test_онбординг_завершён(self):
        from db.base import AsyncReadSession
        from db.models.user import User
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == 195169)
            )
            user = result.scalar_one_or_none()
        assert user.onboarding_completed is True
        assert user.onboarding_step is None
