"""Tests for the Parquet store."""

from __future__ import annotations

from pathlib import Path

from app.data.parquet_store import (
    ohlcv_rows_to_frame,
    read_ohlcv,
    timestamps,
    write_ohlcv,
)
from app.data.timeframes import tf_to_ms
from fakes import make_ohlcv


def test_write_read_roundtrip(data_dir: Path) -> None:
    n = write_ohlcv("m", "BTCUSDT", "1h", ohlcv_rows_to_frame(make_ohlcv(0, 10, "1h")))
    assert n == 10
    df = read_ohlcv("m", "BTCUSDT", "1h")
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(df) == 10


def test_merge_dedup_sort(data_dir: Path) -> None:
    tf = "1h"
    step = tf_to_ms(tf)
    write_ohlcv("m", "S", tf, ohlcv_rows_to_frame(make_ohlcv(0, 5, tf)))
    total = write_ohlcv("m", "S", tf, ohlcv_rows_to_frame(make_ohlcv(3 * step, 5, tf)))
    assert total == 8  # 0..4 merged with 3..7 → 0..7 unique
    assert timestamps("m", "S", tf) == [i * step for i in range(8)]


def test_read_missing_returns_empty(data_dir: Path) -> None:
    assert read_ohlcv("m", "NOPE", "1h").empty
    assert timestamps("m", "NOPE", "1h") == []
