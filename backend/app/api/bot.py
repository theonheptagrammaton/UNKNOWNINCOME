"""Trade bot API (doc §12): mode, kill switch, portfolio, signals, decision log.

The bot engine runs in the worker; this API is the read/control surface the Trade
Deck uses. Reads come from the shared tables (open trades, equity snapshots,
signals, risk events); control writes settings/flags the engine honours on its next
tick (hot). Every mutation records an ``audit_log`` row via the underlying helpers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import killswitch as ks
from app.bot import mode as mode_mod
from app.core.audit import write_audit
from app.core.db import get_session
from app.core.settings_store import (
    KEY_PROMOTION_GATE,
    KEY_RISK_LIMITS,
    get_setting,
    set_setting,
)
from app.execution.risk import RiskLimits
from app.models.risk import RiskEvent
from app.models.system import AuditLog
from app.models.trading import EquitySnapshot, Signal, Trade

router = APIRouter(prefix="/bot", tags=["bot"])

# Promotion-gate defaults (doc §9.5).
DEFAULT_PROMOTION_GATE = {
    "min_days": 30,
    "min_trades": 30,
    "min_profit_factor": 1.3,
    "max_drawdown_pct": 10.0,
}


class ModeRequest(BaseModel):
    mode: str  # off | paper | live
    scope: str = "global"  # global | strategy
    strategy_id: str | None = None


class KillRequest(BaseModel):
    reason: str = ""


class SettingsRequest(BaseModel):
    risk_limits: dict | None = None
    promotion_gate: dict | None = None


async def _last_equity(session: AsyncSession) -> EquitySnapshot | None:
    return (
        await session.execute(
            select(EquitySnapshot).where(EquitySnapshot.mode == "paper")
            .order_by(EquitySnapshot.ts.desc()).limit(1)
        )
    ).scalar_one_or_none()


@router.get("/status")
async def status(session: AsyncSession = Depends(get_session)) -> dict:
    """Status strip payload (doc §10.2): mode, kill state, equity, daily pnl, positions."""
    global_mode = await mode_mod.get_global_mode(session)
    engaged = await ks.is_engaged_db(session)
    last_eq = await _last_equity(session)
    open_trades = (
        await session.execute(
            select(Trade).where(Trade.mode == "paper", Trade.status == "open")
        )
    ).scalars().all()
    from datetime import UTC, datetime

    midnight_ms = int(
        datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
    )
    day_open = (
        await session.execute(
            select(EquitySnapshot).where(
                EquitySnapshot.mode == "paper", EquitySnapshot.ts >= midnight_ms
            ).order_by(EquitySnapshot.ts.asc()).limit(1)
        )
    ).scalar_one_or_none()
    equity = last_eq.equity if last_eq else None
    daily_pnl = (equity - day_open.equity) if (equity is not None and day_open) else None
    return {
        "global_mode": global_mode,
        "live_enabled": mode_mod.LIVE_ENABLED,
        "killswitch": engaged,
        "equity": equity,
        "exposure": last_eq.exposure if last_eq else 0.0,
        "daily_pnl": daily_pnl,
        "open_positions": len(open_trades),
        "regime": None,  # regime labelling arrives in Phase 6 (doc §8.4)
    }


@router.post("/start")
async def start(session: AsyncSession = Depends(get_session)) -> dict:
    """Switch the global mode to paper (doc §12 POST /bot/start)."""
    previous = await mode_mod.set_global_mode(session, "paper", actor="api")
    await session.commit()
    return {"global_mode": "paper", "previous": previous}


@router.post("/stop")
async def stop(session: AsyncSession = Depends(get_session)) -> dict:
    """Switch the global mode to off (doc §12 POST /bot/stop)."""
    previous = await mode_mod.set_global_mode(session, "off", actor="api")
    await session.commit()
    return {"global_mode": "off", "previous": previous}


@router.post("/mode")
async def set_mode(req: ModeRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Set the global or a per-strategy switch (doc §9.6)."""
    if req.scope == "strategy" and req.strategy_id:
        from app.strategy import service

        try:
            await service.set_mode(session, req.strategy_id, req.mode, actor="api")
        except service.StrategyError as exc:
            from fastapi import HTTPException

            raise HTTPException(400, str(exc)) from exc
        await session.commit()
        return {"scope": "strategy", "strategy_id": req.strategy_id, "mode": req.mode}
    try:
        previous = await mode_mod.set_global_mode(session, req.mode, actor="api")
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(400, str(exc)) from exc
    await session.commit()
    return {"scope": "global", "mode": req.mode, "previous": previous}


@router.post("/killswitch")
async def killswitch(req: KillRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Engage the kill switch (channel 2 of 4, doc §9.4)."""
    await ks.engage(session, actor="api", reason=req.reason)
    await session.commit()
    return {"killswitch": True, "reason": req.reason}


@router.post("/killswitch/clear")
async def killswitch_clear(session: AsyncSession = Depends(get_session)) -> dict:
    """Clear the kill switch so the bot may resume (deliberate action)."""
    await ks.clear(session, actor="api")
    await session.commit()
    return {"killswitch": False}


@router.get("/portfolio")
async def portfolio(session: AsyncSession = Depends(get_session)) -> dict:
    """Open positions, exposure and equity (doc §10.2 portfolio panel)."""
    open_trades = (
        await session.execute(
            select(Trade).where(Trade.mode == "paper", Trade.status == "open")
            .order_by(Trade.entry_ts.desc())
        )
    ).scalars().all()
    last_eq = await _last_equity(session)
    positions = [
        {
            "symbol": t.symbol, "side": t.side, "qty": t.qty, "entry_price": t.entry_price,
            "leverage": t.leverage, "entry_ts": t.entry_ts, "strategy_id": t.strategy_id,
        }
        for t in open_trades
    ]
    return {
        "positions": positions,
        "equity": last_eq.equity if last_eq else None,
        "exposure": last_eq.exposure if last_eq else 0.0,
    }


@router.get("/equity")
async def equity_curve(
    limit: int = Query(500, ge=1, le=5000), session: AsyncSession = Depends(get_session)
) -> dict:
    """Recent equity snapshots for the Trade Deck curve."""
    rows = (
        await session.execute(
            select(EquitySnapshot).where(EquitySnapshot.mode == "paper")
            .order_by(EquitySnapshot.ts.desc()).limit(limit)
        )
    ).scalars().all()
    points = [{"time": r.ts, "value": r.equity, "exposure": r.exposure} for r in reversed(rows)]
    return {"points": points}


@router.get("/signals")
async def signals(
    since: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Signal feed with reason + indicator snapshot (doc §10.2)."""
    rows = (
        await session.execute(
            select(Signal).where(Signal.ts >= since)
            .order_by(Signal.ts.desc()).limit(limit)
        )
    ).scalars().all()
    return {"signals": [_signal_row(s) for s in rows]}


@router.get("/decisions")
async def decisions(
    limit: int = Query(100, ge=1, le=1000), session: AsyncSession = Depends(get_session)
) -> dict:
    """Merged decision log: every signal (with outcome) + every risk event (doc §10.2)."""
    sigs = (
        await session.execute(select(Signal).order_by(Signal.ts.desc()).limit(limit))
    ).scalars().all()
    events = (
        await session.execute(select(RiskEvent).order_by(RiskEvent.ts.desc()).limit(limit))
    ).scalars().all()
    merged: list[dict] = [{"kind": "signal", **_signal_row(s)} for s in sigs]
    merged += [
        {
            "kind": "risk", "ts": e.ts, "type": e.type, "symbol": e.symbol,
            "strategy_version_id": e.strategy_version_id, "detail": e.detail,
        }
        for e in events
    ]
    merged.sort(key=lambda d: d["ts"], reverse=True)
    return {"decisions": merged[:limit]}


@router.get("/risk-events")
async def risk_events(
    limit: int = Query(100, ge=1, le=1000), session: AsyncSession = Depends(get_session)
) -> dict:
    rows = (
        await session.execute(select(RiskEvent).order_by(RiskEvent.ts.desc()).limit(limit))
    ).scalars().all()
    return {"risk_events": [
        {"ts": e.ts, "type": e.type, "symbol": e.symbol, "detail": e.detail} for e in rows
    ]}


@router.get("/audit")
async def audit(
    limit: int = Query(100, ge=1, le=1000), session: AsyncSession = Depends(get_session)
) -> dict:
    rows = (
        await session.execute(select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit))
    ).scalars().all()
    return {"audit": [
        {"ts": a.ts, "actor": a.actor, "action": a.action, "detail": a.detail} for a in rows
    ]}


@router.get("/settings")
async def get_settings(session: AsyncSession = Depends(get_session)) -> dict:
    """Risk limits + promotion gate (doc §10.2 settings panel)."""
    limits = await get_setting(session, KEY_RISK_LIMITS) or RiskLimits().model_dump()
    gate = await get_setting(session, KEY_PROMOTION_GATE) or DEFAULT_PROMOTION_GATE
    return {"risk_limits": limits, "promotion_gate": gate}


@router.post("/settings")
async def update_settings(
    req: SettingsRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Persist risk limits / promotion gate; validated against the RiskLimits schema."""
    if req.risk_limits is not None:
        validated = RiskLimits.model_validate(req.risk_limits).model_dump()
        await set_setting(session, KEY_RISK_LIMITS, validated)
        await write_audit(session, "ui", "settings.risk_limits", validated)
    if req.promotion_gate is not None:
        await set_setting(session, KEY_PROMOTION_GATE, req.promotion_gate)
        await write_audit(session, "ui", "settings.promotion_gate", req.promotion_gate)
    await session.commit()
    return await get_settings(session)


def _signal_row(s: Signal) -> dict:
    return {
        "id": s.id,
        "strategy_id": s.strategy_id,
        "strategy_version_id": s.strategy_version_id,
        "ts": s.ts,
        "symbol": s.symbol,
        "tf": s.tf,
        "action": s.action,
        "reason": s.reason,
        "indicator_snapshot": s.indicator_snapshot,
        "outcome": s.outcome,
        "outcome_detail": s.outcome_detail,
    }
