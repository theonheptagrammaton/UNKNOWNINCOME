"""Parquet store for market data.

Layout: ``{data_dir}/{market}/{symbol}/{tf}.parquet`` for OHLCV and
``{data_dir}/{market}/{symbol}/funding.parquet`` for funding history.
Writes merge on ``ts`` (dedup, keep-last) and keep the file sorted.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.data.timeframes import FUNDING_TF

OHLCV_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
FUNDING_COLUMNS = ["ts", "funding_rate"]


def dataset_path(market: str, symbol: str, name: str) -> Path:
    """Absolute path to a symbol's ``{name}.parquet`` (tf or ``funding``)."""
    return Path(settings.data_dir) / market / symbol / f"{name}.parquet"


def _merge_write(path: Path, new: pd.DataFrame, columns: Sequence[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = new.loc[:, list(columns)].dropna(subset=["ts"]).copy()
    frame["ts"] = frame["ts"].astype("int64")
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    frame = (
        frame.drop_duplicates(subset=["ts"], keep="last")
        .sort_values("ts")
        .reset_index(drop=True)
    )
    frame.to_parquet(path, index=False)
    return len(frame)


def write_ohlcv(market: str, symbol: str, tf: str, rows: pd.DataFrame) -> int:
    """Merge OHLCV rows into the tf parquet; returns total row count."""
    return _merge_write(dataset_path(market, symbol, tf), rows, OHLCV_COLUMNS)


def write_funding(market: str, symbol: str, rows: pd.DataFrame) -> int:
    """Merge funding rows into the funding parquet; returns total row count."""
    return _merge_write(dataset_path(market, symbol, FUNDING_TF), rows, FUNDING_COLUMNS)


def read_ohlcv(market: str, symbol: str, tf: str) -> pd.DataFrame:
    """Read the full OHLCV parquet (empty frame if absent)."""
    path = dataset_path(market, symbol, tf)
    if not path.exists():
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    return pd.read_parquet(path)


def timestamps(market: str, symbol: str, tf: str) -> list[int]:
    """Sorted list of stored bar-open timestamps for a symbol × tf."""
    df = read_ohlcv(market, symbol, tf)
    if df.empty:
        return []
    return sorted(int(t) for t in df["ts"].tolist())


def ohlcv_rows_to_frame(rows: list[list[float]]) -> pd.DataFrame:
    """Convert ccxt OHLCV rows ``[ts, o, h, l, c, v]`` to a typed frame."""
    return pd.DataFrame(rows, columns=OHLCV_COLUMNS)
