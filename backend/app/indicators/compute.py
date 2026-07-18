"""Indicator compute engine + Parquet cache (doc §5.5).

Every computed series is cached under ``(symbol, tf, indicator_id, params_hash)``
so the discovery scan never recomputes the same thing — the main reason a full
scan stays under two hours. Cache hits/misses are logged.

The cached parquet carries its own ``ts`` column, so freshness is decided by
comparing the cached bar coverage with the current data — new bars invalidate
the entry without a separate sidecar file.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.data.duckdb_query import query_ohlcv
from app.indicators.registry import IndicatorDef, get_indicator

logger = logging.getLogger(__name__)

CACHE_SUBDIR = "_indicators"


def effective_params(def_: IndicatorDef, params: dict | None) -> dict[str, float]:
    """Merge caller params over defaults, dropping anything not in the schema."""
    merged: dict[str, float] = {name: spec.default for name, spec in def_.params.items()}
    for name, value in (params or {}).items():
        if name in def_.params:
            merged[name] = value
    return merged


def params_hash(def_: IndicatorDef, params: dict | None) -> str:
    """Stable 12-char hash of the effective parameter set (order-independent)."""
    merged = effective_params(def_, params)
    canonical = json.dumps(merged, sort_keys=True, separators=(",", ":"), default=float)
    return hashlib.sha1(canonical.encode()).hexdigest()[:12]


def cache_path(market: str, symbol: str, tf: str, indicator_id: str, phash: str) -> Path:
    """Absolute path to a cached indicator parquet."""
    return (
        Path(settings.data_dir)
        / CACHE_SUBDIR
        / market
        / symbol
        / tf
        / indicator_id
        / f"{phash}.parquet"
    )


def compute_raw(def_: IndicatorDef, ohlcv: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Dispatch to the indicator's source; returns a frame of its output columns."""
    if def_.source == "talib":
        from app.indicators.sources import compute_talib

        return compute_talib(def_, ohlcv, params)
    if def_.source == "pandas_ta":
        from app.indicators.sources import compute_pandas_ta

        return compute_pandas_ta(def_, ohlcv, params)
    if def_.source == "custom":
        from app.indicators.loader import compute_custom

        return compute_custom(def_, ohlcv, params)
    raise ValueError(f"unknown indicator source: {def_.source!r}")


def _is_fresh(cached: pd.DataFrame, ohlcv: pd.DataFrame) -> bool:
    """A cache entry is fresh when it covers exactly the current bar set."""
    if len(cached) != len(ohlcv):
        return False
    if ohlcv.empty:
        return True
    return int(cached["ts"].iloc[-1]) == int(ohlcv["ts"].iloc[-1])


def compute_indicator(
    market: str,
    symbol: str,
    tf: str,
    indicator_id: str,
    params: dict | None = None,
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Compute one indicator for a symbol × tf, cached by params_hash.

    Returns a frame with a ``ts`` column plus the indicator's output columns.
    Caching applies to the full stored series; ``start_ts``/``end_ts`` slice the
    (cached) result for previews.
    """
    def_ = get_indicator(indicator_id)
    if def_ is None:
        raise KeyError(f"unknown indicator: {indicator_id!r}")

    ohlcv = query_ohlcv(market, symbol, tf)
    phash = params_hash(def_, params)
    path = cache_path(market, symbol, tf, indicator_id, phash)
    merged = effective_params(def_, params)

    result: pd.DataFrame | None = None
    if use_cache and path.exists():
        cached = pd.read_parquet(path)
        if _is_fresh(cached, ohlcv):
            logger.info(
                "indicator cache HIT %s/%s/%s %s#%s rows=%d",
                market, symbol, tf, indicator_id, phash, len(cached),
            )
            result = cached

    if result is None:
        if ohlcv.empty:
            result = pd.DataFrame({"ts": pd.Series(dtype="int64")})
            for col in def_.outputs:
                result[col] = pd.Series(dtype="float64")
        else:
            raw = compute_raw(def_, ohlcv, merged)
            result = pd.concat(
                [ohlcv["ts"].reset_index(drop=True), raw.reset_index(drop=True)], axis=1
            )
        if use_cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            result.to_parquet(path, index=False)
        logger.info(
            "indicator cache MISS %s/%s/%s %s#%s rows=%d",
            market, symbol, tf, indicator_id, phash, len(result),
        )

    if start_ts is not None:
        result = result[result["ts"] >= int(start_ts)]
    if end_ts is not None:
        result = result[result["ts"] <= int(end_ts)]
    return result.reset_index(drop=True)
