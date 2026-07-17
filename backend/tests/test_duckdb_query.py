"""Tests for the DuckDB query layer, including a range-query latency budget."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.duckdb_query import count_ohlcv, query_ohlcv
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.data.timeframes import tf_to_ms
from fakes import make_ohlcv


def test_query_range(data_dir: Path) -> None:
    tf = "1h"
    step = tf_to_ms(tf)
    write_ohlcv("m", "S", tf, ohlcv_rows_to_frame(make_ohlcv(0, 100, tf)))
    out = query_ohlcv("m", "S", tf, 10 * step, 20 * step)
    assert len(out) == 11
    assert int(out["ts"].iloc[0]) == 10 * step
    assert int(out["ts"].iloc[-1]) == 20 * step
    assert count_ohlcv("m", "S", tf) == 100


def test_query_missing_returns_empty(data_dir: Path) -> None:
    assert query_ohlcv("m", "NOPE", "1h").empty
    assert count_ohlcv("m", "NOPE", "1h") == 0


def test_range_query_under_1s(data_dir: Path) -> None:
    tf = "1m"
    step = tf_to_ms(tf)
    n = 300_000
    base = 1_600_000_000_000
    ts = np.arange(base, base + n * step, step, dtype=np.int64)
    price = np.linspace(100.0, 200.0, n)
    df = pd.DataFrame(
        {
            "ts": ts,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + 0.5,
            "volume": np.arange(n, dtype=float),
        }
    )
    write_ohlcv("m", "BIG", tf, df)

    start = base + 50_000 * step
    end = base + 150_000 * step
    t0 = time.perf_counter()
    out = query_ohlcv("m", "BIG", tf, start, end)
    elapsed = time.perf_counter() - t0

    assert len(out) == 100_001
    assert elapsed < 1.0, f"range query took {elapsed:.3f}s (budget 1s)"
