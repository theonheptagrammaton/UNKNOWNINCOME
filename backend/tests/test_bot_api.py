"""API round-trips: convert-to-strategy, hot-reload save, mode + kill switch (§12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import get_session
from app.main import app
from app.models.backtest import BacktestRun
from app.models.base import Base

MARKET = "binance_usdm"


def _run_config() -> dict:
    return {
        "market": MARKET, "symbol": "BTCUSDT", "tf": "1h", "direction": "long",
        "indicators": [{"key": "ema", "id": "ema", "params": {"timeperiod": 9}}],
        "rules": {"long_entry": [{"primitive": "regime", "args": {"x": "ema", "rule": "gt:0"}}],
                  "long_exit": [], "short_entry": [], "short_exit": []},
        "costs": {"funding_enabled": False},
    }


def _genome(name: str, tp: int) -> dict:
    cfg = _run_config()
    cfg["indicators"][0]["params"]["timeperiod"] = tp
    return {"name": name, "config": cfg}


@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
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


async def test_convert_run_then_edit_hot_reloads(client) -> None:
    c, factory = client
    async with factory() as s:
        s.add(BacktestRun(id="run-9", config=_run_config(), config_hash="h", seed=42,
                          status="done", metrics={"num_trades": 3}))
        await s.commit()

    # Convert to strategy (doc §10.1 "Convert to strategy").
    resp = await c.post("/api/strategies/from-run", json={"run_id": "run-9"})
    assert resp.status_code == 201
    strat_id = resp.json()["id"]
    assert resp.json()["active_version"] == 1

    # Save a new version from the raw JSON editor → version 2, active pointer moves.
    resp = await c.post(
        f"/api/strategies/{strat_id}/versions", json={"genome": _genome("edited", 21)}
    )
    assert resp.status_code == 201 and resp.json()["version"] == 2

    detail = (await c.get(f"/api/strategies/{strat_id}")).json()
    assert detail["active_version"] == 2

    versions = (await c.get(f"/api/strategies/{strat_id}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]

    # Diff the two versions.
    a, b = versions[1]["id"], versions[0]["id"]
    diff = (await c.get(f"/api/strategies/{strat_id}/diff", params={"a": a, "b": b})).json()
    assert "config.indicators[0].params.timeperiod" in diff["changes"]


async def test_mode_and_killswitch_endpoints(client) -> None:
    c, _ = client
    assert (await c.post("/api/bot/mode", json={"mode": "paper"})).status_code == 200
    status = (await c.get("/api/bot/status")).json()
    assert status["global_mode"] == "paper"
    assert status["live_enabled"] is False

    assert (await c.post("/api/bot/killswitch", json={"reason": "test"})).status_code == 200
    assert (await c.get("/api/bot/status")).json()["killswitch"] is True
    assert (await c.post("/api/bot/killswitch/clear")).status_code == 200
    assert (await c.get("/api/bot/status")).json()["killswitch"] is False


async def test_invalid_mode_rejected(client) -> None:
    c, _ = client
    assert (await c.post("/api/bot/mode", json={"mode": "banana"})).status_code == 400


async def test_reload_plugins_endpoint(client) -> None:
    c, _ = client
    body = (await c.post("/api/strategies/reload-plugins")).json()
    assert "pct_above" in body["primitives"]


async def test_from_run_unknown_returns_404(client) -> None:
    c, _ = client
    assert (await c.post("/api/strategies/from-run", json={"run_id": "nope"})).status_code == 404
