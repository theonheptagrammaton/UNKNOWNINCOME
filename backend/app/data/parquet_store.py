"""Parquet store for market data.

Layout: ``{data_dir}/{market}/{symbol}/{tf}.parquet`` for OHLCV,
``{data_dir}/{market}/{symbol}/funding.parquet`` for funding history and
``{data_dir}/{market}/{symbol}/open_interest.parquet`` for OI snapshots (Faz 11).
Writes merge on ``ts`` (dedup, keep-last) and keep the file sorted.

**Taker flow (Faz 11 §25.2).** The Binance kline response already carries
``taker_buy_base_volume`` and ``number_of_trades``; before Faz 11 they were
dropped. They are now *optional* trailing OHLCV columns: a frame that supplies
them stores 8 columns, a legacy/6-column frame stores 6, and a merge of the two
leaves the old rows' taker fields NaN (they genuinely never had them). No schema
migration is forced on files downloaded before this phase.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.data.timeframes import FUNDING_TF

# Base OHLCV columns every bar has.
OHLCV_BASE_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
# Optional taker-flow columns (Faz 11 §25.2), in Binance kline order after volume.
OHLCV_TAKER_COLUMNS = ["taker_buy_base_volume", "number_of_trades"]
# Kept for callers that want the full possible schema.
OHLCV_COLUMNS = OHLCV_BASE_COLUMNS + OHLCV_TAKER_COLUMNS

FUNDING_COLUMNS = ["ts", "funding_rate"]

OPEN_INTEREST_DATASET = "open_interest"
OPEN_INTEREST_COLUMNS = ["ts", "open_interest", "open_interest_value"]

# Per-minute liquidation notional, aggregated from the `liquidations` table (Faz 11
# §25.3). Kept in Parquet so the `liq_cascade` primitive reads it through DuckDB on
# the same sync path as every other alpha input — no live DB driver in the compute
# layer. ``liq_sell_notional`` = longs force-sold (down pressure); ``liq_buy_notional``
# = shorts force-bought (up pressure).
LIQUIDATION_DATASET = "liquidations"
LIQUIDATION_COLUMNS = ["ts", "liq_buy_notional", "liq_sell_notional"]


def dataset_path(market: str, symbol: str, name: str) -> Path:
    """Absolute path to a symbol's ``{name}.parquet`` (tf, ``funding`` or ``open_interest``)."""
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


def _ohlcv_columns(frame: pd.DataFrame) -> list[str]:
    """Base OHLCV columns plus any taker column actually present in ``frame``."""
    return OHLCV_BASE_COLUMNS + [c for c in OHLCV_TAKER_COLUMNS if c in frame.columns]


def write_ohlcv(market: str, symbol: str, tf: str, rows: pd.DataFrame) -> int:
    """Merge OHLCV rows into the tf parquet; returns total row count.

    Taker columns are written only when the frame supplies them, so a 6-column
    (legacy) frame stays 6 columns and never fabricates zeros for taker flow.
    """
    return _merge_write(dataset_path(market, symbol, tf), rows, _ohlcv_columns(rows))


def write_funding(market: str, symbol: str, rows: pd.DataFrame) -> int:
    """Merge funding rows into the funding parquet; returns total row count."""
    return _merge_write(dataset_path(market, symbol, FUNDING_TF), rows, FUNDING_COLUMNS)


def write_open_interest(market: str, symbol: str, rows: pd.DataFrame) -> int:
    """Merge OI snapshots into the open_interest parquet; returns total row count."""
    return _merge_write(
        dataset_path(market, symbol, OPEN_INTEREST_DATASET), rows, OPEN_INTEREST_COLUMNS
    )


def read_ohlcv(market: str, symbol: str, tf: str) -> pd.DataFrame:
    """Read the full OHLCV parquet (empty base-column frame if absent)."""
    path = dataset_path(market, symbol, tf)
    if not path.exists():
        return pd.DataFrame(columns=OHLCV_BASE_COLUMNS)
    return pd.read_parquet(path)


def read_open_interest(market: str, symbol: str) -> pd.DataFrame:
    """Read the full open-interest parquet (empty frame if absent)."""
    path = dataset_path(market, symbol, OPEN_INTEREST_DATASET)
    if not path.exists():
        return pd.DataFrame(columns=OPEN_INTEREST_COLUMNS)
    return pd.read_parquet(path)


def write_liquidation_bars(market: str, symbol: str, rows: pd.DataFrame) -> int:
    """Merge per-minute liquidation-notional rows into the liquidations parquet."""
    return _merge_write(
        dataset_path(market, symbol, LIQUIDATION_DATASET), rows, LIQUIDATION_COLUMNS
    )


def read_liquidation_bars(market: str, symbol: str) -> pd.DataFrame:
    """Read the full liquidation-notional parquet (empty frame if absent)."""
    path = dataset_path(market, symbol, LIQUIDATION_DATASET)
    if not path.exists():
        return pd.DataFrame(columns=LIQUIDATION_COLUMNS)
    return pd.read_parquet(path)


def timestamps(market: str, symbol: str, tf: str) -> list[int]:
    """Sorted list of stored bar-open timestamps for a symbol × tf."""
    df = read_ohlcv(market, symbol, tf)
    if df.empty:
        return []
    return sorted(int(t) for t in df["ts"].tolist())


def ohlcv_rows_to_frame(rows: list[list[float]]) -> pd.DataFrame:
    """Convert ccxt-style OHLCV rows to a typed frame.

    Accepts both 6-wide ``[ts, o, h, l, c, v]`` and the extended 8-wide
    ``[ts, o, h, l, c, v, taker_buy_base_volume, number_of_trades]`` (Faz 11):
    the extra trailing columns are named only when present.
    """
    if not rows:
        return pd.DataFrame(columns=OHLCV_BASE_COLUMNS)
    extra = max(0, len(rows[0]) - len(OHLCV_BASE_COLUMNS))
    cols = OHLCV_BASE_COLUMNS + OHLCV_TAKER_COLUMNS[:extra]
    return pd.DataFrame(rows, columns=cols)
