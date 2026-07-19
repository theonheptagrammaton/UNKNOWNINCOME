"""Independent 'second-opinion' finalist engine (doc §6.1 fallback).

A deliberately separate execution implementation from ``backtest/engine.py``: it
reuses the shared signal generation (the signals are not what we are cross-checking)
but simulates fills, costs, funding and the volatility stop/target through its own
code path. If the two engines disagree beyond tolerance, that divergence is a real
signal — which is exactly what the cross-check alarm is for. Always available (no
third-party dependency), so the discovery pipeline can always cross-validate.
"""

from __future__ import annotations

import numpy as np

from app.backtest.config import RunConfig
from app.backtest.rules import build_signals, resolve_operands
from app.backtest.runner import _indicator_frames
from app.data.duckdb_query import query_funding, query_ohlcv
from app.data.timeframes import tf_to_ms
from app.discovery.finalist.base import FinalistResult

_MS_PER_YEAR = 365.25 * 24 * 3600 * 1000.0


def _wilder_atr(high, low, close, length: int) -> np.ndarray:
    """Wilder ATR, re-derived independently of the primary engine."""
    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr = np.full(n, np.nan)
    if n >= length >= 1:
        atr[length - 1] = tr[:length].mean()
        for i in range(length, n):
            atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length
    return atr


def _funding_by_bar(ts: np.ndarray, funding) -> np.ndarray:
    out = np.zeros(len(ts))
    if funding is None or funding.empty:
        return out
    f_ts = funding["ts"].to_numpy(dtype="int64")
    f_rate = funding["funding_rate"].to_numpy(dtype="float64")
    pos = np.searchsorted(ts, f_ts, side="left")
    for k, i in enumerate(pos):
        if 1 <= i < len(ts):
            out[i] += f_rate[k]
    return out


class LeanSecondEngine:
    """Independent event simulator used to cross-validate finalists."""

    name = "lean_second"

    def verify(self, config: RunConfig) -> FinalistResult:
        ohlcv = query_ohlcv(
            config.market, config.symbol, config.tf, config.start_ts, config.end_ts
        ).reset_index(drop=True)
        if len(ohlcv) < 2:
            return FinalistResult(0.0, 0, 0.0, config.capital.initial_cash, self.name)

        frames = _indicator_frames(config, ohlcv)
        ops = resolve_operands(ohlcv, frames)
        sig = build_signals(config.rules, ops, config.direction, len(ohlcv))
        funding = None
        if config.costs.funding_enabled:
            funding = query_funding(config.market, config.symbol, config.start_ts, config.end_ts)
        return self._simulate(ohlcv, sig, config, funding)

    def _simulate(self, ohlcv, sig, config, funding) -> FinalistResult:
        n = len(ohlcv)
        ts = ohlcv["ts"].to_numpy(dtype="int64")
        op = ohlcv["open"].to_numpy(dtype="float64")
        hi = ohlcv["high"].to_numpy(dtype="float64")
        lo = ohlcv["low"].to_numpy(dtype="float64")
        cl = ohlcv["close"].to_numpy(dtype="float64")
        le = sig["long_entry"].to_numpy(dtype="bool")
        lx = sig["long_exit"].to_numpy(dtype="bool")
        se = sig["short_entry"].to_numpy(dtype="bool")
        sx = sig["short_exit"].to_numpy(dtype="bool")

        costs, cap, risk = config.costs, config.capital, config.risk_exit
        comm = costs.commission_bps / 1e4
        slip = costs.slippage_bps / 1e4
        atr_slip = (
            _wilder_atr(hi, lo, cl, costs.atr_length) if costs.slippage_model == "atr"
            else np.zeros(n)
        )
        risk_on = risk is not None and risk.enabled
        atr_risk = _wilder_atr(hi, lo, cl, risk.atr_length) if risk_on else np.zeros(n)
        fund_bar = _funding_by_bar(ts, funding) if costs.funding_enabled else np.zeros(n)

        def fill(ref: float, is_buy: bool, s: int) -> float:
            d = costs.atr_mult * (atr_slip[s] if not np.isnan(atr_slip[s]) else 0.0) \
                if costs.slippage_model == "atr" else ref * slip
            return ref + d if is_buy else ref - d

        cash = cap.initial_cash
        pos, qty, entry = 0, 0.0, 0.0
        stop = target = np.nan
        equity = np.empty(n)
        trades = 0

        for i in range(n):
            if pos != 0 and fund_bar[i]:
                cash += -pos * qty * entry * fund_bar[i]
            if i >= 1:
                s = i - 1
                if pos != 0:
                    c = cl[s]
                    risk_hit = risk_on and (
                        (not np.isnan(stop) and pos * (c - stop) <= 0)
                        or (not np.isnan(target) and pos * (c - target) >= 0)
                    )
                    sig_exit = (pos == 1 and (lx[s] or se[s])) or (pos == -1 and (sx[s] or le[s]))
                    if risk_hit or sig_exit:
                        xf = fill(op[i], pos < 0, s)
                        cash += pos * qty * (xf - entry) - comm * qty * xf
                        pos, qty, stop, target, trades = 0, 0.0, np.nan, np.nan, trades + 1
                if pos == 0:
                    side = 1 if le[s] else (-1 if se[s] else 0)
                    if side != 0 and cash > 0:
                        ef = fill(op[i], side > 0, s)
                        if ef > 0:
                            qty = (cash * cap.size_pct * cap.leverage) / ef
                            cash -= comm * qty * ef
                            pos, entry = side, ef
                            if risk_on and not np.isnan(atr_risk[s]):
                                a = atr_risk[s]
                                stop = (entry - side * risk.atr_stop_mult * a
                                        if risk.atr_stop_mult else np.nan)
                                target = (entry + side * risk.atr_target_mult * a
                                          if risk.atr_target_mult else np.nan)
            equity[i] = cash + (pos * qty * (cl[i] - entry) if pos != 0 else 0.0)

        if pos != 0:  # mark out at final close (no exit cost), independent of primary
            equity[n - 1] = cash + pos * qty * (cl[n - 1] - entry)
            trades += 1

        initial = cap.initial_cash
        net_return = equity[-1] / initial - 1.0 if initial else 0.0
        sharpe = _sharpe(equity, config.tf)
        return FinalistResult(
            net_return=float(net_return), num_trades=int(trades),
            sharpe=float(sharpe), final_equity=float(equity[-1]), engine=self.name,
        )


def _sharpe(equity: np.ndarray, tf: str) -> float:
    if len(equity) < 3:
        return 0.0
    prev = equity[:-1]
    rets = np.where(prev != 0, equity[1:] / np.where(prev == 0, np.nan, prev) - 1.0, 0.0)
    rets = np.nan_to_num(rets, nan=0.0, posinf=0.0, neginf=0.0)
    std = rets.std(ddof=1) if len(rets) > 1 else 0.0
    if std <= 0:
        return 0.0
    return float(rets.mean() / std * np.sqrt(_MS_PER_YEAR / tf_to_ms(tf)))
