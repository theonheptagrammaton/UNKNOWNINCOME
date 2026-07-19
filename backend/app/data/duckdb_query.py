"""DuckDB query layer over the Parquet store.

DuckDB reads Parquet directly, so range queries stay fast without loading whole
files into pandas first.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from app.data.parquet_store import dataset_path
from app.data.timeframes import FUNDING_TF


def query_ohlcv(
    market: str,
    symbol: str,
    tf: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> pd.DataFrame:
    """Return OHLCV rows for a symbol × tf in ``[start_ts, end_ts]`` (inclusive)."""
    path = dataset_path(market, symbol, tf)
    if not path.exists():
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

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
        "SELECT ts, open, high, low, close, volume "
        "FROM read_parquet(?) "
        f"{where}ORDER BY ts"
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
