"""Risk events — the audit trail of the mandatory risk wall (doc §9.4, §11).

Every time the risk layer blocks, resizes or halts, it writes a row here. These
rows are the evidence behind the decision log's rejected actions (doc §10.2) and
are how the acceptance test proves a limit breach both blocked the order *and*
was recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


# Canonical event types (doc §9.4).
RISK_TYPES = (
    "daily_loss",
    "max_drawdown",
    "killswitch",
    "cooldown",
    "price_guard",
    "max_positions",
    "leverage_cap",
    "liq_buffer",
    "insufficient_equity",
    "reconcile",  # live venue vs local state divergence (doc §9.2, Phase 7)
)


class RiskEvent(Base):
    """One risk-layer action: block, resize, halt or kill (doc §9.4, §11)."""

    __tablename__ = "risk_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)  # ms UTC
    type: Mapped[str] = mapped_column(String(24), index=True)
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strategy_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON)  # human-readable reason + numbers
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
