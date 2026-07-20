"""The shared sizing/liquidation model + the backtest↔live equivalence it guarantees.

The whole point of :mod:`app.execution.sizing` is that a backtest and the live risk
wall size a position *identically* — the root cause of "profitable in backtest, loses
live" was that they didn't. These tests pin the arithmetic and prove the two callers
(the engine and :class:`RiskLayer`) agree, plus the isolated-margin liquidation model.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtest.config import CapitalConfig, CostConfig, RiskExitConfig
from app.backtest.engine import _atr, run_engine
from app.execution.paper import PaperAdapter
from app.execution.risk import RiskLayer, RiskLimits, TradeIntent
from app.execution.sizing import liquidation_price, position_size

TF_MS = 3_600_000


# ── position_size ─────────────────────────────────────────────────────────────
def test_atr_sizing_risks_fixed_fraction_to_stop() -> None:
    # Risk 1% of 10_000 = 100; stop 2.0 away ⇒ qty = 100 / 2 = 50 (well under margin cap).
    qty = position_size(
        equity=10_000, price=100, leverage=5, sizing="atr",
        per_trade_pct=1.0, stop_distance=2.0,
    )
    assert qty == pytest.approx(50.0)


def test_atr_sizing_capped_by_margin() -> None:
    # Tiny stop would ask for a huge qty; margin caps it at equity·lev/price = 500.
    qty = position_size(
        equity=10_000, price=100, leverage=5, sizing="atr",
        per_trade_pct=1.0, stop_distance=0.01,
    )
    assert qty == pytest.approx(500.0)  # (10_000·5)/100


def test_atr_sizing_without_stop_is_zero() -> None:
    # No stop ⇒ no ATR risk basis ⇒ no trade (never silently oversize on warm-up).
    assert position_size(
        equity=10_000, price=100, leverage=5, sizing="atr",
        per_trade_pct=1.0, stop_distance=None,
    ) == 0.0


def test_fixed_sizing_matches_legacy_formula() -> None:
    # Legacy Phase-3 behaviour: deploy fixed_fraction of equity as levered notional.
    qty = position_size(
        equity=1100, price=110, leverage=1, sizing="fixed",
        fixed_fraction=1.0, stop_distance=None,
    )
    assert qty == pytest.approx(10.0)  # 1100·1·1 / 110


# ── liquidation_price ─────────────────────────────────────────────────────────
def test_liquidation_price_long_short() -> None:
    # lev 5, mm 0.005 ⇒ adverse frac = 0.2 − 0.005 = 0.195.
    assert liquidation_price(100, +1, 5, 0.005) == pytest.approx(80.5)
    assert liquidation_price(100, -1, 5, 0.005) == pytest.approx(119.5)


def test_no_liquidation_at_low_leverage() -> None:
    assert liquidation_price(100, +1, 1.0) is None  # 1x ⇒ effectively unreachable


# ── engine ↔ RiskLayer equivalence (the A1 proof) ─────────────────────────────
def _atr_ohlcv(n: int = 40) -> pd.DataFrame:
    """A gently trending series with room for ATR to warm up and a stop to sit."""
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "ts": [i * TF_MS for i in range(n)],
            "open": closes,
            "high": [c + 2 for c in closes],
            "low": [c - 2 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


def _no_costs() -> CostConfig:
    return CostConfig(commission_bps=0.0, slippage_bps=0.0, funding_enabled=False)


def test_engine_and_risklayer_size_identically() -> None:
    ohlcv = _atr_ohlcv(40)
    n = len(ohlcv)
    sig = {
        "long_entry": pd.Series([i == 20 for i in range(n)]),
        "long_exit": pd.Series([i == 30 for i in range(n)]),
        "short_entry": pd.Series([False] * n),
        "short_exit": pd.Series([False] * n),
    }
    cap = CapitalConfig(initial_cash=10_000, sizing="atr", per_trade_pct=1.0, leverage=3.0)
    risk_exit = RiskExitConfig(atr_stop_mult=2.0, atr_length=14)
    result = run_engine(ohlcv, sig, _no_costs(), cap, None, risk_exit)
    assert len(result.trades) == 1
    trade = result.trades[0]

    # Recompute the ATR-at-signal the engine sized against (signal bar = entry_index − 1).
    atr = _atr(
        ohlcv["high"].to_numpy("float64"),
        ohlcv["low"].to_numpy("float64"),
        ohlcv["close"].to_numpy("float64"),
        14,
    )
    stop_dist = 2.0 * atr[trade.entry_index - 1]
    expected = position_size(
        equity=10_000, price=trade.entry_price, leverage=3.0, sizing="atr",
        per_trade_pct=1.0, stop_distance=stop_dist,
    )
    assert trade.qty == pytest.approx(expected)

    # The live risk wall, given the same inputs, sizes to the same qty.
    layer = RiskLayer(PaperAdapter(10_000), RiskLimits(), mode="paper")
    intent = TradeIntent(
        strategy_version_id="v", symbol="BTCUSDT", action="open_long",
        reference_price=trade.entry_price, ts=0, atr=atr[trade.entry_index - 1],
        stop_distance=stop_dist, leverage=3.0, sizing="atr", per_trade_pct=1.0,
    )
    decision = layer.evaluate(intent)
    assert decision.approved
    assert decision.qty == pytest.approx(trade.qty)


def test_leveraged_position_liquidates_instead_of_recovering() -> None:
    # Long at ~100 with 5x; price craters to 50 then recovers. Isolated margin is gone
    # at ~80.5 — the trade must be liquidated there, and equity must never go negative.
    closes = [100, 100, 100, 100, 50, 60, 90, 100]
    ohlcv = pd.DataFrame(
        {
            "ts": [i * TF_MS for i in range(len(closes))],
            "open": [float(c) for c in closes],
            "high": [float(c) + 1 for c in closes],
            "low": [float(c) - 1 for c in closes],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * len(closes),
        }
    )
    n = len(closes)
    sig = {
        "long_entry": pd.Series([i == 0 for i in range(n)]),
        "long_exit": pd.Series([False] * n),
        "short_entry": pd.Series([False] * n),
        "short_exit": pd.Series([False] * n),
    }
    cap = CapitalConfig(initial_cash=10_000, sizing="fixed", size_pct=1.0, leverage=5.0)
    result = run_engine(ohlcv, sig, _no_costs(), cap, None, None)
    assert any(t.liquidated for t in result.trades)
    assert min(result.equity) >= 0.0
