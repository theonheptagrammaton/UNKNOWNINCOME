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
    # Portfolio-level gate (doc §24.5, Phase 10) — evaluated before strategy limits.
    "portfolio_drawdown",  # portfolio DD ≥ 12% → kill (stricter than strategy 15%)
    "portfolio_daily_loss",  # portfolio daily loss ≥ 3% → halt new entries
    "symbol_exposure",  # net symbol exposure > 35% of equity → reject
    "gross_leverage",  # gross leverage > 3x → reject
    "direction_concentration",  # one side > 60% → restrict same-side entry
    "active_strategies",  # active-strategy band 3–8 breached → warn only
    "correlation_gate",  # new strategy |ρ| > 0.70 vs pool → allocation cut/reject
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
