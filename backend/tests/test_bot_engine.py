"""Paper bot engine: reason+snapshot, fills, hot-reload, risk block, soak (§9, §10.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.engine import BotEngine
from app.bot.killswitch import KillSwitch
from app.bot.mode import set_global_mode
from app.core.config import settings
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.execution.risk import RiskLimits
from app.models.base import Base
from app.models.risk import RiskEvent
from app.models.trading import EquitySnapshot, Order, Signal, Trade
from app.strategy import service
from fakes import make_wave_ohlcv

MARKET, SYMBOL, TF = "binance_usdm", "BTCUSDT", "1h"
CLOCK_MS = 1_700_000_000_000


def _clock() -> int:
    return CLOCK_MS


def _genome(name="AlwaysLong", exit_always=False) -> dict:
    exit_rule = (
        [{"primitive": "regime", "args": {"x": "ema", "rule": "gt:0"}}] if exit_always else []
    )
    return {
        "name": name,
        "config": {
            "market": MARKET, "symbol": SYMBOL, "tf": TF, "direction": "long",
            "indicators": [{"key": "ema", "id": "ema", "params": {"timeperiod": 9}}],
            "rules": {
                "long_entry": [{"primitive": "regime", "args": {"x": "ema", "rule": "gt:0"}}],
                "long_exit": exit_rule, "short_entry": [], "short_exit": [],
            },
            "costs": {"funding_enabled": False},
            # Fixed 20% notional: deterministic and within the Phase-10 portfolio
            # caps (net symbol ≤ 35%, gross ≤ 3x) so these plumbing tests exercise the
            # engine, not the portfolio gate (which has its own tests).
            "capital": {
                "initial_cash": 10_000, "sizing": "fixed", "size_pct": 0.2, "leverage": 1.0,
            },
        },
    }


async def _factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/bot.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_strategy(factory, genome, *, global_mode="paper", strat_mode="paper"):
    async with factory() as s:
        strat, v = await service.create_strategy(s, genome)
        await service.set_mode(s, strat.id, strat_mode)
        await set_global_mode(s, global_mode)
        await s.commit()
        return strat.id, v.id


@pytest.fixture
def _data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(200, TF, seed=7)))
    return tmp_path


async def test_signal_has_reason_and_indicator_snapshot(_data, monkeypatch) -> None:
    factory = await _factory(_data)
    await _seed_strategy(factory, _genome())
    engine = BotEngine(factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"))

    report = await engine.tick()
    assert report.signals == 1 and report.orders == 1

    async with factory() as s:
        sig = (await s.execute(select(Signal))).scalars().one()
        assert sig.action == "open_long"
        assert sig.reason  # pazarlıksız: never empty
        assert sig.reason["long_entry"][0]["primitive"] == "regime"
        assert sig.indicator_snapshot.get("ema") is not None
        assert sig.indicator_snapshot.get("close") is not None
        assert sig.outcome == "filled"

        trade = (await s.execute(select(Trade))).scalars().one()
        assert trade.status == "open" and trade.side == "long"
        order = (await s.execute(select(Order))).scalars().one()
        assert order.status == "filled"
        assert (await s.execute(select(EquitySnapshot))).scalars().first() is not None


async def test_genome_hot_reload_without_restart(_data) -> None:
    factory = await _factory(_data)
    strat_id, _ = await _seed_strategy(factory, _genome("v1-entry"))
    engine = BotEngine(factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"))

    await engine.tick()  # opens the long under v1
    async with factory() as s:
        assert (await s.execute(select(Trade).where(Trade.status == "open"))).scalars().one()

    # Edit the genome → new active version. Same engine instance, no restart.
    async with factory() as s:
        await service.add_version(s, strat_id, _genome("v2-exit", exit_always=True))
        await s.commit()

    await engine.tick()  # v2 says exit → position closes with the NEW genome
    async with factory() as s:
        trades = (await s.execute(select(Trade))).scalars().all()
        assert trades[0].status == "closed"
        actions = [x.action for x in (await s.execute(select(Signal))).scalars().all()]
        assert "close_long" in actions


async def test_risk_limit_blocks_order_and_records_event(_data) -> None:
    factory = await _factory(_data)
    await _seed_strategy(factory, _genome())
    engine = BotEngine(
        factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"),
        limits=RiskLimits(max_concurrent_positions=0),  # forbid any new position
    )
    report = await engine.tick()
    assert report.rejected == 1 and report.orders == 0

    async with factory() as s:
        sig = (await s.execute(select(Signal))).scalars().one()
        assert sig.outcome == "rejected"
        events = (await s.execute(select(RiskEvent))).scalars().all()
        assert any(e.type == "max_positions" for e in events)
        assert (await s.execute(select(Trade))).scalars().first() is None


async def test_off_mode_does_not_trade(_data) -> None:
    factory = await _factory(_data)
    await _seed_strategy(factory, _genome(), global_mode="off", strat_mode="paper")
    engine = BotEngine(factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"))
    report = await engine.tick()
    assert report.signals == 0
    async with factory() as s:
        assert (await s.execute(select(Signal))).scalars().first() is None


async def test_multi_cycle_soak_is_stable(_data) -> None:
    """Local soak proxy: many cycles run without crashing, equity curve stays continuous."""
    factory = await _factory(_data)
    await _seed_strategy(factory, _genome())
    engine = BotEngine(
        factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"),
        tick_seconds=0.0, kill_poll_seconds=0.0,
    )

    async def _sleep(_seconds: float) -> None:
        return None

    ticks = await engine.run(stop=lambda: False, sleep=_sleep, max_ticks=50)
    assert ticks == 50
    async with factory() as s:
        snaps = (await s.execute(select(EquitySnapshot))).scalars().all()
        assert len(snaps) == 50
        assert all(x.equity > 0 for x in snaps)
