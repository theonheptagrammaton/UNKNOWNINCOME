"""Stage 5 — walk-forward validation, the overfitting defense line (doc §6.5).

A finalist earns "candidate" status only by surviving all of §6.5:
1. IS/OOS separation — the score that ranks it comes from out-of-sample folds.
2. Walk-forward — rolling train/test windows (default 90/30/30 days).
3. Parameter plateau — the best params' neighbours must also be profitable.
4. Monte-Carlo — trade order is shuffled to map the drawdown distribution.

Everything is seeded, so the same scan seed reproduces the same verdict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from app.data.duckdb_query import query_ohlcv
from app.discovery.combine import Combo, combo_to_run_config
from app.discovery.config import ScanConfig
from app.discovery.evaluate import MIN_BARS, run_eval
from app.discovery.optimize import OptimizeResult, _tunable
from app.indicators.registry import ParamSpec

logger = logging.getLogger(__name__)

_DAY_MS = 86_400_000


@dataclass
class Window:
    train_start: int
    train_end: int
    test_start: int
    test_end: int


def rolling_windows(
    start_ts: int, end_ts: int, train_days: int, test_days: int, step_days: int
) -> list[Window]:
    """Sliding train/test windows over ``[start_ts, end_ts]`` (doc §6.5 point 2)."""
    train = train_days * _DAY_MS
    test = test_days * _DAY_MS
    step = max(1, step_days) * _DAY_MS
    windows: list[Window] = []
    t = start_ts
    while t + train + test <= end_ts:
        windows.append(Window(t, t + train, t + train, t + train + test))
        t += step
    return windows


@dataclass
class WFOReport:
    oos_score: float
    layers: list[dict]
    plateau_ok: bool
    plateau_scores: list[float]
    monte_carlo: dict
    full_metrics: dict = field(default_factory=dict)
    survived: bool = False
    oos_mean_net_return: float = 0.0
    oos_trades: int = 0
    # Aşama 5.5 inputs (doc §23): the realized OOS per-trade returns feed the Deflated
    # Sharpe (skew/kurtosis/T); the full-period per-bar returns feed the PBO cohort
    # matrix (all combos in a symbol × tf cell share the same bar axis).
    oos_trade_returns: list[float] = field(default_factory=list)
    full_bar_returns: list[float] = field(default_factory=list)


def evaluate_survival(
    *,
    oos_score: float,
    oos_mean_net: float,
    oos_trades: int,
    is_score: float,
    plateau_ok: bool,
    passes_hard_filters: bool,
    min_oos_is_ratio: float,
    min_oos_trades: int,
) -> bool:
    """§6.5 survival verdict — a *genuine* OOS bar, not the old ``oos_score > 0``.

    The out-of-sample folds must be profitable on average, keep a real fraction of the
    in-sample score (so a strategy that only shines in-sample is rejected), carry enough
    OOS trades to be evidence rather than noise, and clear the plateau + hard filters.
    """
    oos_is_ok = (
        oos_score >= min_oos_is_ratio * is_score if is_score > 0 else oos_score > 0.0
    )
    return bool(
        plateau_ok
        and passes_hard_filters
        and oos_mean_net > 0.0
        and oos_trades >= min_oos_trades
        and oos_is_ok
    )


def monte_carlo(trade_returns: np.ndarray, runs: int, seed: int) -> dict:
    """Shuffle trade order → drawdown distribution; report the 95% worst case."""
    n = len(trade_returns)
    if n < 2 or runs <= 0:
        return {"p95_max_drawdown": 0.0, "mean_max_drawdown": 0.0, "runs": 0}
    rng = np.random.default_rng(seed)
    dds = np.empty(runs)
    for i in range(runs):
        eq = np.cumprod(1.0 + rng.permutation(trade_returns))
        peak = np.maximum.accumulate(eq)
        dds[i] = float((1.0 - eq / np.where(peak == 0, np.nan, peak)).max())
    dds = np.nan_to_num(dds, nan=0.0)
    return {
        "p95_max_drawdown": float(np.percentile(dds, 95)),
        "mean_max_drawdown": float(dds.mean()),
        "runs": int(runs),
    }


def _neighbor_values(spec: ParamSpec, value: float, steps: int) -> list[float]:
    """±steps·step neighbours of a value, clamped to the spec's bounds."""
    if spec.step is None or spec.min is None or spec.max is None:
        return []
    out: list[float] = []
    for k in (-steps, steps):
        v = value + k * spec.step
        if spec.min <= v <= spec.max and v != value:
            out.append(round(v, 6) if spec.kind == "float" else float(int(v)))
    return out


def parameter_plateau(
    combo: Combo, config: ScanConfig, opt: OptimizeResult, best_score: float
) -> tuple[bool, list[float]]:
    """Perturb each tuned param ±step; neighbours must score ≥ ratio × best (§6.5.3)."""
    if not config.plateau.enabled:
        return True, []
    specs = {
        "trig": _tunable(combo.trigger.indicator_id),
        "filt": _tunable(combo.filter.indicator_id),
    }
    chosen = {"trig": dict(opt.trigger_params), "filt": dict(opt.filter_params)}
    floor = config.plateau.min_neighbor_ratio * best_score
    scores: list[float] = []
    ok = True
    for prefix, params in chosen.items():
        for name, value in params.items():
            spec = specs[prefix].get(name)
            if spec is None:
                continue
            for nv in _neighbor_values(spec, float(value), config.plateau.neighbor_steps):
                trial = {"trig": dict(chosen["trig"]), "filt": dict(chosen["filt"])}
                trial[prefix][name] = nv
                s = _eval_score(combo, config, trial["trig"], trial["filt"])
                scores.append(s)
                if s < floor:
                    ok = False
    return ok, scores


def walk_forward(combo: Combo, config: ScanConfig, opt: OptimizeResult) -> WFOReport:
    """Full §6.5 validation for one optimized combo."""
    full = query_ohlcv(config.market, combo.symbol, combo.tf, config.start_ts, config.end_ts)
    if len(full) < MIN_BARS:
        return WFOReport(0.0, [], False, [], monte_carlo(np.zeros(0), 0, config.seed))

    ts0, ts1 = int(full["ts"].iloc[0]), int(full["ts"].iloc[-1])
    windows = rolling_windows(
        ts0, ts1, config.wfo.train_days, config.wfo.test_days, config.wfo.step_days
    )
    if not windows:
        # Data span < train+test ⇒ fall back to a single 70/30 IS/OOS split (§6.5.1).
        split = ts0 + int(0.7 * (ts1 - ts0))
        windows = [Window(ts0, split, split, ts1)]

    layers: list[dict] = []
    oos_trade_returns: list[float] = []
    for w in windows:
        trig, filt = opt.trigger_params, opt.filter_params
        if config.wfo.reoptimize:
            from app.discovery.optimize import optimize_combo

            train_cfg = config.model_copy(update={"start_ts": w.train_start, "end_ts": w.train_end})
            re = optimize_combo(combo, train_cfg)
            trig, filt = re.trigger_params, re.filter_params
        score, metrics, layer_rets = _eval(combo, config, trig, filt, w.test_start, w.test_end)
        oos_trade_returns.extend(layer_rets)
        layers.append({
            "train_start": w.train_start, "train_end": w.train_end,
            "test_start": w.test_start, "test_end": w.test_end,
            "composite_score": score,
            "net_return": metrics.get("net_return"),
            "num_trades": metrics.get("num_trades", 0),
        })

    oos_scores = [x["composite_score"] for x in layers]
    oos_score = float(np.mean(oos_scores)) if oos_scores else 0.0
    oos_nets = [x["net_return"] for x in layers if x.get("net_return") is not None]
    oos_mean_net = float(np.mean(oos_nets)) if oos_nets else 0.0
    oos_trades = int(sum(x.get("num_trades", 0) for x in layers))

    # Full-period eval: leaderboard metrics + the trade set for Monte-Carlo + the
    # per-bar returns for the Aşama 5.5 PBO cohort (§23.4).
    full_score, full_metrics, trade_rets, bar_rets = _eval_full(
        combo, config, opt.trigger_params, opt.filter_params
    )
    plateau_ok, plateau_scores = parameter_plateau(combo, config, opt, full_score)
    mc = monte_carlo(trade_rets, config.monte_carlo_runs, config.seed)

    # §6.5 survival — a genuine OOS bar (see evaluate_survival), not "oos_score > 0".
    survived = evaluate_survival(
        oos_score=oos_score,
        oos_mean_net=oos_mean_net,
        oos_trades=oos_trades,
        is_score=float(opt.best_score or 0.0),
        plateau_ok=plateau_ok,
        passes_hard_filters=bool(full_metrics.get("passes_hard_filters", False)),
        min_oos_is_ratio=config.wfo.min_oos_is_ratio,
        min_oos_trades=config.wfo.min_oos_trades,
    )
    return WFOReport(
        oos_score=oos_score, layers=layers, plateau_ok=plateau_ok,
        plateau_scores=plateau_scores, monte_carlo=mc, full_metrics=full_metrics,
        survived=survived, oos_mean_net_return=oos_mean_net, oos_trades=oos_trades,
        oos_trade_returns=oos_trade_returns, full_bar_returns=[float(x) for x in bar_rets],
    )


def _eval(combo, config, trig, filt, start, end) -> tuple[float, dict, list[float]]:
    cfg = config.model_copy(update={"start_ts": start, "end_ts": end})
    try:
        ev = run_eval(combo_to_run_config(combo, cfg, trig, filt))
    except Exception as exc:  # resilience per layer (incl. NoDataError)
        logger.debug("wfo layer eval failed %s: %s", combo.key, exc)
        return 0.0, {}, []
    trade_rets = [float(t.return_pct) for t in ev.result.trades]
    return float(ev.metrics.get("composite_score") or 0.0), ev.metrics, trade_rets


def _eval_score(combo, config, trig, filt) -> float:
    return _eval_full(combo, config, trig, filt)[0]


def _bar_returns(equity: list[float]) -> np.ndarray:
    """Per-bar returns from an equity curve (the PBO cohort series, §23.4)."""
    eq = np.asarray(equity, dtype="float64")
    if eq.size < 2:
        return np.zeros(0)
    prev = eq[:-1]
    rets = np.where(prev != 0, eq[1:] / np.where(prev == 0, np.nan, prev) - 1.0, 0.0)
    return np.nan_to_num(rets, nan=0.0, posinf=0.0, neginf=0.0)


def _eval_full(combo, config, trig, filt) -> tuple[float, dict, np.ndarray, np.ndarray]:
    try:
        ev = run_eval(combo_to_run_config(combo, config, trig, filt))
    except Exception as exc:  # resilience (incl. NoDataError)
        logger.debug("wfo full eval failed %s: %s", combo.key, exc)
        return 0.0, {}, np.zeros(0), np.zeros(0)
    rets = np.array([t.return_pct for t in ev.result.trades], dtype="float64")
    bar_rets = _bar_returns(ev.result.equity)
    return float(ev.metrics.get("composite_score") or 0.0), ev.metrics, rets, bar_rets
