"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  register models on Base.metadata
from app.core.config import settings
from app.models.base import Base


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the Parquet store at an isolated temp directory."""
    target = tmp_path / "parquet"
    monkeypatch.setattr(settings, "data_dir", str(target))
    return target


@pytest_asyncio.fixture
async def _db_engine(tmp_path: Path) -> AsyncIterator[object]:
    """A SQLite-backed async engine with the schema created (shared per test)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(_db_engine: object) -> AsyncIterator[AsyncSession]:
    """A SQLite-backed async session over the shared engine."""
    session_factory = async_sessionmaker(_db_engine, expire_on_commit=False)  # type: ignore[arg-type]
    async with session_factory() as session:
        yield session


@pytest.fixture
def db_session_factory(_db_engine: object) -> async_sessionmaker[AsyncSession]:
    """A session *factory* over the same engine as :func:`db_session`.

    Lets a test drive code that opens its own short-lived sessions (e.g. the
    liquidation collector's batch writer) while asserting via ``db_session``.
    """
    return async_sessionmaker(_db_engine, expire_on_commit=False)  # type: ignore[arg-type]
