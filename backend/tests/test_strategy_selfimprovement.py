"""Self-improvement end-to-end (doc §8.3–8.5, §15/Faz-6 acceptance).

Covers the three hard acceptance criteria:
* degradation ⇒ auto-pause + a pending version with a report + a notification,
* an unapproved version never trades,
* the weekly scheduler runs (shortened interval) and produces pending versions.
Plus the human-approved terfi kapısı (approve/reject).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.engine import BotEngine
from app.bot.killswitch import KillSwitch
from app.bot.mode import set_global_mode
from app.bot.notifier import NullNotifier
from app.core.config import settings
from app.core.settings_store import KEY_REGIME_LOCK, set_setting
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.models.base import Base
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Signal
from app.strategy import regen, service
from app.strategy.health import DegradeVerdict
from app.strategy.scheduler import run_scheduled_reopt
from fakes import make_wave_ohlcv

MARKET, SYMBOL, TF = "binance_usdm", "BTCUSDT", "1h"
CLOCK_MS = 1_700_000_000_000


def _clock() -> int:
    return CLOCK_MS


def _genome(name: str = "Subject") -> dict:
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
def _data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(400, TF, seed=7)))
    return tmp_path


async def _factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/si.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(factory, *, mode="paper", global_mode="paper"):
    async with factory() as s:
        strat, v = await service.create_strategy(s, _genome())
        await service.set_mode(s, strat.id, mode)
        await set_global_mode(s, global_mode)
        await s.commit()
        return strat.id, v.id


# ── §8.5: degradation → pause + pending version + notify (end-to-end) ─────────
async def test_degradation_pauses_and_drops_pending_version(_data) -> None:
    factory = await _factory(_data)
    strat_id, v1_id = await _seed(factory)
    notifier = NullNotifier()
    verdict = DegradeVerdict(
        degraded=True, triggers=["rolling_pf"], num_trades=30,
        rolling_pf=0.5, realized_max_drawdown=0.2, mc_p95_drawdown=0.05,
    )

    async with factory() as s:
        new_version = await regen.degrade_and_regenerate(
            s, strat_id, verdict=verdict, reason="degrade:rolling_pf",
            trials=4, notifier=notifier,
        )
        await s.commit()

    assert new_version is not None
    async with factory() as s:
        strat = await s.get(Strategy, strat_id)
        pending = await s.get(StrategyVersion, new_version.id)
        # Paused, pending version stored with a report, active pointer UNCHANGED.
        assert strat.mode == "off"
        assert pending.status == "pending_approval"
        assert pending.wfo_report and "monte_carlo" in pending.wfo_report
        assert strat.active_version_id == v1_id

    joined = "\n".join(notifier.sent)
    assert "degradation detected" in joined  # pause notice
    assert "awaiting approval" in joined  # approval-needed notice


# ── §8.5: an unapproved version NEVER trades ─────────────────────────────────
async def test_unapproved_version_never_trades(_data) -> None:
    factory = await _factory(_data)
    strat_id, v1_id = await _seed(factory)
    engine = BotEngine(
        factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"),
        monitor_degradation=False,
    )
    await engine.tick()  # trades under the active v1

    # Store a self-generated version WITHOUT activating it.
    async with factory() as s:
        pending = await service.add_version(
            s, strat_id, _genome("proposed"), status="pending_approval",
            activate=False, regime=None,
        )
        await s.commit()
        pending_id = pending.id

    async with factory() as s:
        strat = await s.get(Strategy, strat_id)
        assert strat.active_version_id == v1_id  # pointer never moved

    # Defense in depth: even if the pointer *did* point at a pending version,
    # the engine must skip it (status guard).
    async with factory() as s:
        strat = await s.get(Strategy, strat_id)
        strat.active_version_id = pending_id
        await s.commit()
    await engine.tick()

    async with factory() as s:
        sigs = (await s.execute(select(Signal))).scalars().all()
        assert all(sig.strategy_version_id != pending_id for sig in sigs)


# ── §8.5: human-approved terfi kapısı ────────────────────────────────────────
async def test_approve_activates_pending_in_paper(_data) -> None:
    factory = await _factory(_data)
    strat_id, v1_id = await _seed(factory, mode="off")
    async with factory() as s:
        pending = await service.add_version(
            s, strat_id, _genome("v2"), status="pending_approval", activate=False, regime=None
        )
        await s.commit()
        pending_id = pending.id

    async with factory() as s:
        await service.approve_version(s, strat_id, pending_id, actor="ui")
        await s.commit()

    async with factory() as s:
        strat = await s.get(Strategy, strat_id)
        version = await s.get(StrategyVersion, pending_id)
        assert strat.active_version_id == pending_id  # activated (hot-reload)
        assert version.status == "paper"  # runs in paper
        assert strat.mode == "paper"  # resumed


async def test_reject_retires_pending_keeps_active(_data) -> None:
    factory = await _factory(_data)
    strat_id, v1_id = await _seed(factory, mode="off")
    async with factory() as s:
        pending = await service.add_version(
            s, strat_id, _genome("v2"), status="pending_approval", activate=False, regime=None
        )
        await s.commit()
        pending_id = pending.id

    async with factory() as s:
        await service.reject_version(s, strat_id, pending_id, actor="ui")
        await s.commit()

    async with factory() as s:
        strat = await s.get(Strategy, strat_id)
        version = await s.get(StrategyVersion, pending_id)
        assert version.status == "retired"
        assert strat.active_version_id == v1_id  # active untouched
        assert strat.mode == "off"  # stays paused


# ── §8.3 v1: the weekly scheduler runs (shortened) + de-dupes ────────────────
async def test_scheduler_produces_pending_versions(_data, monkeypatch) -> None:
    monkeypatch.setattr(settings, "reopt_trials", 3)  # shortened for the local run
    factory = await _factory(_data)
    strat_id, v1_id = await _seed(factory)

    produced = await run_scheduled_reopt(factory, NullNotifier())
    assert len(produced) == 1

    async with factory() as s:
        strat = await s.get(Strategy, strat_id)
        pend = (
            await s.execute(
                select(StrategyVersion).where(
                    StrategyVersion.strategy_id == strat_id,
                    StrategyVersion.status == "pending_approval",
                )
            )
        ).scalars().all()
        assert len(pend) == 1
        assert strat.active_version_id == v1_id  # scheduler never activates

    # Running again must NOT pile up a second proposal.
    again = await run_scheduled_reopt(factory, NullNotifier())
    assert again == []


# ── §8.4: regime gate runs only the matching pool (manual lock) ──────────────
async def test_regime_gate_filters_pool(_data) -> None:
    factory = await _factory(_data)
    strat_id, v1_id = await _seed(factory)
    engine = BotEngine(
        factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"),
        monitor_degradation=False,
    )

    async def _set_regime(regime: str | None, lock: str) -> None:
        async with factory() as s:
            v = await s.get(StrategyVersion, v1_id)
            v.regime = regime
            await set_setting(s, KEY_REGIME_LOCK, {"mode": lock})
            await s.commit()

    # Labelled "range" but the desk is locked to "trend" ⇒ gated out (no signals).
    await _set_regime("range/low", "trend")
    report = await engine.tick()
    assert report.evaluated == 0
    async with factory() as s:
        assert (await s.execute(select(Signal))).scalars().first() is None

    # Regime now matches the lock ⇒ it runs.
    await _set_regime("trend/high", "trend")
    report = await engine.tick()
    assert report.evaluated == 1
    async with factory() as s:
        assert (await s.execute(select(Signal))).scalars().first() is not None


async def test_unlabelled_and_off_lock_always_run(_data) -> None:
    factory = await _factory(_data)
    strat_id, v1_id = await _seed(factory)
    engine = BotEngine(
        factory, clock=_clock, killswitch=KillSwitch(_data / "KILLSWITCH"),
        monitor_degradation=False,
    )
    # Unlabelled version is always eligible even under a lock (never starve the pool).
    async with factory() as s:
        v = await s.get(StrategyVersion, v1_id)
        v.regime = None
        await set_setting(s, KEY_REGIME_LOCK, {"mode": "range"})
        await s.commit()
    assert (await engine.tick()).evaluated == 1
