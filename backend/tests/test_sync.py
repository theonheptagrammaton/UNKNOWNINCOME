"""Tests for sync orchestration: backfill, incremental, gap repair (gap=0)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.data.gaps import find_gaps
from app.data.parquet_store import ohlcv_rows_to_frame, timestamps, write_ohlcv
from app.data.sync import (
    backfill_ohlcv,
    incremental_ohlcv,
    repair_ohlcv_gaps,
    update_sync_state,
)
from app.data.timeframes import last_closed_open_ts, tf_to_ms
from fakes import FakeAdapter, make_ohlcv

MKT = "binance_usdm"
CCXT = "BTC/USDT:USDT"
SYM = "BTCUSDT"
NOW = 1_700_000_000_000


async def test_backfill_is_gap_free(db_session: AsyncSession, data_dir: Path) -> None:
    tf = "1h"
    step = tf_to_ms(tf)
    last = last_closed_open_ts(NOW, tf)
    count = 300
    start = last - (count - 1) * step
    adapter = FakeAdapter(series={(CCXT, tf): make_ohlcv(start, count, tf)})

    res = await backfill_ohlcv(adapter, db_session, MKT, CCXT, SYM, tf, 1, 1500, now_ms=NOW)

    assert res.total_rows == count
    assert res.first_ts == start
    assert res.last_ts == last  # forming bar excluded
    assert res.residual_missing == 0


async def test_incremental_appends_new_bars(db_session: AsyncSession, data_dir: Path) -> None:
    tf = "1h"
    step = tf_to_ms(tf)
    last = last_closed_open_ts(NOW, tf)
    count = 100
    start = last - (count - 1) * step
    full = make_ohlcv(start, count + 5, tf)

    adapter = FakeAdapter(series={(CCXT, tf): full[:count]})
    await backfill_ohlcv(adapter, db_session, MKT, CCXT, SYM, tf, 1, 1500, now_ms=NOW)

    adapter.series[(CCXT, tf)] = full
    new_now = NOW + 5 * step
    res = await incremental_ohlcv(adapter, db_session, MKT, CCXT, SYM, tf, 1500, now_ms=new_now)

    assert res.total_rows == count + 5
    assert res.last_ts == last_closed_open_ts(new_now, tf)
    assert res.residual_missing == 0


async def test_gap_detection_and_repair(db_session: AsyncSession, data_dir: Path) -> None:
    tf = "1h"
    step = tf_to_ms(tf)
    base = 1000 * step
    full = make_ohlcv(base, 50, tf)
    holey = full[:20] + full[25:]  # remove 5 interior bars
    write_ohlcv(MKT, SYM, tf, ohlcv_rows_to_frame(holey))

    assert len(find_gaps(timestamps(MKT, SYM, tf), tf)) == 1

    adapter = FakeAdapter(series={(CCXT, tf): full})
    filled = await repair_ohlcv_gaps(adapter, MKT, CCXT, SYM, tf, 1500)
    assert filled >= 5

    state = await update_sync_state(db_session, MKT, SYM, tf)
    assert state.gaps == []
    assert len(timestamps(MKT, SYM, tf)) == 50
