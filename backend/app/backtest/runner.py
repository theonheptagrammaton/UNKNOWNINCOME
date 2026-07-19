"""Orchestrate a single run: config → indicators → signals → engine → report.

Pure and side-effect free (no DB, no disk) so it is directly unit-testable and
deterministic. Persistence (``backtest_runs`` row + on-disk artifact) is the
worker's job; the API reads back what the worker stored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest.config import RunConfig, config_hash
from app.backtest.engine import BacktestResult, run_engine
from app.backtest.metrics import compute_metrics
from app.backtest.rules import build_signals, resolve_operands
from app.data.duckdb_query import query_funding, query_ohlcv
from app.indicators.compute import compute_indicator


class NoDataError(ValueError):
    """Raised when a run has no (or too little) market data to evaluate."""


def _indicator_frames(config: RunConfig, ohlcv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Compute each configured indicator and align it row-for-row with ``ohlcv``.

    Indicators are computed over the *full* stored series (warm-up preserved) then
    sliced to the window; a left-merge on ``ts`` guarantees exact row alignment.
    """
    frames: dict[str, pd.DataFrame] = {}
    for spec in config.indicators:
        frame = compute_indicator(
            config.market,
            config.symbol,
            config.tf,
            spec.id,
            spec.params,
            start_ts=config.start_ts,
            end_ts=config.end_ts,
        )
        aligned = ohlcv[["ts"]].merge(frame, on="ts", how="left").reset_index(drop=True)
        frames[spec.key] = aligned
    return frames


def _sanitize(value: object) -> object:
    """Recursively convert NaN/Inf to None so the report is JSON-clean."""
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def build_report(config: RunConfig, ohlcv: pd.DataFrame, result: BacktestResult) -> dict:
    """Assemble the UI payload: candles, equity, drawdown, markers, trades."""
    ts = ohlcv["ts"].to_numpy(dtype="int64")
    equity = np.asarray(result.equity, dtype="float64")
    peak = np.maximum.accumulate(equity) if len(equity) else equity
    dd = np.where(peak > 0, equity / peak - 1.0, 0.0)

    candles = [
        {
            "time": int(t),
            "open": float(o),
            "high": float(h),
            "low": float(low),
            "close": float(c),
        }
        for t, o, h, low, c in zip(
            ts,
            ohlcv["open"].to_numpy(),
            ohlcv["high"].to_numpy(),
            ohlcv["low"].to_numpy(),
            ohlcv["close"].to_numpy(),
            strict=False,
        )
    ]
    equity_curve = [
        {"time": int(t), "value": float(e)} for t, e in zip(ts, equity, strict=False)
    ]
    drawdown = [
        {"time": int(t), "value": float(d)} for t, d in zip(ts, dd, strict=False)
    ]

    markers: list[dict] = []
    for tr in result.trades:
        markers.append(
            {
                "time": tr.entry_ts,
                "price": tr.entry_price,
                "kind": f"{tr.side}_entry",
            }
        )
        markers.append(
            {
                "time": tr.exit_ts,
                "price": tr.exit_price,
                "kind": f"{tr.side}_exit",
                "forced": tr.forced,
            }
        )

    report = {
        "market": config.market,
        "symbol": config.symbol,
        "tf": config.tf,
        "direction": config.direction,
        "config_hash": config_hash(config),
        "bars": len(candles),
        "candles": candles,
        "equity": equity_curve,
        "drawdown": drawdown,
        "position": result.position,
        "markers": markers,
        "trades": result.trades_as_dicts(),
        "cost_breakdown": result.cost_breakdown,
    }
    return _sanitize(report)  # type: ignore[return-value]


def run_backtest(config: RunConfig) -> dict:
    """Run one backtest end to end; returns ``{metrics, report}`` (no persistence)."""
    ohlcv = query_ohlcv(
        config.market, config.symbol, config.tf, config.start_ts, config.end_ts
    ).reset_index(drop=True)
    if len(ohlcv) < 2:
        raise NoDataError(
            f"no market data for {config.market}/{config.symbol}/{config.tf} in range"
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
    report = build_report(config, ohlcv, result)
    return {"metrics": _sanitize(metrics), "report": report}
