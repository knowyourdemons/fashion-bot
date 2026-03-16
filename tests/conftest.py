"""Fixtures: db, user, child, redis."""
import asyncio
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from db.base import Base, AsyncWriteSession
from db.models.user import User
from db.models.child import Child


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/1")
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def db_session():
    async with AsyncWriteSession() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session):
    from db.crud.users import create
    user = await create(db_session, telegram_id=999999, name="Test User")
    await db_session.commit()
    return user
