"""Alpha-surface data access (Faz 11 §25.3).

The four new primitives need inputs beyond OHLCV: open interest, funding history and
liquidation flow. This module is the single lookahead-safe bridge between those stores
and the (synchronous) indicator compute path:

* :func:`align_backward` / :func:`open_interest_aligned` / :func:`funding_aligned`
  attach a time series to a bar grid with ``merge_asof(direction="backward")`` — each
  bar sees only the last observation **at or before its open**, so no future value can
  leak into a past bar (pazarlıksız kural #1).
* :func:`query_liquidations` reads the live-collected ``liquidations`` table and
  :func:`aggregate_liquidations` folds it into a per-minute notional Parquet; the
  compute layer then reads that through DuckDB (:func:`liq_notional_aligned`) with **no
  live DB driver** — the same sync path as every other alpha input.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.duckdb_query import query_funding, query_open_interest
from app.data.parquet_store import (
    LIQUIDATION_COLUMNS,
    read_liquidation_bars,
    write_liquidation_bars,
)
from app.models.market import Liquidation

# Liquidation notional is bucketed at 1-minute resolution, then summed up into
# whatever bar the caller asks for — finer than any tradeable timeframe.
LIQ_BAR_MS = 60_000


def align_backward(
    ts: pd.Series, source: pd.DataFrame, value_cols: list[str]
) -> pd.DataFrame:
    """As-of-backward join of ``source`` (``ts`` + ``value_cols``) onto a bar grid.

    Returns a frame indexed row-for-row with ``ts``: each bar carries the most recent
    ``source`` row whose ``ts`` is ≤ the bar's open. Bars before the first observation
    are NaN. Lookahead-safe by construction (``direction="backward"``).
    """
    left = pd.DataFrame({"ts": pd.Series(ts, dtype="int64").reset_index(drop=True)})
    if source is None or source.empty:
        for col in value_cols:
            left[col] = np.nan
        return left
    right = source.loc[:, ["ts", *value_cols]].copy()
    right["ts"] = right["ts"].astype("int64")
    right = right.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    merged = pd.merge_asof(left.sort_values("ts"), right, on="ts", direction="backward")
    return merged.sort_index().reset_index(drop=True)


def open_interest_aligned(market: str, symbol: str, ts: pd.Series) -> pd.Series:
    """Open-interest amount aligned to a bar grid (NaN before first OI sample)."""
    oi = query_open_interest(market, symbol)
    merged = align_backward(ts, oi, ["open_interest"])
    return merged["open_interest"].astype("float64")


def funding_aligned(market: str, symbol: str, ts: pd.Series) -> pd.Series:
    """Funding rate (last settled) aligned to a bar grid (NaN before first funding)."""
    funding = query_funding(market, symbol)
    merged = align_backward(ts, funding, ["funding_rate"])
    return merged["funding_rate"].astype("float64")


def funding_history(market: str, symbol: str) -> pd.DataFrame:
    """Native (sparse, 8h) funding series ``[ts, funding_rate]`` for percentile work."""
    return query_funding(market, symbol)


def liq_notional_aligned(
    market: str, symbol: str, ts: pd.Series, step_ms: int
) -> tuple[pd.Series, pd.Series]:
    """Per-bar (buy, sell) liquidation notional summed into ``ts``'s bars.

    Reads the per-minute liquidation Parquet and sums every minute-bucket that falls
    **inside** each bar ``[open, open+step)`` — activity during the bar, fully known at
    its close. Bars with no liquidations are 0. Absent data → all zeros (no signal).
    """
    bars = pd.Series(ts, dtype="int64").reset_index(drop=True)
    zero = pd.Series(0.0, index=bars.index)
    liq = read_liquidation_bars(market, symbol)
    if liq.empty or len(bars) == 0 or step_ms <= 0:
        return zero.copy(), zero.copy()
    liq = liq.copy()
    liq["bar"] = (liq["ts"].astype("int64") // step_ms) * step_ms
    grouped = liq.groupby("bar")[["liq_buy_notional", "liq_sell_notional"]].sum()
    bar_open = (bars // step_ms) * step_ms
    buy = bar_open.map(grouped["liq_buy_notional"]).fillna(0.0).astype("float64")
    sell = bar_open.map(grouped["liq_sell_notional"]).fillna(0.0).astype("float64")
    return buy.reset_index(drop=True), sell.reset_index(drop=True)


async def query_liquidations(
    session: AsyncSession,
    market: str,
    symbol: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[Liquidation]:
    """Read forced-liquidation events (Faz 8 stream) for a symbol, ordered by trade time.

    This is the "liquidations are now queryable" surface (§25.3); the primitive path
    consumes the aggregated Parquet, but the raw events stay directly readable.
    """
    stmt = (
        select(Liquidation)
        .where(Liquidation.market == market, Liquidation.symbol == symbol)
        .order_by(Liquidation.trade_time)
    )
    if start_ts is not None:
        stmt = stmt.where(Liquidation.trade_time >= int(start_ts))
    if end_ts is not None:
        stmt = stmt.where(Liquidation.trade_time <= int(end_ts))
    return list((await session.execute(stmt)).scalars().all())


async def aggregate_liquidations(
    session: AsyncSession,
    market: str,
    symbol: str,
    since_ms: int | None = None,
) -> int:
    """Fold liquidation events into per-minute notional buckets and persist to Parquet.

    Buckets ``>= since_ms`` are recomputed **in full** (dedup makes the events stable,
    so a keep-last merge is idempotent). SELL orders liquidate longs (down pressure) →
    ``liq_sell_notional``; BUY orders liquidate shorts (up pressure) → ``liq_buy_notional``.
    Returns the number of minute-buckets written.
    """
    events = await query_liquidations(session, market, symbol, start_ts=since_ms)
    if not events:
        return 0
    frame = pd.DataFrame(
        {
            "ts": [(int(e.trade_time) // LIQ_BAR_MS) * LIQ_BAR_MS for e in events],
            "side": [str(e.side).upper() for e in events],
            "quote_qty": [float(e.quote_qty) for e in events],
        }
    )
    frame["liq_sell_notional"] = np.where(
        frame["side"] == "SELL", frame["quote_qty"], 0.0
    )
    frame["liq_buy_notional"] = np.where(
        frame["side"] == "BUY", frame["quote_qty"], 0.0
    )
    bars = (
        frame.groupby("ts")[["liq_buy_notional", "liq_sell_notional"]]
        .sum()
        .reset_index()
        .loc[:, LIQUIDATION_COLUMNS]
    )
    write_liquidation_bars(market, symbol, bars)
    return len(bars)
