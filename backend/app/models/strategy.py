"""Strategy genome + immutable versioning + lineage (doc §8.1–8.2, §11).

A ``Strategy`` is a named lineage; every edit — from the UI rule builder, the raw
JSON editor or a Python plugin — writes a **new immutable** ``StrategyVersion``
(there is no silent edit, doc §8.6). The genome is a serialized backtest
``RunConfig`` (config.py is deliberately forward-compatible with the §8.1 genome),
so the paper bot reuses the exact signal path the backtest was validated against.

Hot-reload is a data fact, not a process trick: ``Strategy.active_version_id``
points at the version the bot must run; pointing it at a newer row makes the
change go live on the next tick with no restart. Lineage is preserved via
``parent_version_id`` (which version this one descends from) and ``source`` (which
backtest run or discovery scan it was born from).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


# Per-strategy mode switch (doc §9.6). Effective mode = min(global, strategy),
# ordered Off < Paper < Live. LIVE is selectable but engine-refused until Phase 7.
MODE_ORDER = {"off": 0, "paper": 1, "live": 2}
# Version lifecycle (doc §8.2): candidate → paper → live → retired.
STATUSES = ("candidate", "paper", "live", "retired")


class Strategy(Base):
    """A named strategy lineage + its live mode switch (doc §8.2, §9.6, §11)."""

    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    # Which backtest run or discovery scan this strategy was converted from.
    created_from_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Per-strategy switch; the bot runs a strategy when min(global, this) ≥ paper.
    mode: Mapped[str] = mapped_column(String(8), default="off", index=True)
    # The version the bot must run right now (hot-reload pointer).
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class StrategyVersion(Base):
    """One immutable genome revision + its lineage (doc §8.1, §11)."""

    __tablename__ = "strategy_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)  # 1-based, monotonic per strategy
    genome: Mapped[dict] = mapped_column(JSON)  # RunConfig dump + name
    genome_hash: Mapped[str] = mapped_column(String(16), index=True)
    wfo_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Provenance: {"kind": "run"|"scan", "id": ..., "rank": ...} (doc §8.1 lineage).
    source: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
