"""Phase-6 API surface (doc §12): debug degrade hook, pending queue, approve, reoptimize."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import get_session
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.main import app
from app.models.base import Base
from app.strategy import service
from fakes import make_wave_ohlcv

MARKET, SYMBOL, TF = "binance_usdm", "BTCUSDT", "1h"


def _genome(name: str = "ApiSubject") -> dict:
    return {
        "name": name,
        "config": {
            "market": MARKET, "symbol": SYMBOL, "tf": TF, "direction": "long",
            "indicators": [{"key": "ema", "id": "ema", "params": {"timeperiod": 9}}],
            "rules": {
                "long_entry": [{"primitive": "regime", "args": {"x": "ema", "rule": "gt:0"}}],
                "long_exit": [], "short_entry": [], "short_exit": [],
            },
            "costs": {"funding_enabled": False},
            "capital": {"initial_cash": 10_000, "size_pct": 1.0, "leverage": 1.0},
            "risk_exit": {"atr_stop_mult": 2.0, "atr_target_mult": 3.0, "atr_length": 14},
        },
    }


@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    monkeypatch.setattr(settings, "app_env", "development")
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(400, TF, seed=7)))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed(factory, *, mode="paper") -> str:
    async with factory() as s:
        strat, _ = await service.create_strategy(s, _genome())
        await service.set_mode(s, strat.id, mode)
        await s.commit()
        return strat.id


async def test_debug_degrade_pauses_and_queues_pending(client) -> None:
    c, factory = client
    strat_id = await _seed(factory)

    resp = await c.post("/api/bot/debug/degrade", json={"strategy_id": strat_id, "trials": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["paused"] is True
    assert body["pending_version"] is not None
    assert body["pending_version"]["status"] == "pending_approval"

    # It shows up in the approval queue with a diff vs the active version.
    pending = (await c.get("/api/strategies/pending")).json()
    assert len(pending) == 1
    assert pending[0]["strategy_id"] == strat_id
    assert "diff" in pending[0]

    # Strategy is paused and still on its original active version (not the proposal).
    strat = (await c.get(f"/api/strategies/{strat_id}")).json()
    assert strat["mode"] == "off"


async def test_debug_degrade_then_approve_activates(client) -> None:
    c, factory = client
    strat_id = await _seed(factory)
    resp = await c.post("/api/bot/debug/degrade", json={"strategy_id": strat_id, "trials": 4})
    body = resp.json()
    version_id = body["pending_version"]["id"]

    approved = await c.post(f"/api/strategies/{strat_id}/versions/{version_id}/approve")
    assert approved.status_code == 200
    out = approved.json()
    assert out["active_version_id"] == version_id
    assert out["status"] == "paper"
    assert out["mode"] == "paper"
    # Approval queue is now empty.
    assert (await c.get("/api/strategies/pending")).json() == []


async def test_debug_degrade_then_reject_keeps_paused(client) -> None:
    c, factory = client
    strat_id = await _seed(factory)
    resp = await c.post("/api/bot/debug/degrade", json={"strategy_id": strat_id, "trials": 4})
    body = resp.json()
    version_id = body["pending_version"]["id"]

    rejected = await c.post(f"/api/strategies/{strat_id}/versions/{version_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "retired"
    assert (await c.get("/api/strategies/pending")).json() == []


async def test_manual_reoptimize_endpoint(client) -> None:
    c, factory = client
    strat_id = await _seed(factory)
    resp = await c.post(f"/api/strategies/{strat_id}/reoptimize", json={"trials": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["produced"] is True
    assert body["version"]["status"] == "pending_approval"


async def test_regime_lock_setting_roundtrip(client) -> None:
    c, _ = client
    resp = await c.post("/api/bot/settings", json={"regime_lock": {"mode": "auto"}})
    assert resp.status_code == 200
    assert resp.json()["regime_lock"]["mode"] == "auto"
    status = (await c.get("/api/bot/status")).json()
    assert status["regime"] == "auto"


async def test_debug_degrade_disabled_in_production(client, monkeypatch) -> None:
    c, factory = client
    strat_id = await _seed(factory)
    monkeypatch.setattr(settings, "app_env", "production")
    resp = await c.post("/api/bot/debug/degrade", json={"strategy_id": strat_id})
    assert resp.status_code == 404
