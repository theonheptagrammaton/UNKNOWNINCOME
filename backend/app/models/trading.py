"""Signals, orders, trades and equity snapshots (doc §9, §11).

Paper and live share these tables — only the ``mode`` column differs — so comparing
paper against live comes for free (doc §9.1). Every ``Signal`` row carries a
``reason`` (the rules that fired) and an ``indicator_snapshot`` (the indicator
values at that bar); this is pazarlıksız — a signal without its justification is a
bug (doc §2, §10.2). The signal's ``outcome`` records the bot's decision (filled /
rejected by the risk wall / skipped), making the row a first-class decision-log
entry alongside ``risk_events``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


class Signal(Base):
    """One rule firing + its full justification + the bot's decision (doc §10.2)."""

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_version_id: Mapped[str] = mapped_column(String(36), index=True)
    strategy_id: Mapped[str] = mapped_column(String(36), index=True)
    ts: Mapped[int] = mapped_column(BigInteger)  # bar close, ms UTC
    symbol: Mapped[str] = mapped_column(String(32))
    tf: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(8), index=True)  # paper | live
    # "open_long" | "open_short" | "close_long" | "close_short".
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[dict] = mapped_column(JSON)  # fired clauses (never empty)
    indicator_snapshot: Mapped[dict] = mapped_column(JSON)  # operand → value at bar
    # Decision outcome: "filled" | "rejected" | "skipped".
    outcome: Mapped[str] = mapped_column(String(16), default="filled", index=True)
    outcome_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Order(Base):
    """One order sent to an execution adapter (doc §9.3, §11)."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mode: Mapped[str] = mapped_column(String(8), index=True)  # paper | live
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    strategy_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4))  # buy | sell
    reduce_only: Mapped[bool] = mapped_column(default=False)
    qty: Mapped[float] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(8), default="market")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # fill price
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    # filled | rejected | cancelled | pending
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Trade(Base):
    """One round-trip position, paper or live (doc §11)."""

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mode: Mapped[str] = mapped_column(String(8), index=True)  # paper | live
    strategy_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    strategy_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(5))  # long | short
    qty: Mapped[float] = mapped_column(Float)
    leverage: Mapped[float] = mapped_column(Float, default=1.0)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_ts: Mapped[int] = mapped_column(BigInteger)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0.0)  # commission + slippage cost
    funding: Mapped[float] = mapped_column(Float, default=0.0)  # signed
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)  # net realized
    status: Mapped[str] = mapped_column(String(8), default="open", index=True)  # open|closed
    # When several strategies net into one exchange position (doc §24.4), the netted
    # PnL is attributed proportionally here: {strategy_id: pnl_share}. None for a
    # position held by a single strategy (its own row already carries the full pnl).
    attribution: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class EquitySnapshot(Base):
    """Point-in-time equity + exposure for the equity curve (doc §11)."""

    __tablename__ = "equity_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)  # ms UTC
    mode: Mapped[str] = mapped_column(String(8), index=True)
    equity: Mapped[float] = mapped_column(Float)
    exposure: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
