"""Async database engine, session factory and schema bootstrap.

Uses SQLAlchemy async (asyncpg in production; aiosqlite in tests). Schema is
created idempotently via ``create_all`` — Alembic migrations are introduced
when the first schema change lands (later phase).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.base import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session."""
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create tables if missing. Tolerant of an unreachable DB (logs + skips)."""
    import app.models  # noqa: F401  ensure models register on Base.metadata

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - startup resilience
        logger.warning("DB schema init skipped (database unreachable?): %s", exc)
