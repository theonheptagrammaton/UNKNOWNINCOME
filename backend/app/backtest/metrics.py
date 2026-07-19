"""Full metric set (§6.3) + composite score (§6.4) for one backtest run.

Every run computes the whole §6.3 battery from the equity curve and the realized
trades. The §6.4 composite score ranks runs; its ``norm(...)`` terms are meant to
be normalised across a *population* (the Phase 4 leaderboard). For a single run we
apply documented, monotonic bounded transforms so a score exists on its own — the
leaderboard re-normalises later. Hard filters (≥30 trades · MaxDD ≤ 25% · PF ≥ 1)
are reported as a pass/fail flag, never silently applied here.
"""

from __future__ import annotations

import numpy as np

from app.backtest.engine import BacktestResult
from app.data.timeframes import tf_to_ms

_MS_PER_YEAR = 365.25 * 24 * 3600 * 1000.0

# §6.4 weights.
_W_SHARPE = 0.30
_W_PF = 0.25
_W_MAXDD = 0.20
_W_WINRATE = 0.15
_W_EXPECTANCY = 0.10


def _safe_std(x: np.ndarray) -> float:
    return float(x.std(ddof=1)) if len(x) > 1 else 0.0


def _monthly_returns(ts: np.ndarray, equity: np.ndarray, initial: float) -> list[dict]:
    """Month-by-month return heatmap rows: ``{year, month, return}``."""
    if len(equity) == 0:
        return []
    import pandas as pd

    idx = pd.to_datetime(ts, unit="ms", utc=True)
    s = pd.Series(equity, index=idx)
    month_end = s.resample("ME").last()
    # Prepend the initial capital so the first month has a base to grow from.
    base = np.concatenate([[initial], month_end.to_numpy()[:-1]])
    rets = month_end.to_numpy() / np.where(base == 0, np.nan, base) - 1.0
    out: list[dict] = []
    for period, r in zip(month_end.index, rets, strict=False):
        out.append(
            {"year": int(period.year), "month": int(period.month), "return": _f(r)}
        )
    return out


def _f(v: float) -> float | None:
    """JSON-safe float (NaN/Inf → None)."""
    if v is None or not np.isfinite(v):
        return None
    return float(v)


def _max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    """Return (max drawdown depth as a positive fraction, longest underwater bars)."""
    if len(equity) == 0:
        return 0.0, 0
    peak = np.maximum.accumulate(equity)
    dd = np.where(peak > 0, equity / peak - 1.0, 0.0)
    depth = float(-dd.min()) if len(dd) else 0.0
    # Longest consecutive underwater stretch.
    longest = cur = 0
    for x in dd:
        cur = cur + 1 if x < 0 else 0
        longest = max(longest, cur)
    return depth, longest


def compute_metrics(result: BacktestResult, tf: str) -> dict:
    """The full §6.3 metric set + §6.4 score from a :class:`BacktestResult`."""
    equity = np.asarray(result.equity, dtype="float64")
    ts = np.asarray(result.ts, dtype="int64")
    initial = result.initial_cash
    n = len(equity)

    final = float(equity[-1]) if n else initial
    net_return = final / initial - 1.0 if initial else 0.0

    span_ms = float(ts[-1] - ts[0]) if n > 1 else 0.0
    years = span_ms / _MS_PER_YEAR
    if years > 0 and final > 0 and initial > 0:
        try:
            cagr = (final / initial) ** (1.0 / years) - 1.0
        except OverflowError:  # sub-day span annualises to an absurd value → report null
            cagr = float("inf")
    else:
        cagr = net_return

    # Per-bar returns for risk-adjusted ratios.
    if n > 1:
        prev = equity[:-1]
        rets = np.where(prev != 0, equity[1:] / np.where(prev == 0, np.nan, prev) - 1.0, 0.0)
        rets = np.nan_to_num(rets, nan=0.0, posinf=0.0, neginf=0.0)
    else:
        rets = np.zeros(0)
    bars_per_year = _MS_PER_YEAR / tf_to_ms(tf)
    mean_r = float(rets.mean()) if len(rets) else 0.0
    std_r = _safe_std(rets)
    sharpe = (mean_r / std_r) * np.sqrt(bars_per_year) if std_r > 0 else 0.0
    downside = rets[rets < 0]
    dstd = _safe_std(downside)
    sortino = (mean_r / dstd) * np.sqrt(bars_per_year) if dstd > 0 else 0.0

    max_dd, dd_bars = _max_drawdown(equity)
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    # Trade-level stats.
    pnls = np.array([t.net_pnl for t in result.trades], dtype="float64")
    trade_rets = np.array([t.return_pct for t in result.trades], dtype="float64")
    num_trades = len(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    win_rate = len(wins) / num_trades if num_trades else 0.0
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (np.inf if gross_win > 0 else 0.0)
    expectancy = float(pnls.mean()) if num_trades else 0.0
    expectancy_pct = float(trade_rets.mean()) if num_trades else 0.0
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(-losses.mean()) if len(losses) else 0.0
    avg_win_loss = avg_win / avg_loss if avg_loss > 0 else 0.0

    position = np.asarray(result.position, dtype="int64")
    exposure = float((position != 0).mean()) if n else 0.0
    sqn = (
        np.sqrt(num_trades) * (trade_rets.mean() / _safe_std(trade_rets))
        if num_trades > 1 and _safe_std(trade_rets) > 0
        else 0.0
    )

    metrics = {
        "net_return": _f(net_return),
        "cagr": _f(cagr),
        "sharpe": _f(sharpe),
        "sortino": _f(sortino),
        "calmar": _f(calmar),
        "max_drawdown": _f(max_dd),
        "max_drawdown_bars": int(dd_bars),
        "win_rate": _f(win_rate),
        "profit_factor": _f(profit_factor) if np.isfinite(profit_factor) else None,
        "expectancy": _f(expectancy),
        "expectancy_pct": _f(expectancy_pct),
        "avg_win_loss": _f(avg_win_loss),
        "num_trades": num_trades,
        "exposure": _f(exposure),
        "sqn": _f(sqn),
        "final_equity": _f(final),
        "monthly_returns": _monthly_returns(ts, equity, initial),
    }
    metrics.update(composite_score(metrics))
    return metrics


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def composite_score(m: dict) -> dict:
    """§6.4 score with single-run bounded normalisation + hard-filter flag.

    Normalisation (documented, monotonic): Sharpe/3, (PF−1)/2, MaxDD/0.5,
    win-rate as-is, expectancy via tanh. The Phase 4 leaderboard re-normalises
    each term across the population, so absolute scores are comparable only within
    a shared normalisation context.
    """
    sharpe = m.get("sharpe") or 0.0
    pf = m.get("profit_factor")
    pf = pf if pf is not None else 10.0  # PF=None ⇒ no losses ⇒ treat as strong
    max_dd = m.get("max_drawdown") or 0.0
    win_rate = m.get("win_rate") or 0.0
    exp_pct = m.get("expectancy_pct") or 0.0
    num_trades = m.get("num_trades") or 0

    n_sharpe = _clamp01(sharpe / 3.0)
    n_pf = _clamp01((pf - 1.0) / 2.0)
    n_maxdd = _clamp01(max_dd / 0.5)
    n_win = _clamp01(win_rate)
    n_exp = _clamp01(0.5 * (1.0 + np.tanh(exp_pct * 50.0)))

    score = (
        _W_SHARPE * n_sharpe
        + _W_PF * n_pf
        + _W_MAXDD * (1.0 - n_maxdd)
        + _W_WINRATE * n_win
        + _W_EXPECTANCY * n_exp
    )
    passes = num_trades >= 30 and max_dd <= 0.25 and (pf >= 1.0)
    return {
        "composite_score": _f(score),
        "passes_hard_filters": bool(passes),
        "score_components": {
            "sharpe": _f(n_sharpe),
            "profit_factor": _f(n_pf),
            "max_drawdown": _f(1.0 - n_maxdd),
            "win_rate": _f(n_win),
            "expectancy": _f(n_exp),
        },
    }
