"""Promotion gate (doc §9.5) — LIVE refused at EVERY layer until the gate opens.

This is the Phase-7 acceptance: "Gate sağlanmadan LIVE moda geçiş her katmanda
reddedilir — TESTLE KANITLA." We prove refusal at the gate function, the mode module,
the strategy service, the HTTP API and — the technical closure — the bot engine, which
never even constructs the live adapter while the gate is closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot import mode as mode_mod
from app.bot.engine import BotEngine
from app.bot.killswitch import KillSwitch
from app.bot.promotion import (
    GateNotMet,
    assert_can_go_live,
    evaluate_global_gate,
    evaluate_strategy_gate,
)
from app.core.clock import now_ms
from app.core.config import settings
from app.core.db import get_session
from app.main import app
from app.models.base import Base
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.strategy import service

DAY_MS = 86_400_000
SID = "strat-1"


async def _make_strategy(session, sid: str = SID) -> None:
    version = StrategyVersion(
        id=f"{sid}-v1", strategy_id=sid, version=1,
        genome={"name": "X", "config": {"capital": {"initial_cash": 10_000}}},
        genome_hash="h", status="paper",
    )
    strat = Strategy(id=sid, name="X", mode="paper", active_version_id=f"{sid}-v1")
    session.add_all([strat, version])


async def _seed_passing(session, sid: str = SID, n: int = 35, span_days: int = 40) -> None:
    """A paper record that clears the gate: 35 winning trades spread over 40 days."""
    start = now_ms() - span_days * DAY_MS
    for i in range(n):
        ts = start + int(i * span_days * DAY_MS / n)
        session.add(Trade(
            mode="paper", status="closed", strategy_id=sid, strategy_version_id=f"{sid}-v1",
            symbol="BTCUSDT", side="long", qty=1.0, entry_price=100.0,
            entry_ts=ts, exit_ts=ts + 3_600_000, pnl=5.0, fees=0.1,
        ))


async def _enable_infra(session) -> None:
    from app.core.secrets import store_api_keys

    await store_api_keys(session, "livekey_abcdef12", "livesecret_abcdef12", testnet=True)


@pytest.fixture
def infra(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "live_trading_enabled", True)
    monkeypatch.setattr(settings, "secrets_key", "unit-test-master")
    yield


# ── Layer 1: the gate function ────────────────────────────────────────────────
async def test_gate_closed_without_track_record(db_session, infra) -> None:
    await _make_strategy(db_session)
    await db_session.commit()
    result = await evaluate_strategy_gate(db_session, SID)
    assert result.passed is False
    assert any("trades" in f for f in result.failures)
    assert any("days" in f for f in result.failures)


async def test_gate_closed_when_infra_missing(db_session) -> None:
    # Even a perfect record cannot open the gate without live infra.
    await _make_strategy(db_session)
    await _seed_passing(db_session)
    await db_session.commit()
    result = await evaluate_strategy_gate(db_session, SID)
    assert result.passed is False
    assert any("live trading disabled" in f for f in result.failures)


async def test_gate_opens_with_record_and_infra(db_session, infra) -> None:
    await _make_strategy(db_session)
    await _seed_passing(db_session)
    await _enable_infra(db_session)
    await db_session.commit()
    strat_result = await evaluate_strategy_gate(db_session, SID)
    assert strat_result.passed is True, strat_result.failures
    global_result = await evaluate_global_gate(db_session)
    assert global_result.passed is True, global_result.failures


# ── Layer 2 + 3: mode module + strategy service ──────────────────────────────
async def test_mode_module_refuses_live_when_closed(db_session, infra) -> None:
    await _make_strategy(db_session)
    await db_session.commit()
    with pytest.raises(GateNotMet):
        await assert_can_go_live(db_session, "global", None)
    with pytest.raises(GateNotMet):
        await mode_mod.set_global_mode(db_session, "live")


async def test_service_refuses_strategy_live_when_closed(db_session, infra) -> None:
    await _make_strategy(db_session)
    await db_session.commit()
    with pytest.raises(GateNotMet):
        await service.set_mode(db_session, SID, "live")
    # But paper is always allowed.
    await service.set_mode(db_session, SID, "paper")


async def test_mode_module_allows_live_when_open(db_session, infra) -> None:
    await _make_strategy(db_session)
    await _seed_passing(db_session)
    await _enable_infra(db_session)
    await db_session.commit()
    await mode_mod.set_global_mode(db_session, "live")
    await db_session.commit()
    assert await mode_mod.get_global_mode(db_session) == "live"


# ── Layer 4: the HTTP API ─────────────────────────────────────────────────────
@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "live_trading_enabled", True)
    monkeypatch.setattr(settings, "secrets_key", "unit-test-master")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/gate.db")
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


async def test_api_refuses_live_then_allows_when_gate_opens(client) -> None:
    c, factory = client
    async with factory() as s:
        await _make_strategy(s)
        await s.commit()

    # Gate closed → 422 with the failing metrics.
    resp = await c.post("/api/bot/mode", json={"mode": "live", "scope": "global"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "promotion_gate"

    # Store keys via the Settings API (masked, never plaintext) + seed a record.
    keyresp = await c.post(
        "/api/bot/keys",
        json={"api_key": "livekey_abcdef12", "api_secret": "livesecret_abcdef12", "testnet": True},
    )
    assert keyresp.status_code == 200
    assert "livekey_abcdef12" not in keyresp.text  # masked
    async with factory() as s:
        await _seed_passing(s)
        await s.commit()

    # Gate open → the switch flips.
    resp2 = await c.post("/api/bot/mode", json={"mode": "live", "scope": "global"})
    assert resp2.status_code == 200
    assert (await c.get("/api/bot/status")).json()["global_mode"] == "live"


async def test_api_gate_endpoint_reports_status(client) -> None:
    c, factory = client
    async with factory() as s:
        await _make_strategy(s)
        await s.commit()
    body = (await c.get("/api/bot/gate")).json()
    assert body["passed"] is False
    assert "metrics" in body


# ── Layer 5: engine reachability — the technical closure ─────────────────────
async def _factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/reach.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_engine_never_builds_live_wall_while_gate_closed(
    tmp_path, infra, monkeypatch
) -> None:
    """The live adapter is never even constructed while the gate is closed."""
    import app.execution.binance as binance_mod

    def _boom(*a, **k):  # constructing the live adapter here would be a leak of the path
        raise AssertionError("live adapter constructed while the gate was closed!")

    monkeypatch.setattr(binance_mod, "BinanceFuturesAdapter", _boom)

    factory = await _factory(tmp_path)
    async with factory() as s:
        await _make_strategy(s)  # no trades ⇒ gate closed
        await _enable_infra(s)   # infra ready, but the record is not
        await s.commit()

    engine = BotEngine(factory, killswitch=KillSwitch(tmp_path / "KILLSWITCH"))
    await engine.tick()  # must not raise → adapter was never constructed
    assert engine._live_risk is None


async def test_engine_arms_live_wall_when_gate_open(tmp_path, infra, monkeypatch) -> None:
    """Positive control: with the gate open, the wall arms (via a stub adapter)."""
    import app.execution.binance as binance_mod

    class StubLive:
        mode = "live"
        testnet = True

        def __init__(self, *a, **k):
            StubLive.built += 1

        def get_positions(self):
            return []

        def get_balance(self):
            from app.execution.base import Balance

            return Balance(equity=1000.0, cash=1000.0, unrealized_pnl=0.0)

    StubLive.built = 0
    monkeypatch.setattr(binance_mod, "BinanceFuturesAdapter", StubLive)

    factory = await _factory(tmp_path)
    async with factory() as s:
        await _make_strategy(s)
        await _seed_passing(s)
        await _enable_infra(s)
        await s.commit()

    engine = BotEngine(factory, killswitch=KillSwitch(tmp_path / "KILLSWITCH"))
    await engine.tick()
    assert StubLive.built == 1
    assert engine._live_risk is not None
