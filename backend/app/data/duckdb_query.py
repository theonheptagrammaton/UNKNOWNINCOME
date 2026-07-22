"""DuckDB query layer over the Parquet store.

DuckDB reads Parquet directly, so range queries stay fast without loading whole
files into pandas first.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from app.data.parquet_store import (
    OHLCV_BASE_COLUMNS,
    OHLCV_TAKER_COLUMNS,
    OPEN_INTEREST_COLUMNS,
    OPEN_INTEREST_DATASET,
    dataset_path,
)
from app.data.timeframes import FUNDING_TF


def _parquet_columns(con: duckdb.DuckDBPyConnection, path: str) -> set[str]:
    """Column names present in a parquet file (via a zero-row DESCRIBE)."""
    rows = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()
    return {r[0] for r in rows}


def query_ohlcv(
    market: str,
    symbol: str,
    tf: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
    *,
    include_extended: bool = False,
) -> pd.DataFrame:
    """Return OHLCV rows for a symbol × tf in ``[start_ts, end_ts]`` (inclusive).

    With ``include_extended`` the taker-flow columns (§25.2) are appended; files
    written before Faz 11 lack them, so they are selected as ``NULL`` (→ NaN) to
    keep a stable schema for the ``flow_imbalance`` primitive.
    """
    base_cols = list(OHLCV_BASE_COLUMNS)
    path = dataset_path(market, symbol, tf)
    if not path.exists():
        cols = base_cols + (OHLCV_TAKER_COLUMNS if include_extended else [])
        return pd.DataFrame(columns=cols)

    conditions: list[str] = []
    params: list[object] = [str(path)]
    if start_ts is not None:
        conditions.append("ts >= ?")
        params.append(int(start_ts))
    if end_ts is not None:
        conditions.append("ts <= ?")
        params.append(int(end_ts))
    where = f"WHERE {' AND '.join(conditions)} " if conditions else ""

    con = duckdb.connect()
    try:
        select_cols = list(base_cols)
        if include_extended:
            present = _parquet_columns(con, str(path))
            for col in OHLCV_TAKER_COLUMNS:
                select_cols.append(col if col in present else f"NULL AS {col}")
        sql = f"SELECT {', '.join(select_cols)} FROM read_parquet(?) {where}ORDER BY ts"
        return con.execute(sql, params).df()
    finally:
        con.close()


def query_open_interest(
    market: str,
    symbol: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> pd.DataFrame:
    """Return OI snapshots ``[ts, open_interest, open_interest_value]`` (§25.3).

    An absent file means no OI has been collected yet (empty frame) — the
    ``oi_divergence`` primitive then contributes no signal.
    """
    path = dataset_path(market, symbol, OPEN_INTEREST_DATASET)
    if not path.exists():
        return pd.DataFrame(columns=OPEN_INTEREST_COLUMNS)

    conditions: list[str] = []
    params: list[object] = [str(path)]
    if start_ts is not None:
        conditions.append("ts >= ?")
        params.append(int(start_ts))
    if end_ts is not None:
        conditions.append("ts <= ?")
        params.append(int(end_ts))
    where = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    sql = (
        "SELECT ts, open_interest, open_interest_value "
        f"FROM read_parquet(?) {where}ORDER BY ts"
    )
    con = duckdb.connect()
    try:
        return con.execute(sql, params).df()
    finally:
        con.close()


def query_funding(
    market: str,
    symbol: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> pd.DataFrame:
    """Return funding rows ``[ts, funding_rate]`` in ``[start_ts, end_ts]`` (inclusive).

    Funding settles every 8h (doc §6.2); an absent file means no funding data
    (an empty frame — the cost model then contributes zero funding).
    """
    path = dataset_path(market, symbol, FUNDING_TF)
    if not path.exists():
        return pd.DataFrame(columns=["ts", "funding_rate"])

    conditions: list[str] = []
    params: list[object] = [str(path)]
    if start_ts is not None:
        conditions.append("ts >= ?")
        params.append(int(start_ts))
    if end_ts is not None:
        conditions.append("ts <= ?")
        params.append(int(end_ts))
    where = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    sql = f"SELECT ts, funding_rate FROM read_parquet(?) {where}ORDER BY ts"
    con = duckdb.connect()
    try:
        return con.execute(sql, params).df()
    finally:
        con.close()


def count_ohlcv(market: str, symbol: str, tf: str) -> int:
    """Row count for a symbol × tf parquet (0 if absent)."""
    path = dataset_path(market, symbol, tf)
    if not path.exists():
        return 0
    con = duckdb.connect()
    try:
        return int(con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0])
    finally:
        con.close()
