"""Discovery scan bookkeeping (doc §7, §11).

A scan drives the full Aşama 0–6 pipeline. PostgreSQL keeps the config, its
reproducible hash, live progress (stage + fraction + combos tried) and a compact
leaderboard summary; the heavy per-entry detail (genomes, WFO layers, Monte-Carlo
bands, engine-disagreement alarms) lives on disk as an artifact.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DiscoveryScan(Base):
    """One discovery request + its live progress and outcome (doc §7, §11)."""

    __tablename__ = "discovery_scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    config: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(16), index=True)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # queued → running → done | failed
    stage: Mapped[str | None] = mapped_column(String(48), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 … 1.0
    combos_tried: Mapped[int] = mapped_column(Integer, default=0)
    leaderboard: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # summary
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
