"""Lean single-config evaluation shared by every discovery stage.

The Phase-3 :func:`app.backtest.runner.run_backtest` also builds the heavy UI
report (candles/markers/curves); discovery runs thousands of evaluations and only
needs metrics + the realized signals, so this strips the run down to
indicators → signals → engine → metrics. It reuses the exact Phase-3 primitives
(``_indicator_frames``, ``resolve_operands``, ``build_signals``, ``run_engine``,
``compute_metrics``) so a discovery score is identical to a manual backtest score.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.backtest.config import RunConfig
from app.backtest.engine import BacktestResult, run_engine
from app.backtest.metrics import compute_metrics
from app.backtest.rules import build_signals, resolve_operands
from app.backtest.runner import NoDataError, _indicator_frames
from app.data.duckdb_query import query_funding, query_ohlcv

MIN_BARS = 50  # need warm-up + a handful of tradable bars to score anything


@dataclass
class EvalResult:
    metrics: dict
    result: BacktestResult
    signals: dict[str, pd.Series]
    ohlcv: pd.DataFrame


def run_eval(config: RunConfig, ohlcv: pd.DataFrame | None = None) -> EvalResult:
    """Evaluate one ``RunConfig`` to metrics + signals (no report, no persistence)."""
    if ohlcv is None:
        ohlcv = query_ohlcv(
            config.market, config.symbol, config.tf, config.start_ts, config.end_ts
        ).reset_index(drop=True)
    if len(ohlcv) < MIN_BARS:
        raise NoDataError(
            f"insufficient data for {config.symbol}/{config.tf} "
            f"({len(ohlcv)} bars < {MIN_BARS})"
        )

    frames = _indicator_frames(config, ohlcv)
    ops = resolve_operands(ohlcv, frames)
    signals = build_signals(config.rules, ops, config.direction, len(ohlcv))

    funding = None
    if config.costs.funding_enabled:
        funding = query_funding(
            config.market, config.symbol, config.start_ts, config.end_ts
        )

    result = run_engine(
        ohlcv, signals, config.costs, config.capital, funding, config.risk_exit
    )
    metrics = compute_metrics(result, config.tf)
    return EvalResult(metrics=metrics, result=result, signals=signals, ohlcv=ohlcv)


def entry_vector(signals: dict[str, pd.Series]) -> pd.Series:
    """Boolean 'any entry this bar' series — the correlation signal (§7 Aşama 2)."""
    return (signals["long_entry"] | signals["short_entry"]).astype(float)
