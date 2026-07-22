"""Limit-entry path (doc §26.3): the resolver, the router's T-second timeout → market
fallback (KABUL #3), and the backtest's maker/taker split as a separate line item."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest.config import CapitalConfig, CostConfig
from app.backtest.engine import run_engine
from app.execution.base import OrderRequest
from app.execution.limit import LimitAction, LimitOrderRouter, resolve_limit
from app.execution.paper import PaperAdapter


# ── resolver (pure) ────────────────────────────────────────────────────────────
def test_resolve_limit_states() -> None:
    # Buy limit at 99, price 100 → not marketable, still inside the window → REST.
    assert resolve_limit("buy", 99.0, 0, 5_000, 3_000, 100.0) is LimitAction.REST
    # Price falls to the limit → maker fill.
    assert resolve_limit("buy", 99.0, 0, 5_000, 3_000, 99.0) is LimitAction.FILL_MAKER
    # Timeout elapsed without a fill → market fallback.
    assert resolve_limit("buy", 99.0, 0, 5_000, 6_000, 100.0) is LimitAction.FALLBACK_MARKET
    # Sell limit at 101 fills once price rises to it.
    assert resolve_limit("sell", 101.0, 0, 5_000, 1_000, 101.5) is LimitAction.FILL_MAKER


# ── router: T-second timeout → market fallback (KABUL #3) ──────────────────────
def _limit_req(side="buy", limit_price=99.0, timeout_s=5.0) -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDT", side=side, qty=1.0, order_type="limit",
        reference_price=100.0, limit_price=limit_price, timeout_s=timeout_s,
        leverage=1.0, client_id="c1", commission_bps=4.0, slippage_bps=5.0,
    )


def test_router_rests_then_falls_back_to_market_on_timeout() -> None:
    adapter = PaperAdapter(initial_cash=100_000.0)
    router = LimitOrderRouter(adapter, maker_fee_bps=2.0)

    # Buy limit below market → not immediately marketable → rests (no fill yet).
    res = router.submit(_limit_req(), now_ts=0, current_price=100.0)
    assert res is None
    assert "c1" in router.resting

    # Still inside the timeout window → nothing happens.
    assert router.poll(now_ts=3_000, price_by_symbol={"BTCUSDT": 100.0}) == []
    assert "c1" in router.resting

    # Past the 5s timeout, still unfilled → market (taker) fallback executes on the adapter.
    out = router.poll(now_ts=6_000, price_by_symbol={"BTCUSDT": 100.0})
    assert len(out) == 1
    key, outcome, result = out[0]
    assert key == "c1" and outcome == "market_fallback"
    assert result.accepted and result.status == "filled"
    assert "c1" not in router.resting  # no longer resting
    # A market fallback pays the taker commission and takes slippage (fill ≠ 100 exactly).
    assert result.fill.commission > 0 and result.fill.price != 100.0


def test_router_maker_fill_when_immediately_marketable() -> None:
    adapter = PaperAdapter(initial_cash=100_000.0)
    router = LimitOrderRouter(adapter, maker_fee_bps=2.0)
    # Buy limit at/above market → marketable now → maker fill at the limit price, no slip.
    res = router.submit(_limit_req(limit_price=101.0), now_ts=0, current_price=100.0)
    assert res is not None and res.accepted
    assert res.fill.price == 101.0  # filled at the limit, zero slippage
    assert res.fill.slippage_cost == 0.0
    assert not router.resting


# ── backtest maker/taker split (doc §26.3) ─────────────────────────────────────
def _frame(rows: list[list[float]]) -> pd.DataFrame:
    arr = np.array(rows, dtype="float64")
    return pd.DataFrame({"ts": np.arange(len(rows)) * 3_600_000,
                         "open": arr[:, 0], "high": arr[:, 1],
                         "low": arr[:, 2], "close": arr[:, 3],
                         "volume": np.full(len(rows), 1_000_000.0)})


def _one_entry_signals(n: int, at: int = 5) -> dict[str, pd.Series]:
    le = np.zeros(n, dtype=bool)
    le[at] = True
    z = np.zeros(n, dtype=bool)
    return {"long_entry": pd.Series(le), "long_exit": pd.Series(z),
            "short_entry": pd.Series(z), "short_exit": pd.Series(z)}


def test_backtest_limit_entry_maker_when_range_reaches_limit() -> None:
    # Flat price; every fill bar's range straddles the previous close → maker fill.
    rows = [[100.0, 100.5, 99.5, 100.0] for _ in range(12)]
    df = _frame(rows)
    costs = CostConfig(slippage_model="fixed_bps", slippage_bps=5.0, funding_enabled=False,
                       limit_entry_enabled=True, maker_fee_bps=2.0, commission_bps=4.0)
    cap = CapitalConfig(sizing="fixed", size_pct=0.5, leverage=1.0)
    r = run_engine(df, _one_entry_signals(len(rows)), costs, cap)
    cb = r.cost_breakdown
    assert cb["limit_entry"] is True
    assert cb["maker_entries"] == 1 and cb["taker_entries"] == 0
    assert cb["maker_commission"] > 0 and cb["taker_commission"] == 0.0


def test_backtest_limit_entry_taker_fallback_when_price_gaps_away() -> None:
    # The fill bar (index 6) gaps up above the signal-bar close (100) → limit unreachable
    # → market (taker) fallback, the adverse-selection case (doc §26.3).
    rows = [[100.0, 100.5, 99.5, 100.0] for _ in range(6)]
    rows.append([102.0, 103.0, 101.0, 102.0])  # index 6: opens/stays above 100
    rows += [[102.0, 102.5, 101.5, 102.0] for _ in range(5)]
    df = _frame(rows)
    costs = CostConfig(slippage_model="fixed_bps", slippage_bps=5.0, funding_enabled=False,
                       limit_entry_enabled=True, maker_fee_bps=2.0, commission_bps=4.0)
    cap = CapitalConfig(sizing="fixed", size_pct=0.5, leverage=1.0)
    r = run_engine(df, _one_entry_signals(len(rows)), costs, cap)
    cb = r.cost_breakdown
    assert cb["taker_entries"] == 1 and cb["maker_entries"] == 0
    assert cb["taker_commission"] > 0
