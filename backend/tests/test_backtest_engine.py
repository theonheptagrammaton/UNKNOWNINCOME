"""Engine arithmetic: hand-computed P&L, cost model, funding, lookahead timing.

These prove the §6.2 cost model and the close-signal → next-open-fill contract
with literal, by-hand numbers (KABUL: reference strategy matches hand computation;
lookahead: shifting the signal by one bar changes the result).
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtest.config import CapitalConfig, CostConfig
from app.backtest.engine import run_engine

TF_MS = 3_600_000  # 1h


def _ohlcv(opens: list[float], closes: list[float] | None = None) -> pd.DataFrame:
    n = len(opens)
    closes = closes if closes is not None else list(opens)
    return pd.DataFrame(
        {
            "ts": [i * TF_MS for i in range(n)],
            "open": [float(o) for o in opens],
            "high": [float(max(o, c)) + 1 for o, c in zip(opens, closes, strict=False)],
            "low": [float(min(o, c)) - 1 for o, c in zip(opens, closes, strict=False)],
            "close": [float(c) for c in closes],
            "volume": [100.0] * n,
        }
    )


def _sig(n: int, **flags: list[int]) -> dict[str, pd.Series]:
    """Boolean signal series from index lists, e.g. ``_sig(5, long_entry=[0])``."""
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
    return CapitalConfig(initial_cash=cash, size_pct=1.0, leverage=1.0)


def test_single_long_trade_hand_computed() -> None:
    # Enter at bar0 close → fill open[1]=110; exit at bar2 close → fill open[3]=120.
    ohlcv = _ohlcv([100, 110, 115, 120, 125])
    signals = _sig(5, long_entry=[0], long_exit=[2])
    result = run_engine(ohlcv, signals, _no_costs(), _cap(1100.0))

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.side == "long"
    assert t.entry_price == pytest.approx(110.0)
    assert t.exit_price == pytest.approx(120.0)
    assert t.qty == pytest.approx(10.0)  # 1100 / 110
    assert t.gross_pnl == pytest.approx(100.0)  # 10 · (120 − 110)
    assert t.net_pnl == pytest.approx(100.0)
    assert result.equity[-1] == pytest.approx(1200.0)


def test_commission_hand_computed() -> None:
    ohlcv = _ohlcv([100, 110, 115, 120, 125])
    signals = _sig(5, long_entry=[0], long_exit=[2])
    costs = CostConfig(
        commission_bps=10.0, slippage_model="fixed_bps", slippage_bps=0.0,
        funding_enabled=False,
    )
    result = run_engine(ohlcv, signals, costs, _cap(1100.0))

    t = result.trades[0]
    # entry comm = 0.001·10·110 = 1.1 ; exit comm = 0.001·10·120 = 1.2
    assert t.commission == pytest.approx(2.3)
    assert t.net_pnl == pytest.approx(97.7)  # 100 − 2.3
    assert result.equity[-1] == pytest.approx(1197.7)
    assert result.cost_breakdown["total_commission"] == pytest.approx(2.3)


def test_slippage_embedded_in_fills() -> None:
    ohlcv = _ohlcv([100, 110, 115, 120, 125])
    signals = _sig(5, long_entry=[0], long_exit=[2])
    costs = CostConfig(
        commission_bps=0.0, slippage_model="fixed_bps", slippage_bps=5.0,
        funding_enabled=False,
    )
    result = run_engine(ohlcv, signals, costs, _cap(1100.0))
    t = result.trades[0]
    # buy pays up: 110·1.0005 = 110.055 ; sell gets less: 120·0.9995 = 119.94
    assert t.entry_price == pytest.approx(110.055)
    assert t.exit_price == pytest.approx(119.94)
    assert t.slippage_cost == pytest.approx(110 * 5e-4 + 120 * 5e-4)


def test_funding_long_pays_short_receives() -> None:
    # Entry bar0→fill open[1]; settlement at ts[2] (inside hold); exit bar2→open[3].
    ohlcv = _ohlcv([100, 110, 115, 120, 125])
    funding = pd.DataFrame({"ts": [2 * TF_MS], "funding_rate": [0.01]})
    costs = CostConfig(
        commission_bps=0.0, slippage_model="fixed_bps", slippage_bps=0.0,
        funding_enabled=True,
    )

    long_sig = _sig(5, long_entry=[0], long_exit=[2])
    r_long = run_engine(ohlcv, long_sig, costs, _cap(1100.0), funding)
    t = r_long.trades[0]
    # long pays: −1·10·110·0.01 = −11
    assert t.funding == pytest.approx(-11.0)
    assert t.net_pnl == pytest.approx(89.0)  # 100 − 11
    assert r_long.equity[-1] == pytest.approx(1189.0)

    short_sig = _sig(5, short_entry=[0], short_exit=[2])
    r_short = run_engine(ohlcv, short_sig, costs, _cap(1100.0), funding)
    ts_ = r_short.trades[0]
    # short receives: +11 ; gross = −10·(120−110) = −100 ; net = −100 + 11
    assert ts_.side == "short"
    assert ts_.funding == pytest.approx(11.0)
    assert ts_.gross_pnl == pytest.approx(-100.0)
    assert ts_.net_pnl == pytest.approx(-89.0)


def test_open_position_marked_out_at_final_close() -> None:
    ohlcv = _ohlcv([100, 110, 115, 120, 130])
    signals = _sig(5, long_entry=[0])  # never exits
    result = run_engine(ohlcv, signals, _no_costs(), _cap(1100.0))
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.forced is True
    assert t.exit_price == pytest.approx(130.0)  # final close, no exit cost
    assert t.gross_pnl == pytest.approx(10 * (130 - 110))


def test_shifting_signal_by_one_bar_changes_result() -> None:
    """Lookahead guard: a signal one bar later fills at a different open → different P&L."""
    ohlcv = _ohlcv([100, 102, 104, 106, 108, 110, 112])
    base = _sig(7, long_entry=[1], long_exit=[4])
    shifted = _sig(7, long_entry=[2], long_exit=[5])  # every signal +1 bar
    r_base = run_engine(ohlcv, base, _no_costs(), _cap(1000.0))
    r_shift = run_engine(ohlcv, shifted, _no_costs(), _cap(1000.0))
    assert r_base.equity[-1] != r_shift.equity[-1]
    assert r_base.trades[0].entry_price != r_shift.trades[0].entry_price


def test_reversal_in_one_bar() -> None:
    # Long from bar0; at bar2 a short_entry both closes the long and opens a short.
    ohlcv = _ohlcv([100, 110, 120, 130, 140])
    signals = _sig(5, long_entry=[0], short_entry=[2])
    result = run_engine(ohlcv, signals, _no_costs(), _cap(1200.0))
    assert [t.side for t in result.trades] == ["long", "short"]
    assert result.trades[0].exit_index == result.trades[1].entry_index == 3
