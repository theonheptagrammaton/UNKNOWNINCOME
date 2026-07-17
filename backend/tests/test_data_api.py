"""Tests for the data API (sync enqueue + status)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.data as data_mod
from app.core.config import settings
from app.core.db import get_session
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.data.timeframes import tf_to_ms
from app.main import app
from app.models.base import Base
from app.models.market import CandleSyncState
from fakes import make_ohlcv


async def test_sync_enqueue_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with session_factory() as session:
            yield session

    async def fake_enqueue(_name: str, *_args: object) -> str:
        return "job-123"

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(data_mod, "enqueue", fake_enqueue)

    # Seed one series (sync-state row + a small parquet).
    step = tf_to_ms("1h")
    async with session_factory() as session:
        session.add(
            CandleSyncState(
                market="binance_usdm", symbol="BTCUSDT", tf="1h",
                first_ts=0, last_ts=2 * step, gaps=[],
            )
        )
        await session.commit()
    write_ohlcv("binance_usdm", "BTCUSDT", "1h", ohlcv_rows_to_frame(make_ohlcv(0, 3, "1h")))

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/data/sync", json={"symbols": ["BTCUSDT"], "months": 1})
            assert resp.status_code == 202
            body = resp.json()
            assert body["job_id"] == "job-123"
            assert body["timeframes"] == settings.default_timeframes

            status = await client.get("/api/data/status")
            assert status.status_code == 200
            payload = status.json()
            assert payload["summary"]["series"] == 1
            row = payload["series"][0]
            assert row["symbol"] == "BTCUSDT"
            assert row["rows"] == 3
            assert row["missing"] == 0
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
