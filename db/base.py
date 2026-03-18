from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from config import settings


class Base(DeclarativeBase):
    pass


# ── Lazy engine / session factory ────────────────────────────────────────────
# Engines создаются при первом вызове сессии, не при импорте модуля.
# Это позволяет импортировать db.base в тестах и воркере без живого DB.

_write_maker: async_sessionmaker | None = None
_read_maker: async_sessionmaker | None = None


def _get_write_maker() -> async_sessionmaker:
    global _write_maker
    if _write_maker is None:
        engine = create_async_engine(
            settings.database_write_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            echo=settings.environment == "dev",
        )
        _write_maker = async_sessionmaker(engine, expire_on_commit=False)
    return _write_maker


def _get_read_maker() -> async_sessionmaker:
    global _read_maker
    if _read_maker is None:
        engine = create_async_engine(
            settings.database_read_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            echo=False,
        )
        _read_maker = async_sessionmaker(engine, expire_on_commit=False)
    return _read_maker


def AsyncWriteSession() -> AsyncSession:
    """Создаёт write-сессию. Используй: async with AsyncWriteSession() as session:"""
    return _get_write_maker()()


def AsyncReadSession() -> AsyncSession:
    """Создаёт read-сессию. Используй: async with AsyncReadSession() as session:"""
    return _get_read_maker()()


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
