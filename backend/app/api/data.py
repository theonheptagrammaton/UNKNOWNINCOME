"""Market-data API: trigger sync jobs and inspect coverage (doc §12)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.queue import enqueue
from app.data.duckdb_query import count_ohlcv
from app.data.gaps import expected_count
from app.models.market import CandleSyncState

router = APIRouter(prefix="/data", tags=["data"])


class SyncRequest(BaseModel):
    symbols: list[str] | None = None  # None → latest universe snapshot
    timeframes: list[str] | None = None
    months: float | None = None
    funding: bool = True
    incremental: bool = False


@router.post("/sync", status_code=202)
async def trigger_sync(body: SyncRequest) -> dict:
    """Queue a background sync job; returns 202 with the job id."""
    timeframes = body.timeframes or settings.default_timeframes
    months = body.months if body.months is not None else settings.default_lookback_months
    job_id = await enqueue(
        "sync_data_job", body.symbols, timeframes, months, body.funding, body.incremental
    )
    return {
        "status": "queued",
        "job_id": job_id,
        "symbols": body.symbols,
        "timeframes": timeframes,
        "months": months,
        "funding": body.funding,
        "incremental": body.incremental,
    }


@router.get("/status")
async def data_status(session: AsyncSession = Depends(get_session)) -> dict:
    """Per symbol × timeframe coverage: first/last bar, row count, gaps."""
    stmt = select(CandleSyncState).order_by(
        CandleSyncState.symbol, CandleSyncState.tf
    )
    rows = (await session.execute(stmt)).scalars().all()

    series: list[dict] = []
    total_missing = 0
    for r in rows:
        actual = count_ohlcv(r.market, r.symbol, r.tf)
        if r.first_ts is not None and r.last_ts is not None:
            expected = expected_count(r.first_ts, r.last_ts, r.tf)
        else:
            expected = 0
        missing = max(expected - actual, 0)
        total_missing += missing
        series.append(
            {
                "market": r.market,
                "symbol": r.symbol,
                "tf": r.tf,
                "first_ts": r.first_ts,
                "last_ts": r.last_ts,
                "rows": actual,
                "expected": expected,
                "missing": missing,
                "gaps": len(r.gaps or []),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )

    return {
        "summary": {
            "symbols": len({r.symbol for r in rows}),
            "series": len(rows),
            "total_missing": total_missing,
        },
        "series": series,
    }
