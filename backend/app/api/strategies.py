"""Strategies API (doc §12): convert, list, version, diff, promote/pause/retire.

Every mutating call goes through :mod:`app.strategy.service`, so each edit produces a
new immutable version and repoints the active pointer (hot-reload). "Convert to
strategy" accepts either a backtest run or a discovery leaderboard entry.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.data.duckdb_query import query_ohlcv
from app.execution.capacity import capacity_from_samples
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import EquitySnapshot, Trade
from app.strategy import service
from app.strategy.genome import GenomeError, diff_genomes, genome_config
from app.strategy.plugin_loader import load_plugins
from app.strategy.plugin_registry import get_plugin_registry

router = APIRouter(prefix="/strategies", tags=["strategies"])


class FromRunRequest(BaseModel):
    run_id: str | None = None
    scan_id: str | None = None
    rank: int | None = None
    name: str | None = None


class NewVersionRequest(BaseModel):
    genome: dict  # {"name", "config"}
    wfo_report: dict | None = None


class ModeRequest(BaseModel):
    mode: str  # off | paper | live


class StrategyOut(BaseModel):
    id: str
    name: str
    mode: str
    active_version_id: str | None
    active_version: int | None
    status: str | None
    regime: str | None
    created_from_run_id: str | None
    created_at: str | None
    health: dict
    capacity_usd: float | None = None  # "carries up to $X" (doc §26.2)


class VersionOut(BaseModel):
    id: str
    strategy_id: str
    version: int
    genome: dict
    genome_hash: str
    status: str
    regime: str | None
    parent_version_id: str | None
    source: dict | None
    wfo_report: dict | None
    created_at: str | None


class PendingOut(BaseModel):
    """A self-generated version awaiting human approval (doc §8.5)."""

    version: VersionOut
    strategy_id: str
    strategy_name: str
    active_version: int | None
    diff: dict  # active genome → proposed genome


async def _health(session: AsyncSession, strategy_id: str) -> dict:
    """Rolling health for a strategy card (doc §10.2): trade count, PF, last pnl."""
    rows = (
        await session.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id, Trade.mode == "paper", Trade.status == "closed"
            ).order_by(Trade.exit_ts.desc()).limit(30)
        )
    ).scalars().all()
    pnls = [t.pnl for t in rows if t.pnl is not None]
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    pf = (gains / losses) if losses > 0 else (None if gains == 0 else float("inf"))
    open_count = (
        await session.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id, Trade.mode == "paper", Trade.status == "open"
            )
        )
    ).scalars().all()
    return {
        "num_trades": len(pnls),
        "rolling_pf": None if pf is None or pf == float("inf") else round(pf, 3),
        "last_pnl": pnls[0] if pnls else None,
        "open_positions": len(open_count),
    }


async def _capacity(
    session: AsyncSession, strategy_id: str, version: StrategyVersion | None
) -> float | None:
    """"Carries up to $X" (doc §26.2): equity × 1% / median order participation.

    Best-effort — the strategy's recent fills give ``(order_qty, bar_volume)`` pairs
    (bar volume read from OHLCV at each entry bar); the median participation projects how
    much capital the strategy could carry before an order would breach the 1% cap. Returns
    ``None`` until there are real fills with real volume (an operator step, like the other
    real-data numbers in this phase). Never raises — the card degrades to no estimate.
    """
    if version is None:
        return None
    try:
        config = genome_config(version.genome)
    except Exception:
        return None
    last_eq = (
        await session.execute(
            select(EquitySnapshot).where(EquitySnapshot.mode == "paper")
            .order_by(EquitySnapshot.ts.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if last_eq is None or last_eq.equity <= 0:
        return None
    trades = (
        await session.execute(
            select(Trade).where(Trade.strategy_id == strategy_id, Trade.mode == "paper")
            .order_by(Trade.entry_ts.desc()).limit(20)
        )
    ).scalars().all()
    if not trades:
        return None
    try:
        ohlcv = query_ohlcv(config.market, config.symbol, config.tf)
        vol_by_ts = dict(zip(ohlcv["ts"].tolist(), ohlcv["volume"].tolist(), strict=False))
    except Exception:
        return None
    samples = [
        (t.qty, vol_by_ts[t.entry_ts])
        for t in trades
        if t.symbol == config.symbol and t.entry_ts in vol_by_ts
    ]
    if not samples:
        return None
    return capacity_from_samples(last_eq.equity, samples)


async def _strategy_out(session: AsyncSession, strat: Strategy) -> StrategyOut:
    version = (
        await session.get(StrategyVersion, strat.active_version_id)
        if strat.active_version_id else None
    )
    return StrategyOut(
        id=strat.id,
        name=strat.name,
        mode=strat.mode,
        active_version_id=strat.active_version_id,
        active_version=version.version if version else None,
        status=version.status if version else None,
        regime=version.regime if version else None,
        created_from_run_id=strat.created_from_run_id,
        created_at=strat.created_at.isoformat() if strat.created_at else None,
        health=await _health(session, strat.id),
        capacity_usd=await _capacity(session, strat.id, version),
    )


def _version_out(v: StrategyVersion) -> VersionOut:
    return VersionOut(
        id=v.id, strategy_id=v.strategy_id, version=v.version, genome=v.genome,
        genome_hash=v.genome_hash, status=v.status, regime=v.regime,
        parent_version_id=v.parent_version_id,
        source=v.source, wfo_report=v.wfo_report,
        created_at=v.created_at.isoformat() if v.created_at else None,
    )


@router.post("/from-run", status_code=201, response_model=StrategyOut)
async def convert_to_strategy(
    req: FromRunRequest, session: AsyncSession = Depends(get_session)
) -> StrategyOut:
    """Convert a backtest run or a discovery leaderboard entry into a candidate (§10.1)."""
    try:
        if req.run_id:
            strat, _ = await service.create_from_backtest_run(session, req.run_id, req.name)
        elif req.scan_id and req.rank is not None:
            strat, _ = await service.create_from_scan_entry(
                session, req.scan_id, req.rank, req.name
            )
        else:
            raise HTTPException(422, "provide run_id, or scan_id + rank")
    except service.StrategyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except GenomeError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    return await _strategy_out(session, strat)


@router.get("", response_model=list[StrategyOut])
async def list_strategies(session: AsyncSession = Depends(get_session)) -> list[StrategyOut]:
    strategies = (
        await session.execute(select(Strategy).order_by(Strategy.created_at.desc()))
    ).scalars().all()
    return [await _strategy_out(session, s) for s in strategies]


@router.get("/pending", response_model=list[PendingOut])
async def list_pending(session: AsyncSession = Depends(get_session)) -> list[PendingOut]:
    """Self-generated versions awaiting approval, with a diff vs the active one (§8.5)."""
    pending = await service.pending_versions(session)
    out: list[PendingOut] = []
    for v in pending:
        strat = await session.get(Strategy, v.strategy_id)
        active = (
            await session.get(StrategyVersion, strat.active_version_id)
            if strat and strat.active_version_id else None
        )
        diff = diff_genomes(active.genome, v.genome) if active else {}
        out.append(PendingOut(
            version=_version_out(v),
            strategy_id=v.strategy_id,
            strategy_name=strat.name if strat else "—",
            active_version=active.version if active else None,
            diff=diff,
        ))
    return out


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get_strategy(
    strategy_id: str, session: AsyncSession = Depends(get_session)
) -> StrategyOut:
    strat = await session.get(Strategy, strategy_id)
    if strat is None:
        raise HTTPException(404, f"unknown strategy: {strategy_id!r}")
    return await _strategy_out(session, strat)


@router.get("/{strategy_id}/versions", response_model=list[VersionOut])
async def list_versions(
    strategy_id: str, session: AsyncSession = Depends(get_session)
) -> list[VersionOut]:
    rows = (
        await session.execute(
            select(StrategyVersion).where(StrategyVersion.strategy_id == strategy_id)
            .order_by(StrategyVersion.version.desc())
        )
    ).scalars().all()
    return [_version_out(v) for v in rows]


@router.post("/{strategy_id}/versions", status_code=201, response_model=VersionOut)
async def add_version(
    strategy_id: str, req: NewVersionRequest, session: AsyncSession = Depends(get_session)
) -> VersionOut:
    """Save a new immutable version from the UI builder or the raw JSON editor (§8.6)."""
    try:
        version = await service.add_version(
            session, strategy_id, req.genome, wfo_report=req.wfo_report, actor="ui"
        )
    except service.StrategyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except GenomeError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    return _version_out(version)


@router.get("/{strategy_id}/diff")
async def diff(
    strategy_id: str,
    a: str = Query(...),
    b: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Flat path→{from,to} diff between two versions of the strategy (doc §8.1)."""
    va, vb = await session.get(StrategyVersion, a), await session.get(StrategyVersion, b)
    if va is None or vb is None or va.strategy_id != strategy_id or vb.strategy_id != strategy_id:
        raise HTTPException(404, "both versions must belong to this strategy")
    return {"a": va.version, "b": vb.version, "changes": diff_genomes(va.genome, vb.genome)}


@router.post("/{strategy_id}/mode", response_model=StrategyOut)
async def set_mode(
    strategy_id: str, req: ModeRequest, session: AsyncSession = Depends(get_session)
) -> StrategyOut:
    try:
        strat = await service.set_mode(session, strategy_id, req.mode, actor="ui")
    except service.StrategyError as exc:
        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return await _strategy_out(session, strat)


@router.post("/{strategy_id}/promote", response_model=StrategyOut)
async def promote(
    strategy_id: str, session: AsyncSession = Depends(get_session)
) -> StrategyOut:
    try:
        await service.promote(session, strategy_id, actor="ui")
    except service.StrategyError as exc:
        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return await _strategy_out(session, await session.get(Strategy, strategy_id))


@router.post("/{strategy_id}/pause", response_model=StrategyOut)
async def pause(strategy_id: str, session: AsyncSession = Depends(get_session)) -> StrategyOut:
    try:
        strat = await service.set_mode(session, strategy_id, "off", actor="ui")
    except service.StrategyError as exc:
        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return await _strategy_out(session, strat)


@router.post("/{strategy_id}/retire", response_model=StrategyOut)
async def retire(strategy_id: str, session: AsyncSession = Depends(get_session)) -> StrategyOut:
    try:
        await service.set_status(session, strategy_id, "retired", actor="ui")
    except service.StrategyError as exc:
        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return await _strategy_out(session, await session.get(Strategy, strategy_id))


@router.post("/{strategy_id}/versions/{version_id}/approve", response_model=StrategyOut)
async def approve(
    strategy_id: str, version_id: str, session: AsyncSession = Depends(get_session)
) -> StrategyOut:
    """Approve a pending self-generated version → it runs in paper (doc §8.5 terfi kapısı)."""
    try:
        await service.approve_version(session, strategy_id, version_id, actor="ui")
    except service.StrategyError as exc:
        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return await _strategy_out(session, await session.get(Strategy, strategy_id))


@router.post("/{strategy_id}/versions/{version_id}/reject", response_model=VersionOut)
async def reject(
    strategy_id: str, version_id: str, session: AsyncSession = Depends(get_session)
) -> VersionOut:
    """Reject a pending version (retire it); the strategy stays paused (doc §8.5)."""
    try:
        version = await service.reject_version(session, strategy_id, version_id, actor="ui")
    except service.StrategyError as exc:
        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return _version_out(version)


class ReoptRequest(BaseModel):
    trials: int | None = None  # Optuna budget override (small for a quick manual run)


@router.post("/{strategy_id}/reoptimize")
async def reoptimize(
    strategy_id: str, req: ReoptRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Manually trigger a WFO re-optimization → a pending-approval version (doc §8.3)."""
    from app.bot.notifier import default_notifier
    from app.strategy import regen

    try:
        version = await regen.regenerate(
            session, strategy_id, reason="manual", trials=req.trials,
            notifier=default_notifier(), actor="ui",
        )
    except service.StrategyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except KeyError as exc:  # unknown generator kind
        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return {
        "produced": version is not None,
        "version": _version_out(version).model_dump() if version else None,
    }


@router.post("/reload-plugins")
async def reload_plugins() -> dict:
    """Re-scan ``strategy/plugins/`` so new decision types load without a restart (§8.6)."""
    loaded = load_plugins()
    return {"loaded": loaded, "primitives": get_plugin_registry().names()}
