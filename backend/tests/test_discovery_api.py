"""Discovery API round-trip: POST /scan → worker runs → GET /scans/{id} + leaderboard."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.discovery as discovery_api
from app.core.config import settings
from app.core.db import get_session
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.discovery.service import execute_scan
from app.main import app
from app.models.base import Base
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
TF = "1h"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def _scan_config() -> dict:
    return {
        "market": MARKET,
        "symbols": SYMBOLS,
        "timeframes": [TF],
        "fast_mode": True,
        "seed": 7,
        "costs": {"funding_enabled": False},
    }


async def test_scan_queue_execute_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/disc.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with session_factory() as session:
            yield session

    async def fake_enqueue(_name: str, *_args: object) -> str:
        return "job-scan"

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(discovery_api, "enqueue", fake_enqueue)

    for i, symbol in enumerate(SYMBOLS):
        write_ohlcv(
            MARKET, symbol, TF,
            ohlcv_rows_to_frame(make_wave_ohlcv(900, TF, seed=100 + i, base_price=100.0 + 10 * i)),
        )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/discovery/scan", json=_scan_config())
            assert resp.status_code == 202
            scan_id = resp.json()["scan_id"]
            assert resp.json()["config_hash"]

            # Worker executes (enqueue stubbed) — drive it directly.
            async with session_factory() as session:
                await execute_scan(session, scan_id)

            detail = await client.get(f"/api/discovery/scans/{scan_id}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["status"] == "done"
            assert body["progress"] == 1.0
            assert body["combos_tried"] > 0
            assert body["leaderboard"]["rows"], "compact leaderboard has rows"
            assert body["detail"] is None  # not requested

            full = await client.get(f"/api/discovery/scans/{scan_id}?include_detail=true")
            assert full.json()["detail"]["leaderboard"], "full artifact carries the genomes"

            board = await client.get("/api/discovery/leaderboard")
            assert board.status_code == 200
            rows = board.json()["rows"]
            assert rows and all(r["scan_id"] == scan_id for r in rows)
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_unknown_scan_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/disc2.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/api/discovery/scans/nope")).status_code == 404
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
