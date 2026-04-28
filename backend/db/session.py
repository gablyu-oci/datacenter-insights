"""
Async database session factory using asyncpg.
Provides FastAPI dependency injection via get_db().
"""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends() pattern for async DB sessions."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create tables if needed (for dev only; prod uses Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
