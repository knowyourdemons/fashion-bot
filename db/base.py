from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, MappedColumn
from typing import AsyncGenerator

from config import settings


class Base(DeclarativeBase):
    pass


# Write engine (primary)
write_engine = create_async_engine(
    settings.database_write_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.environment == "dev",
)

# Read engine (replica / same host in dev)
read_engine = create_async_engine(
    settings.database_read_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=False,
)

AsyncWriteSession = async_sessionmaker(write_engine, expire_on_commit=False)
AsyncReadSession = async_sessionmaker(read_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """DI dependency — write session с auto commit/rollback."""
    async with AsyncWriteSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """DI dependency — read-only session."""
    async with AsyncReadSession() as session:
        try:
            yield session
        finally:
            await session.close()
