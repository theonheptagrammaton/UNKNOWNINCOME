"""Append-only audit log helper (doc §13 point 4).

Every mutation that matters — mode transitions, kill switch, promotions and every
Telegram command — writes one row here. Kept tiny and dependency-light so any layer
(API, bot, Telegram) can record an action without ceremony.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.system import AuditLog


async def write_audit(
    session: AsyncSession, actor: str, action: str, detail: dict | None = None
) -> AuditLog:
    """Append one audit row (caller commits). ``actor`` ∈ ui|api|telegram|system."""
    row = AuditLog(ts=now_ms(), actor=actor, action=action, detail=detail or {})
    session.add(row)
    return row
