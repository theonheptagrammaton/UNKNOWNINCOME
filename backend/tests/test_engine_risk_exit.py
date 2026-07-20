"""Volatility stop/target exits (doc §7 Aşama 3): hand-computed long/short cases.

``atr_length=1`` makes ATR equal the bar's true range, so the stop/target band is
exact by hand. The trigger is read at bar *close* and filled at the next open —
the same lookahead-safe contract as a signal exit (rule #1).
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtest.config import CapitalConfig, CostConfig, RiskExitConfig
from app.backtest.engine import run_engine

TF_MS = 3_600_000  # 1h


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Explicit OHLC bars ``(open, high, low, close)`` (volume constant)."""
    return pd.DataFrame(
        {
            "ts": [i * TF_MS for i in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [100.0] * len(rows),
        }
    )


def _sig(n: int, **flags: list[int]) -> dict[str, pd.Series]:
    out = {}
    for name in ("long_entry", "long_exit", "short_entry", "short_exit"):
        idx = set(flags.get(name, []))
        out[name] = pd.Series([i in idx for i in range(n)])
    return out


def _no_costs() -> CostConfig:
    return CostConfig(
        commission_bps=0.0, slippage_model="fixed_bps", slippage_bps=0.0,
        funding_enabled=False,
    )


def _cap(cash: float = 1100.0) -> CapitalConfig:
    # Fixed sizing keeps qty a clean 10 so the stop/target exits are hand-checkable;
    # ATR-risk sizing (the new default) is exercised in test_sizing.py.
    return CapitalConfig(initial_cash=cash, sizing="fixed", size_pct=1.0, leverage=1.0)


def test_long_atr_target_exit_hand_computed() -> None:
    # bar0 TR=2 → ATR(entry)=2; enter long @open[1]=110; target=110+2·2=114.
    ohlcv = _frame([
        (100, 101, 99, 100),   # ATR seed: TR = 2
        (110, 112, 108, 111),  # entry fill = 110; close 111 < 114 → no hit
        (112, 116, 111, 115),  # close 115 ≥ 114 → target hit at this close
        (118, 119, 117, 118),  # exit fills here at open = 118
        (120, 121, 119, 120),
    ])
    signals = _sig(5, long_entry=[0])
    risk = RiskExitConfig(atr_target_mult=2.0, atr_length=1)
    result = run_engine(ohlcv, signals, _no_costs(), _cap(1100.0), None, risk)

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.side == "long"
    assert t.entry_price == pytest.approx(110.0)
    assert t.exit_price == pytest.approx(118.0)  # next open after the close hit
    assert t.forced is False
    assert t.gross_pnl == pytest.approx(10 * (118 - 110))
    assert result.equity[-1] == pytest.approx(1180.0)


def test_long_atr_stop_exit_hand_computed() -> None:
    # Enter long @110; stop = 110 − 2·2 = 106; close 105 ≤ 106 → stop hit.
    ohlcv = _frame([
        (100, 101, 99, 100),
        (110, 111, 104, 105),  # entry fill = 110; close 105 ≤ 106 → stop hit
        (103, 104, 102, 103),  # exit fills here at open = 103
        (102, 103, 101, 102),
    ])
    signals = _sig(4, long_entry=[0])
    risk = RiskExitConfig(atr_stop_mult=2.0, atr_length=1)
    result = run_engine(ohlcv, signals, _no_costs(), _cap(1100.0), None, risk)

    t = result.trades[0]
    assert t.exit_price == pytest.approx(103.0)
    assert t.gross_pnl == pytest.approx(10 * (103 - 110))  # −70
    assert result.equity[-1] == pytest.approx(1030.0)


def test_short_atr_target_exit_hand_computed() -> None:
    # Enter short @110; target = 110 − 2·2 = 106; close 105 ≤ 106 → target hit.
    ohlcv = _frame([
        (100, 101, 99, 100),
        (110, 112, 104, 105),  # entry fill = 110; close 105 ≤ 106 → target hit
        (104, 105, 103, 104),  # exit fills here at open = 104
        (103, 104, 102, 103),
    ])
    signals = _sig(4, short_entry=[0])
    risk = RiskExitConfig(atr_target_mult=2.0, atr_length=1)
    result = run_engine(ohlcv, signals, _no_costs(), _cap(1100.0), None, risk)

    t = result.trades[0]
    assert t.side == "short"
    assert t.exit_price == pytest.approx(104.0)
    # short gross = −qty·(exit − entry) = −10·(104 − 110) = +60
    assert t.gross_pnl == pytest.approx(60.0)
    assert result.equity[-1] == pytest.approx(1160.0)


def test_risk_exit_disabled_by_default_holds_to_final() -> None:
    """No risk_exit ⇒ position runs to the forced final-bar mark-out (Phase-3 behavior)."""
    ohlcv = _frame([
        (100, 101, 99, 100),
        (110, 112, 108, 100),  # deep intrabar move, but no stop configured
        (100, 101, 99, 100),
        (130, 131, 129, 130),
    ])
    signals = _sig(4, long_entry=[0])  # never exits
    result = run_engine(ohlcv, signals, _no_costs(), _cap(1100.0))
    assert len(result.trades) == 1
    assert result.trades[0].forced is True
    assert result.trades[0].exit_price == pytest.approx(130.0)  # final close
