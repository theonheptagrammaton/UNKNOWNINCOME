"""Degradation triggers (doc §8.5): rolling PF < 1.0 and MC 95% drawdown breach."""

from __future__ import annotations

from app.models.trading import Trade
from app.strategy.health import (
    DegradeConfig,
    evaluate_degradation,
    profit_factor,
    realized_max_drawdown,
)

STRAT = "strat-1"


def _pure_helpers_ok() -> None:
    assert profit_factor([1.0, 1.0, -1.0]) == 2.0
    assert profit_factor([1.0, 2.0]) is None  # no losses ⇒ undefined
    # equity 100 → 110 → 90 ⇒ peak 110, trough 90 ⇒ dd ≈ 0.1818
    dd = realized_max_drawdown([10.0, -20.0], 100.0)
    assert round(dd, 4) == round(20.0 / 110.0, 4)


def test_pure_helpers() -> None:
    _pure_helpers_ok()


async def _add_closed_trades(session, pnls: list[float], *, base_ts: int = 1_000) -> None:
    """Insert closed paper trades (chronological) for the strategy."""
    for i, pnl in enumerate(pnls):
        session.add(Trade(
            mode="paper", strategy_id=STRAT, strategy_version_id="v1", symbol="BTCUSDT",
            side="long", qty=1.0, entry_price=100.0, entry_ts=base_ts + i,
            exit_price=100.0 + pnl, exit_ts=base_ts + i + 1, pnl=pnl, status="closed",
        ))
    await session.flush()


async def test_rolling_pf_trigger(db_session) -> None:
    # 40 trades, net losing (PF < 1) with enough trades to clear min_trades.
    pnls = [-2.0, 1.0] * 20  # gains 20, losses 40 ⇒ PF 0.5
    await _add_closed_trades(db_session, pnls)
    cfg = DegradeConfig(rolling_window=30, min_trades=30, min_profit_factor=1.0)
    verdict = await evaluate_degradation(
        db_session, STRAT, wfo_report=None, initial_cash=10_000.0, config=cfg
    )
    assert verdict.degraded
    assert "rolling_pf" in verdict.triggers
    assert verdict.rolling_pf is not None and verdict.rolling_pf < 1.0


async def test_pf_trigger_needs_min_trades(db_session) -> None:
    # Losing but only a few trades ⇒ PF trigger must NOT fire yet.
    await _add_closed_trades(db_session, [-2.0, 1.0, -2.0])
    cfg = DegradeConfig(rolling_window=30, min_trades=30, min_profit_factor=1.0)
    verdict = await evaluate_degradation(
        db_session, STRAT, wfo_report=None, initial_cash=10_000.0, config=cfg
    )
    assert not verdict.degraded


async def test_monte_carlo_drawdown_trigger(db_session) -> None:
    # A deep realized drawdown that exceeds the report's 95% MC band.
    await _add_closed_trades(db_session, [100.0, -400.0, 50.0])  # deep mid drawdown
    report = {"monte_carlo": {"p95_max_drawdown": 0.02}}  # band = 2%
    cfg = DegradeConfig(rolling_window=30, min_trades=30, min_profit_factor=1.0)
    verdict = await evaluate_degradation(
        db_session, STRAT, wfo_report=report, initial_cash=10_000.0, config=cfg
    )
    assert verdict.degraded
    assert "mc_drawdown" in verdict.triggers
    assert verdict.mc_p95_drawdown == 0.02
    assert verdict.realized_max_drawdown > 0.02


async def test_healthy_strategy_not_degraded(db_session) -> None:
    await _add_closed_trades(db_session, [5.0, -1.0, 4.0, -1.0] * 10)  # PF = 40/20 = 2
    report = {"monte_carlo": {"p95_max_drawdown": 0.5}}  # generous band
    cfg = DegradeConfig(rolling_window=30, min_trades=30, min_profit_factor=1.0)
    verdict = await evaluate_degradation(
        db_session, STRAT, wfo_report=report, initial_cash=10_000.0, config=cfg
    )
    assert not verdict.degraded
    assert verdict.triggers == []
