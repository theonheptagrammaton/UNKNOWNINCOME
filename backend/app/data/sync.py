"""Sync orchestration: backfill, incremental fetch, gap repair, sync-state.

Lookahead guard (doc §2 rule 1): only *fully closed* bars are stored — the
currently forming bar is never fetched.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.adapters.base import MarketDataAdapter, MarketInfo
from app.data.gaps import count_missing, find_gaps
from app.data.parquet_store import (
    ohlcv_rows_to_frame,
    timestamps,
    write_funding,
    write_ohlcv,
)
from app.data.timeframes import FUNDING_INTERVAL_MS, FUNDING_TF, last_closed_open_ts, tf_to_ms
from app.models.market import CandleSyncState


@dataclass
class SyncResult:
    market: str
    symbol: str
    tf: str
    total_rows: int
    first_ts: int | None
    last_ts: int | None
    residual_missing: int

    def as_dict(self) -> dict:
        return asdict(self)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _months_to_ms(months: float) -> int:
    return int(months * 30.5 * 86_400_000)


async def fetch_ohlcv_range(
    adapter: MarketDataAdapter,
    ccxt_symbol: str,
    tf: str,
    since_ms: int,
    until_ms: int,
    limit: int,
) -> list[list[float]]:
    """Paginated OHLCV fetch over ``[since_ms, until_ms)`` (bar open times)."""
    step = tf_to_ms(tf)
    out: list[list[float]] = []
    since = since_ms
    while since < until_ms:
        batch = await adapter.fetch_ohlcv(ccxt_symbol, tf, since, limit)
        batch = [r for r in batch if since_ms <= r[0] < until_ms]
        if not batch:
            break
        out.extend(batch)
        nxt = int(batch[-1][0]) + step
        if nxt <= since:  # no forward progress → stop
            break
        since = nxt
    return out


async def fetch_funding_range(
    adapter: MarketDataAdapter,
    ccxt_symbol: str,
    since_ms: int,
    until_ms: int,
    limit: int = 1000,
) -> pd.DataFrame:
    """Paginated funding-history fetch → frame ``[ts, funding_rate]``."""
    rows: list[dict[str, float]] = []
    since = since_ms
    while since < until_ms:
        batch = await adapter.fetch_funding_history(ccxt_symbol, since, limit)
        batch = [e for e in batch if since_ms <= int(e["timestamp"]) < until_ms]
        if not batch:
            break
        for entry in batch:
            rows.append(
                {"ts": int(entry["timestamp"]), "funding_rate": float(entry["fundingRate"])}
            )
        nxt = int(batch[-1]["timestamp"]) + 1
        if nxt <= since:
            break
        since = nxt
    return pd.DataFrame(rows, columns=["ts", "funding_rate"])


async def _get_or_create_state(
    session: AsyncSession, market: str, symbol: str, tf: str
) -> CandleSyncState:
    stmt = select(CandleSyncState).where(
        CandleSyncState.market == market,
        CandleSyncState.symbol == symbol,
        CandleSyncState.tf == tf,
    )
    state = (await session.execute(stmt)).scalar_one_or_none()
    if state is None:
        state = CandleSyncState(market=market, symbol=symbol, tf=tf, gaps=[])
        session.add(state)
    return state


async def update_sync_state(
    session: AsyncSession, market: str, symbol: str, tf: str
) -> CandleSyncState:
    """Recompute first/last/gaps from stored bars and persist sync-state."""
    present = timestamps(market, symbol, tf)
    gap_tf = FUNDING_TF if tf == FUNDING_TF else tf
    gaps = find_gaps(present, gap_tf)
    state = await _get_or_create_state(session, market, symbol, tf)
    state.first_ts = present[0] if present else None
    state.last_ts = present[-1] if present else None
    state.gaps = [[s, e] for s, e in gaps]
    await session.commit()
    return state


async def repair_ohlcv_gaps(
    adapter: MarketDataAdapter,
    market: str,
    ccxt_symbol: str,
    symbol: str,
    tf: str,
    limit: int,
) -> int:
    """Re-fetch and merge any interior gaps; returns rows fetched."""
    gaps = find_gaps(timestamps(market, symbol, tf), tf)
    step = tf_to_ms(tf)
    filled = 0
    for start, end in gaps:
        rows = await fetch_ohlcv_range(adapter, ccxt_symbol, tf, start, end + step, limit)
        if rows:
            write_ohlcv(market, symbol, tf, ohlcv_rows_to_frame(rows))
            filled += len(rows)
    return filled


async def backfill_ohlcv(
    adapter: MarketDataAdapter,
    session: AsyncSession,
    market: str,
    ccxt_symbol: str,
    symbol: str,
    tf: str,
    months: float,
    limit: int,
    now_ms: int | None = None,
) -> SyncResult:
    """Backfill ``months`` of OHLCV, repair gaps, update sync-state."""
    now = now_ms if now_ms is not None else _now_ms()
    step = tf_to_ms(tf)
    until = last_closed_open_ts(now, tf) + step
    since = ((now - _months_to_ms(months)) // step) * step
    rows = await fetch_ohlcv_range(adapter, ccxt_symbol, tf, since, until, limit)
    if rows:
        write_ohlcv(market, symbol, tf, ohlcv_rows_to_frame(rows))
    await repair_ohlcv_gaps(adapter, market, ccxt_symbol, symbol, tf, limit)
    return await _finish(session, market, symbol, tf)


async def incremental_ohlcv(
    adapter: MarketDataAdapter,
    session: AsyncSession,
    market: str,
    ccxt_symbol: str,
    symbol: str,
    tf: str,
    limit: int,
    now_ms: int | None = None,
) -> SyncResult:
    """Fetch only newly closed bars since the last stored bar."""
    now = now_ms if now_ms is not None else _now_ms()
    step = tf_to_ms(tf)
    until = last_closed_open_ts(now, tf) + step
    present = timestamps(market, symbol, tf)
    since = (present[-1] + step) if present else until - limit * step
    if since < until:
        rows = await fetch_ohlcv_range(adapter, ccxt_symbol, tf, since, until, limit)
        if rows:
            write_ohlcv(market, symbol, tf, ohlcv_rows_to_frame(rows))
    await repair_ohlcv_gaps(adapter, market, ccxt_symbol, symbol, tf, limit)
    return await _finish(session, market, symbol, tf)


async def backfill_funding(
    adapter: MarketDataAdapter,
    session: AsyncSession,
    market: str,
    ccxt_symbol: str,
    symbol: str,
    months: float,
    now_ms: int | None = None,
) -> SyncResult:
    """Backfill ``months`` of funding history and update sync-state."""
    now = now_ms if now_ms is not None else _now_ms()
    until = (now // FUNDING_INTERVAL_MS) * FUNDING_INTERVAL_MS
    since = now - _months_to_ms(months)
    frame = await fetch_funding_range(adapter, ccxt_symbol, since, until)
    if not frame.empty:
        write_funding(market, symbol, frame)
    return await _finish(session, market, symbol, FUNDING_TF)


async def _finish(session: AsyncSession, market: str, symbol: str, tf: str) -> SyncResult:
    state = await update_sync_state(session, market, symbol, tf)
    gap_tf = FUNDING_TF if tf == FUNDING_TF else tf
    present = timestamps(market, symbol, tf)
    return SyncResult(
        market=market,
        symbol=symbol,
        tf=tf,
        total_rows=len(present),
        first_ts=state.first_ts,
        last_ts=state.last_ts,
        residual_missing=count_missing([tuple(g) for g in state.gaps], gap_tf),
    )


async def resolve_market_infos(
    adapter: MarketDataAdapter, symbols: list[str]
) -> list[MarketInfo]:
    """Map requested normalized symbols to exchange ``MarketInfo`` (skips unknown)."""
    catalog = {m.symbol: m for m in await adapter.list_markets()}
    return [catalog[s.upper()] for s in symbols if s.upper() in catalog]


async def sync_symbol(
    adapter: MarketDataAdapter,
    session: AsyncSession,
    info: MarketInfo,
    timeframes: list[str],
    months: float,
    funding: bool,
    limit: int,
    *,
    incremental: bool = False,
    now_ms: int | None = None,
) -> list[SyncResult]:
    """Sync one symbol across timeframes (+ optional funding)."""
    results: list[SyncResult] = []
    for tf in timeframes:
        if incremental:
            result = await incremental_ohlcv(
                adapter, session, adapter.market, info.ccxt_symbol, info.symbol, tf, limit, now_ms
            )
        else:
            result = await backfill_ohlcv(
                adapter,
                session,
                adapter.market,
                info.ccxt_symbol,
                info.symbol,
                tf,
                months,
                limit,
                now_ms,
            )
        results.append(result)
    if funding:
        results.append(
            await backfill_funding(
                adapter, session, adapter.market, info.ccxt_symbol, info.symbol, months, now_ms
            )
        )
    return results
