"""Orchestrate a single run: config → indicators → signals → engine → report.

Pure and side-effect free (no DB, no disk) so it is directly unit-testable and
deterministic. Persistence (``backtest_runs`` row + on-disk artifact) is the
worker's job; the API reads back what the worker stored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest.config import RunConfig, config_hash
from app.backtest.engine import BacktestResult, _atr, run_engine
from app.backtest.metrics import compute_metrics
from app.backtest.rules import assert_operands_resolve, build_signals, resolve_operands
from app.data.duckdb_query import query_funding, query_ohlcv
from app.execution.slippage_model import LearnedSlippageModel, load_model
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


# Pane classification (UI overlay vs separate sub-pane). An indicator whose values
# live on the price scale — a moving average, a Bollinger band, VWAP, SAR — is drawn
# *on* the candle pane; an oscillator (RSI, MACD, Stochastic) or a volume/statistic
# series is drawn in its own synced sub-pane below. Category decides it, because
# category is what actually determines the scale: momentum/volume/cycle/statistic are
# never price-scale, overlap/trend/price always are. Only genuinely ambiguous
# categories (volatility — Bollinger overlays, ATR does not) fall back to a magnitude
# test so the answer is right regardless of the asset's price level: the indicator's
# median must sit within [0.25×, 4×] of the median close to count as price-scale.
_PRICE_PANE_LO = 0.25
_PRICE_PANE_HI = 4.0
_PRICE_CATEGORIES = frozenset({"overlap", "trend", "price"})
_SEPARATE_CATEGORIES = frozenset({"momentum", "volume", "cycle", "statistic", "pattern"})


def _indicator_category(indicator_id: str) -> str:
    """Registry category for ``indicator_id`` ("" if unknown, e.g. a custom plugin)."""
    from app.indicators.registry import get_indicator

    try:
        return get_indicator(indicator_id).category
    except Exception:  # noqa: BLE001 - unknown id ⇒ fall back to magnitude
        return ""


def _classify_pane(category: str, close_med: float, finite_cols: list[np.ndarray]) -> str:
    """"price" (overlay) or "separate" (own sub-pane) for one indicator's lines."""
    if category in _PRICE_CATEGORIES:
        return "price"
    if category in _SEPARATE_CATEGORIES:
        return "separate"
    if close_med > 0 and finite_cols:
        med = float(np.median(np.concatenate(finite_cols)))
        if med != 0 and _PRICE_PANE_LO <= abs(med) / close_med <= _PRICE_PANE_HI:
            return "price"
    return "separate"


def _indicator_series(
    config: RunConfig, frames: dict[str, pd.DataFrame], close: np.ndarray
) -> list[dict]:
    """Per-indicator line series for the chart, tagged ``price`` or ``separate``.

    Each entry is ``{key, id, pane, lines:[{name, points:[{time, value}]}]}`` where
    ``points`` are the finite samples of one output column (NaN warm-up dropped so
    the line simply starts once the indicator is defined).
    """
    finite_close = close[np.isfinite(close)]
    close_med = float(np.median(finite_close)) if finite_close.size else 0.0

    series: list[dict] = []
    for spec in config.indicators:
        frame = frames.get(spec.key)
        if frame is None:
            continue
        ts = frame["ts"].to_numpy(dtype="int64")
        lines: list[dict] = []
        finite_cols: list[np.ndarray] = []
        for col in frame.columns:
            if col == "ts":
                continue
            values = pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype="float64")
            mask = np.isfinite(values)
            if not mask.any():
                continue
            points = [
                {"time": int(t), "value": float(v)}
                for t, v in zip(ts[mask], values[mask], strict=False)
            ]
            lines.append({"name": str(col), "points": points})
            finite_cols.append(values[mask])
        if not lines:
            continue
        pane = _classify_pane(_indicator_category(spec.id), close_med, finite_cols)
        series.append({"key": spec.key, "id": spec.id, "pane": pane, "lines": lines})
    return series


def build_report(
    config: RunConfig,
    ohlcv: pd.DataFrame,
    result: BacktestResult,
    frames: dict[str, pd.DataFrame] | None = None,
) -> dict:
    """Assemble the UI payload: candles, equity, drawdown, markers, trades, indicators."""
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

    indicators = (
        _indicator_series(config, frames, ohlcv["close"].to_numpy(dtype="float64"))
        if frames
        else []
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
        "indicators": indicators,
    }
    return _sanitize(report)  # type: ignore[return-value]


def _representative_notional(config: RunConfig) -> float:
    """A coarse per-order quote notional for the learned-slippage notional tier.

    The notional tier is log-scaled (§26.1), so a representative order size is enough:
    fixed sizing deploys ``size_pct × leverage`` of equity as notional; ATR sizing is
    bounded by the margin cap (``equity × leverage``). Either way the *volatility* tier
    (per-bar ATR, the dominant slippage driver) is exact; only the size tier is coarse.
    """
    cap = config.capital
    factor = cap.size_pct if cap.sizing == "fixed" else 1.0
    return cap.initial_cash * max(cap.leverage, 1.0) * factor


def learned_slippage_series(
    config: RunConfig, ohlcv: pd.DataFrame, model: LearnedSlippageModel | None = None
) -> np.ndarray | None:
    """Per-bar learned slippage in bps (doc §26.1), or ``None`` if no model is built.

    Trusted buckets carry the measured slippage; untrusted bars fall back to the fixed
    ``slippage_bps`` assumption so the series is always fully defined.
    """
    model = model or load_model()
    if model is None:
        return None
    n = len(ohlcv)
    high = ohlcv["high"].to_numpy("float64")
    low = ohlcv["low"].to_numpy("float64")
    close = ohlcv["close"].to_numpy("float64")
    atr = _atr(high, low, close, config.costs.atr_length)
    notional = _representative_notional(config)
    fallback = config.costs.slippage_bps
    out = np.empty(n, dtype="float64")
    for i in range(n):
        a = atr[i] if not np.isnan(atr[i]) else 0.0
        bps = model.lookup_bps(config.symbol, config.tf, notional, a, close[i])
        out[i] = bps if bps is not None else fallback
    return out


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
    assert_operands_resolve(config.rules, ops)
    signals = build_signals(config.rules, ops, config.direction, len(ohlcv))

    funding = None
    if config.costs.funding_enabled:
        funding = query_funding(
            config.market, config.symbol, config.start_ts, config.end_ts
        )

    slippage_series = (
        learned_slippage_series(config, ohlcv)
        if config.costs.slippage_model == "learned"
        else None
    )
    result = run_engine(
        ohlcv, signals, config.costs, config.capital, funding, config.risk_exit,
        slippage_bps_series=slippage_series,
    )
    metrics = compute_metrics(result, config.tf)
    report = build_report(config, ohlcv, result, frames)
    return {"metrics": _sanitize(metrics), "report": report}
