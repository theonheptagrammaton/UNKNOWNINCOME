"""Persisted indicator registry (doc §5.3).

The in-code registry (``app.indicators.registry``) is the source of truth; this
table is its queryable mirror so the API and discovery pipeline can read
indicator metadata straight from PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IndicatorDefinition(Base):
    """One registry entry — mirrors :class:`app.indicators.registry.IndicatorDef`."""

    __tablename__ = "indicator_defs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    inputs: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[list] = mapped_column(JSON, default=list)
    signal_templates: Mapped[list] = mapped_column(JSON, default=list)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
