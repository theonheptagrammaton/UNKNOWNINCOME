"""Backtest API (doc §12): queue a run, read it back with its report."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.config import RunConfig, config_hash
from app.backtest.runner import NoDataError, run_backtest
from app.backtest.store import read_report
from app.core.db import get_session
from app.core.queue import enqueue
from app.models.backtest import BacktestRun

router = APIRouter(prefix="/backtest", tags=["backtest"])


class RunAccepted(BaseModel):
    run_id: str
    status: str
    config_hash: str


class PreviewResult(BaseModel):
    config_hash: str
    metrics: dict | None
    report: dict | None


class RunDetail(BaseModel):
    id: str
    status: str
    config: dict
    config_hash: str
    seed: int
    metrics: dict | None
    report: dict | None
    error: str | None
    created_at: str | None


@router.post("/run", status_code=202, response_model=RunAccepted)
async def run_backtest_endpoint(
    config: RunConfig, session: AsyncSession = Depends(get_session)
) -> RunAccepted:
    """Validate + queue a backtest; the worker computes it asynchronously (§12)."""
    run_id = str(uuid.uuid4())
    chash = config_hash(config)
    session.add(
        BacktestRun(
            id=run_id,
            config=config.model_dump(mode="json"),
            config_hash=chash,
            seed=config.seed,
            status="queued",
        )
    )
    await session.commit()
    await enqueue("run_backtest_job", run_id)
    return RunAccepted(run_id=run_id, status="queued", config_hash=chash)


@router.post("/preview", response_model=PreviewResult)
async def preview_backtest(config: RunConfig) -> PreviewResult:
    """Run a genome synchronously and return its full report — no queue, no persist.

    This is the on-demand chart path for Discovery and the Trade Deck: given a
    strategy's genome (a ``RunConfig``) it reuses the exact same engine as a queued
    run — same lookahead/cost model (rules #1, #2) — and hands back candles, markers
    and indicator series so the caller can draw the identical chart. CPU-bound, so it
    runs off the event loop.
    """
    try:
        out = await run_in_threadpool(run_backtest, config)
    except NoDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreviewResult(
        config_hash=config_hash(config),
        metrics=out["metrics"],
        report=out["report"],
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    include_report: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    """Fetch a run's status + metrics, and (by default) its full report artifact."""
    run = (
        await session.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id!r}")

    report = read_report(run.artifact_path) if include_report else None
    return RunDetail(
        id=run.id,
        status=run.status,
        config=run.config,
        config_hash=run.config_hash,
        seed=run.seed,
        metrics=run.metrics,
        report=report,
        error=run.error,
        created_at=run.created_at.isoformat() if run.created_at else None,
    )
