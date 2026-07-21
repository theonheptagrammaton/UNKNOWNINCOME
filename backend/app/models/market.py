"""Market-data application-state tables (doc §11).

Market data itself lives in Parquet; PostgreSQL holds only this metadata.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Symbol(Base):
    """A tradable instrument on a market."""

    __tablename__ = "symbols"
    __table_args__ = (UniqueConstraint("market", "symbol", name="uq_symbol_market_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)  # normalized, e.g. BTCUSDT
    ccxt_symbol: Mapped[str] = mapped_column(String(64))  # e.g. BTC/USDT:USDT
    base: Mapped[str] = mapped_column(String(32))
    quote: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CandleSyncState(Base):
    """Per symbol × timeframe sync bookkeeping (first/last bar + residual gaps)."""

    __tablename__ = "candle_sync_state"
    __table_args__ = (
        UniqueConstraint("market", "symbol", "tf", name="uq_sync_market_symbol_tf"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    tf: Mapped[str] = mapped_column(String(8), index=True)
    first_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Residual unfilled gaps as [[start_open_ms, end_open_ms], ...] (UTC ms).
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Liquidation(Base):
    """A single forced-liquidation order from Binance ``!forceOrder@arr`` (Faz 8).

    This stream **cannot be backfilled** — Binance only pushes it live — so the
    Phase-8 note has us collecting it now even though nothing reads it until Faz 11.
    ``dedup_key`` is UNIQUE so a websocket reconnect that replays recent events
    never double-writes (the collector inserts with ON CONFLICT DO NOTHING).
    """

    __tablename__ = "liquidations"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_liquidation_dedup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    # Side of the *liquidation order* the venue submits: SELL = a long got liquidated.
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    orig_qty: Mapped[float] = mapped_column(Float)  # base units
    filled_qty: Mapped[float] = mapped_column(Float)  # accumulated filled, base units
    quote_qty: Mapped[float] = mapped_column(Float)  # ≈ avg_price × filled_qty (USDT)
    order_status: Mapped[str] = mapped_column(String(16))
    event_time: Mapped[int] = mapped_column(BigInteger, index=True)  # E, UTC ms
    trade_time: Mapped[int] = mapped_column(BigInteger)  # T, UTC ms
    dedup_key: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UniverseSnapshot(Base):
    """Dated snapshot of the dynamic universe — survivorship-bias guard (doc §4.5)."""

    __tablename__ = "universe_snapshots"
    __table_args__ = (UniqueConstraint("market", "as_of_date", name="uq_universe_market_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String(32), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    # Ordered list of normalized symbols (highest rank first).
    symbols: Mapped[list] = mapped_column(JSON)
    # Filter thresholds + per-symbol metrics used for the selection.
    criteria: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
