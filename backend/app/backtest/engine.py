"""Lean vectorized backtest engine (doc §6.1 — owned core, vectorbt-ready seam).

Design contracts (pazarlıksız kurallar):

* **No lookahead (rule #1).** A signal is produced at bar *close* ``s``; the order
  it implies fills at the *next* bar's open ``s+1``. The engine never reads a bar
  to fill an order placed at or after it. Shifting the signal by one bar therefore
  changes the result — the acceptance test proves this.
* **Costs ON by default (rule #2).** Commission, slippage and funding are always
  applied; each is reported separately and any disabled component is flagged so
  the UI can red-tag a "costless" run.
* **Deterministic (rule #6).** Pure arithmetic over the input arrays — same config
  ⇒ bit-for-bit identical output. The ``seed`` is reserved for Monte Carlo (§6.5).

``run_engine`` is the single entry point; :class:`Engine` is the Protocol a future
vectorbt/backtesting.py engine implements to slot in behind the same seam.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from app.backtest.config import CapitalConfig, CostConfig, RiskExitConfig
from app.execution.sizing import liquidation_price, position_size


@dataclass
class Trade:
    """One realized round-trip. ``funding`` is signed (negative = paid)."""

    side: str  # "long" | "short"
    entry_ts: int
    exit_ts: int
    entry_index: int
    exit_index: int
    entry_price: float  # incl. entry slippage
    exit_price: float  # incl. exit slippage
    qty: float
    bars_held: int
    gross_pnl: float  # side · qty · (exit − entry); slippage already embedded
    commission: float  # entry + exit commission (positive cost)
    funding: float  # signed sum of 8h funding payments
    slippage_cost: float  # informational; already inside gross_pnl via fills
    net_pnl: float  # gross − commission + funding
    return_pct: float  # net_pnl / entry notional
    forced: bool  # marked out at final bar (no exit costs)
    liquidated: bool = False  # force-closed at the isolated-margin liquidation price


@dataclass
class BacktestResult:
    """Per-bar curves + realized trades + cost totals."""

    ts: list[int]
    equity: list[float]
    position: list[int]  # −1/0/+1 held over each bar
    trades: list[Trade]
    initial_cash: float
    cost_breakdown: dict = field(default_factory=dict)

    def trades_as_dicts(self) -> list[dict]:
        return [asdict(t) for t in self.trades]


class Engine(Protocol):
    """Seam for pluggable engines (lean core now; vectorbt in Phase 4)."""

    def __call__(
        self,
        ohlcv: pd.DataFrame,
        signals: dict[str, pd.Series],
        costs: CostConfig,
        capital: CapitalConfig,
        funding: pd.DataFrame | None = None,
        risk_exit: RiskExitConfig | None = None,
    ) -> BacktestResult: ...


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """Wilder's ATR (RMA of true range). NaN until ``length`` bars accumulate."""
    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n >= length:
        atr[length - 1] = tr[:length].mean()
        for i in range(length, n):
            atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length
    return atr


def _funding_per_bar(ts: np.ndarray, funding: pd.DataFrame | None) -> np.ndarray:
    """Sum of funding rates settling in ``(ts[i-1], ts[i]]`` for each bar i (0 at i=0)."""
    n = len(ts)
    out = np.zeros(n)
    if funding is None or funding.empty or n == 0:
        return out
    f_ts = funding["ts"].to_numpy(dtype="int64")
    f_rate = funding["funding_rate"].to_numpy(dtype="float64")
    # Assign each settlement to the first bar i (i>=1) with ts[i-1] < f <= ts[i].
    idx = np.searchsorted(ts, f_ts, side="left")  # ts[idx-1] < f <= ts[idx]
    for k in range(len(f_ts)):
        i = int(idx[k])
        if 1 <= i < n:
            out[i] += f_rate[k]
    return out


def run_engine(
    ohlcv: pd.DataFrame,
    signals: dict[str, pd.Series],
    costs: CostConfig,
    capital: CapitalConfig,
    funding: pd.DataFrame | None = None,
    risk_exit: RiskExitConfig | None = None,
) -> BacktestResult:
    """Simulate positions → equity → trades with the full §6.2 cost model."""
    n = len(ohlcv)
    ts = ohlcv["ts"].to_numpy(dtype="int64")
    open_ = ohlcv["open"].to_numpy(dtype="float64")
    high = ohlcv["high"].to_numpy(dtype="float64")
    low = ohlcv["low"].to_numpy(dtype="float64")
    close = ohlcv["close"].to_numpy(dtype="float64")

    le = signals["long_entry"].to_numpy(dtype="bool")
    lx = signals["long_exit"].to_numpy(dtype="bool")
    se = signals["short_entry"].to_numpy(dtype="bool")
    sx = signals["short_exit"].to_numpy(dtype="bool")

    comm_rate = costs.commission_bps / 1e4
    slip_bps = costs.slippage_bps / 1e4
    atr = (
        _atr(high, low, close, costs.atr_length)
        if costs.slippage_model == "atr"
        else np.zeros(n)
    )
    fund_bar = _funding_per_bar(ts, funding) if costs.funding_enabled else np.zeros(n)

    # Volatility stop/target (doc §7 Aşama 3) + ATR position sizing (§16 #4). One ATR
    # series drives both: the ATR-at-signal fixes the stop band at entry, and the same
    # stop distance sizes the position, so an ATR-sized trade always carries a real
    # stop (the trigger is evaluated at bar close and filled at the next open, rule #1).
    risk_on = risk_exit is not None and risk_exit.enabled
    atr_sizing = capital.sizing == "atr"
    stop_atr_len = risk_exit.atr_length if risk_exit is not None else 14
    atr_stop = _atr(high, low, close, stop_atr_len) if (risk_on or atr_sizing) else np.zeros(n)
    # Effective stop multiplier: the exit's own stop when set, else the sizing default.
    if risk_on and risk_exit.atr_stop_mult is not None:
        eff_stop_mult: float | None = risk_exit.atr_stop_mult
    elif atr_sizing:
        eff_stop_mult = capital.default_stop_atr_mult
    else:
        eff_stop_mult = None
    target_mult = risk_exit.atr_target_mult if risk_on else None
    stop_level = np.nan  # active-position stop price (NaN = none)
    target_level = np.nan  # active-position target price
    liq_level = np.nan  # active-position liquidation price (NaN = none)

    equity = np.empty(n)
    position = np.zeros(n, dtype="int64")

    cash = capital.initial_cash
    pos = 0  # −1/0/+1
    qty = 0.0
    entry_fill = 0.0
    entry_ts = 0
    entry_index = 0
    entry_commission = 0.0
    entry_slip = 0.0
    trade_funding = 0.0

    trades: list[Trade] = []
    tot_commission = 0.0
    tot_funding = 0.0
    tot_slippage = 0.0

    def fill_price(ref_open: float, is_buy: bool, s: int) -> tuple[float, float]:
        """Adverse fill + its slippage magnitude (absolute price move)."""
        if costs.slippage_model == "atr":
            d = costs.atr_mult * (atr[s] if not np.isnan(atr[s]) else 0.0)
        else:
            d = ref_open * slip_bps
        return (ref_open + d, d) if is_buy else (ref_open - d, d)

    def close_position(
        exit_ref: float, i: int, s: int, forced: bool, liquidated: bool = False
    ) -> None:
        nonlocal cash, pos, qty, trade_funding, tot_commission, tot_slippage
        nonlocal stop_level, target_level, liq_level
        is_buy = pos < 0  # buy to cover a short
        # A forced markout (final bar) and a liquidation both fill at the given price
        # with no exit slippage/commission — a liquidation *is* the margin wipe-out.
        if forced or liquidated:
            exit_fill, slip = exit_ref, 0.0
            exit_commission = 0.0
        else:
            exit_fill, slip = fill_price(exit_ref, is_buy, s)
            exit_commission = comm_rate * qty * exit_fill
        gross = pos * qty * (exit_fill - entry_fill)
        cash += gross - exit_commission
        commission = entry_commission + exit_commission
        net = gross - commission + trade_funding
        notional = qty * entry_fill
        trades.append(
            Trade(
                side="long" if pos > 0 else "short",
                entry_ts=int(entry_ts),
                exit_ts=int(ts[i]),
                entry_index=int(entry_index),
                exit_index=int(i),
                entry_price=float(entry_fill),
                exit_price=float(exit_fill),
                qty=float(qty),
                bars_held=int(i - entry_index),
                gross_pnl=float(gross),
                commission=float(commission),
                funding=float(trade_funding),
                slippage_cost=float(entry_slip + slip),
                net_pnl=float(net),
                return_pct=float(net / notional) if notional else 0.0,
                forced=forced,
                liquidated=liquidated,
            )
        )
        # Entry portions were counted in open_position; add only the exit side here.
        tot_commission += exit_commission
        tot_slippage += slip
        pos = 0
        qty = 0.0
        stop_level = np.nan
        target_level = np.nan
        liq_level = np.nan

    def open_position(side: int, entry_ref: float, i: int, s: int) -> None:
        nonlocal cash, pos, qty, entry_fill, entry_ts, entry_index
        nonlocal entry_commission, entry_slip, trade_funding, tot_commission, tot_slippage
        nonlocal stop_level, target_level, liq_level
        avail = cash  # flat ⇒ equity == cash
        if avail <= 0:
            return
        is_buy = side > 0
        fill, slip = fill_price(entry_ref, is_buy, s)
        if fill <= 0:
            return
        # Stop distance from the ATR known at the entry *signal* bar s — the sizing
        # basis *and* the exit band (identical to the live RiskLayer, so qty matches).
        stop_dist: float | None = None
        if eff_stop_mult is not None:
            a = atr_stop[s]
            if not np.isnan(a) and a > 0:
                stop_dist = eff_stop_mult * a
        q = position_size(
            equity=avail,
            price=fill,
            leverage=capital.leverage,
            sizing=capital.sizing,
            per_trade_pct=capital.per_trade_pct,
            stop_distance=stop_dist,
            fixed_fraction=capital.size_pct,
        )
        if q <= 0:
            return  # ATR sizing with no stop yet (warm-up) ⇒ skip, never oversize
        qty = q
        entry_commission = comm_rate * qty * fill
        cash -= entry_commission
        pos = side
        entry_fill = fill
        entry_ts = int(ts[i])
        entry_index = int(i)
        entry_slip = slip
        trade_funding = 0.0
        tot_commission += entry_commission
        tot_slippage += slip
        # Stop band (from the same stop distance that sized the trade) + target + liq.
        stop_level = fill - side * stop_dist if stop_dist is not None else np.nan
        target_level = np.nan
        if target_mult is not None:
            a = atr_stop[s]
            if not np.isnan(a):
                target_level = fill + side * target_mult * a
        liq = liquidation_price(
            fill, side, capital.leverage, capital.maintenance_margin_rate
        )
        liq_level = liq if liq is not None else np.nan

    for i in range(n):
        pos_start = pos
        # Funding for settlements during (ts[i-1], ts[i]], on the carried position.
        if pos_start != 0 and fund_bar[i]:
            pay = -pos_start * qty * entry_fill * fund_bar[i]
            cash += pay
            trade_funding += pay
            tot_funding += pay

        if i >= 1:
            s = i - 1
            op = open_[i]
            # Risk stop/target hit at bar s's close (fills next open, like a signal).
            c_s = close[s]
            risk_hit = pos != 0 and (
                (not np.isnan(stop_level) and pos * (c_s - stop_level) <= 0)
                or (not np.isnan(target_level) and pos * (c_s - target_level) >= 0)
            )
            # Exits first (allows a same-bar reversal).
            if pos == 1 and (lx[s] or se[s] or risk_hit):
                close_position(op, i, s, forced=False)
            elif pos == -1 and (sx[s] or le[s] or risk_hit):
                close_position(op, i, s, forced=False)
            # Entries only if flat.
            if pos == 0:
                if le[s]:
                    open_position(1, op, i, s)
                elif se[s]:
                    open_position(-1, op, i, s)

        # Isolated-margin liquidation on the position carried through bar i (rule #11):
        # if the bar's range reaches the liquidation price the venue force-closes it
        # there, so the backtest models the wipe-out instead of letting equity recover.
        if pos != 0 and not np.isnan(liq_level):
            if (pos > 0 and low[i] <= liq_level) or (pos < 0 and high[i] >= liq_level):
                close_position(float(liq_level), i, i, forced=False, liquidated=True)

        position[i] = pos
        equity[i] = cash + (pos * qty * (close[i] - entry_fill) if pos != 0 else 0.0)

    # Mark out any still-open position at the final close (no exit costs).
    if pos != 0 and n > 0:
        close_position(close[n - 1], n - 1, n - 1, forced=True)

    slip_on = (costs.slippage_bps > 0) if costs.slippage_model == "fixed_bps" else (
        costs.atr_mult > 0
    )
    cost_breakdown = {
        "total_commission": float(tot_commission),
        "total_funding": float(tot_funding),
        "total_slippage": float(tot_slippage),
        "commission_on": costs.commission_bps > 0,
        "slippage_on": bool(slip_on),
        "funding_on": bool(costs.funding_enabled and _funding_present(funding)),
        "costless": not (costs.commission_bps > 0 or slip_on),
    }
    return BacktestResult(
        ts=[int(t) for t in ts],
        equity=[float(e) for e in equity],
        position=[int(p) for p in position],
        trades=trades,
        initial_cash=float(capital.initial_cash),
        cost_breakdown=cost_breakdown,
    )


def _funding_present(funding: pd.DataFrame | None) -> bool:
    return funding is not None and not funding.empty
