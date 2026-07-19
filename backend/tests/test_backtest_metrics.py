"""Metric set (§6.3) + composite score (§6.4) against independent computation."""

from __future__ import annotations

import numpy as np
import pytest

from app.backtest.engine import BacktestResult, Trade
from app.backtest.metrics import composite_score, compute_metrics

TF_MS = 3_600_000  # 1h


def _trade(net_pnl: float, ret: float, side: str = "long") -> Trade:
    return Trade(
        side=side, entry_ts=0, exit_ts=TF_MS, entry_index=0, exit_index=1,
        entry_price=100.0, exit_price=100.0 + net_pnl, qty=1.0, bars_held=1,
        gross_pnl=net_pnl, commission=0.0, funding=0.0, slippage_cost=0.0,
        net_pnl=net_pnl, return_pct=ret, forced=False,
    )


def _result(
    equity: list[float], position: list[int], trades: list[Trade], step_ms: int = TF_MS
) -> BacktestResult:
    return BacktestResult(
        ts=[i * step_ms for i in range(len(equity))],
        equity=equity,
        position=position,
        trades=trades,
        initial_cash=equity[0],
    )


def test_core_metrics_match_manual() -> None:
    equity = [100.0, 120.0, 90.0, 110.0]
    position = [1, 1, 0, 1]
    trades = [_trade(10.0, 0.10), _trade(20.0, 0.20), _trade(-5.0, -0.05)]
    m = compute_metrics(_result(equity, position, trades), "1h")

    assert m["net_return"] == pytest.approx(0.10)  # 110/100 − 1
    assert m["max_drawdown"] == pytest.approx(0.25)  # 90/120 − 1
    assert m["max_drawdown_bars"] == 2
    assert m["num_trades"] == 3
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert m["profit_factor"] == pytest.approx(30 / 5)  # wins 30 / losses 5
    assert m["expectancy"] == pytest.approx(25 / 3)  # (10+20−5)/3
    assert m["avg_win_loss"] == pytest.approx(15 / 5)  # avg win 15 / avg loss 5
    assert m["exposure"] == pytest.approx(3 / 4)  # 3 of 4 bars in a position


def test_sharpe_matches_numpy() -> None:
    equity = [100.0, 101.0, 103.0, 102.0, 105.0, 108.0]
    m = compute_metrics(_result(equity, [1] * 6, [_trade(8.0, 0.08)]), "1h")
    eq = np.array(equity)
    rets = eq[1:] / eq[:-1] - 1.0
    bars_per_year = (365.25 * 24 * 3600 * 1000.0) / TF_MS
    expected = rets.mean() / rets.std(ddof=1) * np.sqrt(bars_per_year)
    assert m["sharpe"] == pytest.approx(expected)


def test_profit_factor_none_when_no_losses() -> None:
    m = compute_metrics(
        _result([100.0, 110.0], [1, 1], [_trade(10.0, 0.10)]), "1h"
    )
    assert m["profit_factor"] is None  # no losses ⇒ infinite ⇒ JSON null


def test_monthly_returns_present() -> None:
    # 90 daily bars ⇒ ~3 monthly buckets.
    n = 90
    day_ms = 86_400_000
    equity = [100.0 + i for i in range(n)]
    m = compute_metrics(_result(equity, [1] * n, [_trade(1.0, 0.01)], day_ms), "1d")
    assert len(m["monthly_returns"]) >= 3
    assert set(m["monthly_returns"][0]) == {"year", "month", "return"}


def test_composite_score_bounds_and_hard_filters() -> None:
    strong = {
        "sharpe": 3.0, "profit_factor": 3.0, "max_drawdown": 0.0,
        "win_rate": 1.0, "expectancy_pct": 0.2, "num_trades": 50,
    }
    s = composite_score(strong)
    assert 0.0 <= s["composite_score"] <= 1.0
    assert s["composite_score"] == pytest.approx(1.0, abs=1e-6)
    assert s["passes_hard_filters"] is True

    weak = {
        "sharpe": 0.0, "profit_factor": 0.9, "max_drawdown": 0.4,
        "win_rate": 0.2, "expectancy_pct": -0.01, "num_trades": 10,
    }
    w = composite_score(weak)
    assert 0.0 <= w["composite_score"] <= 1.0
    assert w["passes_hard_filters"] is False  # <30 trades, PF<1, DD>25%
