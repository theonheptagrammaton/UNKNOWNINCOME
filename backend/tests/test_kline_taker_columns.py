"""Faz 11 §25.2 — taker-flow columns in the OHLCV schema.

``taker_buy_base_volume`` and ``number_of_trades`` are already in every Binance kline;
they are now optional trailing Parquet columns. Files written before Faz 11 lack them,
so the store must stay backward-compatible: a legacy 6-column file merges with an
extended 8-column write leaving the old rows' taker fields NaN, and the DuckDB read
surfaces the columns (NULL → NaN) so ``flow_imbalance`` always has a stable schema.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.duckdb_query import query_ohlcv
from app.data.parquet_store import (
    OHLCV_TAKER_COLUMNS,
    ohlcv_rows_to_frame,
    read_ohlcv,
    write_ohlcv,
)
from app.data.sync import backfill_ohlcv
from app.data.timeframes import last_closed_open_ts, tf_to_ms
from fakes import FakeAdapter

MKT = "binance_usdm"
CCXT = "BTC/USDT:USDT"
SYM = "BTCUSDT"
NOW = 1_700_000_000_000


def _extended_rows(start: int, count: int, step: int) -> list[list[float]]:
    """8-wide rows ``[ts,o,h,l,c,v, taker_buy_base_volume, number_of_trades]``."""
    rows: list[list[float]] = []
    for i in range(count):
        p = 100.0 + i
        vol = 10.0 + i
        rows.append([start + i * step, p, p + 1, p - 1, p + 0.5, vol, vol * 0.6, 42.0])
    return rows


def test_rows_to_frame_handles_both_widths() -> None:
    six = ohlcv_rows_to_frame([[0, 1, 2, 0.5, 1.5, 9]])
    assert list(six.columns) == ["ts", "open", "high", "low", "close", "volume"]
    eight = ohlcv_rows_to_frame([[0, 1, 2, 0.5, 1.5, 9, 5.4, 42]])
    assert list(eight.columns) == [
        "ts", "open", "high", "low", "close", "volume",
        "taker_buy_base_volume", "number_of_trades",
    ]


def test_extended_write_roundtrip(data_dir: Path) -> None:
    tf = "1h"
    step = tf_to_ms(tf)
    write_ohlcv(MKT, SYM, tf, ohlcv_rows_to_frame(_extended_rows(0, 5, step)))
    stored = read_ohlcv(MKT, SYM, tf)
    for col in OHLCV_TAKER_COLUMNS:
        assert col in stored.columns
    out = query_ohlcv(MKT, SYM, tf, include_extended=True)
    assert out["taker_buy_base_volume"].tolist() == pytest.approx([6.0, 6.6, 7.2, 7.8, 8.4])
    assert set(out["number_of_trades"]) == {42.0}


def test_legacy_file_reads_taker_as_nan(data_dir: Path) -> None:
    """A 6-column (pre-Faz-11) file yields NaN taker columns, never a query error."""
    tf = "1h"
    step = tf_to_ms(tf)
    legacy = [[i * step, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 10.0 + i] for i in range(4)]
    write_ohlcv(MKT, SYM, tf, ohlcv_rows_to_frame(legacy))
    assert list(read_ohlcv(MKT, SYM, tf).columns) == [
        "ts", "open", "high", "low", "close", "volume",
    ]
    out = query_ohlcv(MKT, SYM, tf, include_extended=True)
    assert "taker_buy_base_volume" in out.columns
    assert out["taker_buy_base_volume"].isna().all()
    # Base (non-extended) read is unchanged — no taker columns.
    assert "taker_buy_base_volume" not in query_ohlcv(MKT, SYM, tf).columns


def test_merge_legacy_then_extended_keeps_old_rows_nan(data_dir: Path) -> None:
    tf = "1h"
    step = tf_to_ms(tf)
    legacy = [[i * step, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 10.0 + i] for i in range(3)]
    write_ohlcv(MKT, SYM, tf, ohlcv_rows_to_frame(legacy))
    write_ohlcv(MKT, SYM, tf, ohlcv_rows_to_frame(_extended_rows(3 * step, 3, step)))
    out = query_ohlcv(MKT, SYM, tf, include_extended=True).sort_values("ts")
    taker = out["taker_buy_base_volume"].to_numpy()
    assert np.isnan(taker[:3]).all()  # old rows never had taker flow
    assert np.isfinite(taker[3:]).all()  # new rows do


async def test_backfill_carries_taker_columns(db_session: AsyncSession, data_dir: Path) -> None:
    """The extended adapter rows flow through sync into the Parquet schema (§25.2 KABUL)."""
    tf = "1h"
    step = tf_to_ms(tf)
    last = last_closed_open_ts(NOW, tf)
    count = 50
    start = last - (count - 1) * step
    adapter = FakeAdapter(series={(CCXT, tf): _extended_rows(start, count, step)})

    res = await backfill_ohlcv(adapter, db_session, MKT, CCXT, SYM, tf, 1, 1500, now_ms=NOW)

    assert res.total_rows == count
    out = query_ohlcv(MKT, SYM, tf, include_extended=True)
    assert out["taker_buy_base_volume"].notna().all()
    assert out["number_of_trades"].notna().all()
