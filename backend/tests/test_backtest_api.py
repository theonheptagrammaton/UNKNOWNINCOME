"""Backtest API round-trip: POST /run → worker executes → GET /runs/{id}."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.backtest as backtest_api
from app.backtest.service import execute_backtest
from app.core.config import settings
from app.core.db import get_session
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.main import app
from app.models.base import Base
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
SYMBOL = "BTCUSDT"
TF = "1h"


def _ema_config(symbol: str = SYMBOL) -> dict:
    return {
        "market": MARKET,
        "symbol": symbol,
        "tf": TF,
        "direction": "long",
        "indicators": [
            {"key": "ema_fast", "id": "ema", "params": {"timeperiod": 9}},
            {"key": "ema_slow", "id": "ema", "params": {"timeperiod": 21}},
        ],
        "rules": {
            "long_entry": [
                {"primitive": "line_cross",
                 "args": {"a": "ema_fast", "b": "ema_slow", "direction": "up"}}
            ],
            "long_exit": [
                {"primitive": "line_cross",
                 "args": {"a": "ema_fast", "b": "ema_slow", "direction": "down"}}
            ],
        },
        "costs": {"funding_enabled": False},
    }


async def test_run_and_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/bt.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with session_factory() as session:
            yield session

    async def fake_enqueue(_name: str, *_args: object) -> str:
        return "job-abc"

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(backtest_api, "enqueue", fake_enqueue)

    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(400, TF, seed=7)))

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/backtest/run", json=_ema_config())
            assert resp.status_code == 202
            run_id = resp.json()["run_id"]
            assert resp.json()["config_hash"]

            # Worker executes (enqueue was stubbed); drive it directly.
            async with session_factory() as session:
                await execute_backtest(session, run_id)

            detail = await client.get(f"/api/backtest/runs/{run_id}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["status"] == "done"
            assert body["metrics"]["num_trades"] >= 1
            assert body["report"]["bars"] == 400
            assert len(body["report"]["candles"]) == 400
            assert len(body["report"]["markers"]) == 2 * body["metrics"]["num_trades"]
            assert body["report"]["cost_breakdown"]["funding_on"] is False

            # Metrics-only fetch skips the heavy report.
            slim = await client.get(f"/api/backtest/runs/{run_id}?include_report=false")
            assert slim.json()["report"] is None
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_preview_returns_report_with_indicators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /backtest/preview runs a genome synchronously and returns its chart data."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(300, TF, seed=7)))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/backtest/preview", json=_ema_config())
        assert resp.status_code == 200
        body = resp.json()
        assert body["config_hash"]
        assert body["metrics"]["num_trades"] >= 1
        report = body["report"]
        assert len(report["candles"]) == 300
        # Indicator overlays travel with the report for the on-demand chart.
        keys = {ind["key"] for ind in report["indicators"]}
        assert {"ema_fast", "ema_slow"} <= keys

        # No data for an unseeded symbol ⇒ 422, not a 500.
        missing = await client.post("/api/backtest/preview", json=_ema_config("NODATAUSDT"))
        assert missing.status_code == 422


async def test_failed_run_records_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/bt2.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with session_factory() as session:
            yield session

    async def fake_enqueue(_name: str, *_args: object) -> str:
        return "job-x"

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(backtest_api, "enqueue", fake_enqueue)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # No parquet seeded ⇒ NoDataError ⇒ status failed.
            resp = await client.post("/api/backtest/run", json=_ema_config("NODATAUSDT"))
            run_id = resp.json()["run_id"]
            async with session_factory() as session:
                await execute_backtest(session, run_id)
            body = (await client.get(f"/api/backtest/runs/{run_id}")).json()
            assert body["status"] == "failed"
            assert "NoDataError" in body["error"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
