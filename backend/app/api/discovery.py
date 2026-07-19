"""Discovery API (doc §12): queue a scan, poll its progress, read the leaderboard."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.queue import enqueue
from app.discovery.config import ScanConfig, apply_fast_mode, config_hash
from app.discovery.store import read_leaderboard
from app.models.discovery import DiscoveryScan

router = APIRouter(prefix="/discovery", tags=["discovery"])


class ScanAccepted(BaseModel):
    scan_id: str
    status: str
    config_hash: str


class ScanDetail(BaseModel):
    id: str
    status: str
    stage: str | None
    progress: float
    combos_tried: int
    config: dict
    config_hash: str
    seed: int
    leaderboard: dict | None  # compact summary
    detail: dict | None  # full artifact (opt-in)
    error: str | None
    created_at: str | None


@router.post("/scan", status_code=202, response_model=ScanAccepted)
async def create_scan(
    config: ScanConfig, session: AsyncSession = Depends(get_session)
) -> ScanAccepted:
    """Validate + queue a discovery scan; the worker runs it asynchronously (§7, §12)."""
    # ``config_hash`` is taken over the resolved (fast-mode-applied) config so the
    # stored hash matches what actually runs (rule #6).
    resolved = apply_fast_mode(config)
    scan_id = str(uuid.uuid4())
    chash = config_hash(resolved)
    session.add(
        DiscoveryScan(
            id=scan_id,
            config=config.model_dump(mode="json"),
            config_hash=chash,
            seed=config.seed,
            status="queued",
            stage=None,
            progress=0.0,
            combos_tried=0,
        )
    )
    await session.commit()
    await enqueue("run_discovery_job", scan_id)
    return ScanAccepted(scan_id=scan_id, status="queued", config_hash=chash)


@router.get("/scans/{scan_id}", response_model=ScanDetail)
async def get_scan(
    scan_id: str,
    include_detail: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> ScanDetail:
    """Fetch a scan's live progress + compact leaderboard (+ full artifact on demand)."""
    scan = (
        await session.execute(select(DiscoveryScan).where(DiscoveryScan.id == scan_id))
    ).scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail=f"unknown scan: {scan_id!r}")

    detail = read_leaderboard(scan.artifact_path) if include_detail else None
    return ScanDetail(
        id=scan.id,
        status=scan.status,
        stage=scan.stage,
        progress=scan.progress,
        combos_tried=scan.combos_tried,
        config=scan.config,
        config_hash=scan.config_hash,
        seed=scan.seed,
        leaderboard=scan.leaderboard,
        detail=detail,
        error=scan.error,
        created_at=scan.created_at.isoformat() if scan.created_at else None,
    )


@router.get("/leaderboard")
async def leaderboard(
    scan_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="oos_score"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Aggregate finalist rows across completed scans (or one), ranked by ``sort_by``."""
    stmt = select(DiscoveryScan).where(DiscoveryScan.status == "done")
    if scan_id is not None:
        stmt = stmt.where(DiscoveryScan.id == scan_id)
    stmt = stmt.order_by(DiscoveryScan.created_at.desc())
    scans = (await session.execute(stmt)).scalars().all()

    rows: list[dict] = []
    for s in scans:
        summary = s.leaderboard or {}
        for r in summary.get("rows", []):
            rows.append({**r, "scan_id": s.id})

    def _key(r: dict):
        v = r.get(sort_by)
        numeric = v if isinstance(v, int | float) else None
        return (numeric is None, -(numeric or 0.0))

    rows.sort(key=_key)
    return {"count": len(rows[:limit]), "sort_by": sort_by, "rows": rows[:limit]}
