"""Key-value settings + the audit log (doc §11, §13).

``settings`` holds application state that is neither market data nor a strategy:
the global mode switch, risk limits, promotion-gate thresholds, the kill-switch
flag and (later, encrypted) API keys. ``audit_log`` records every mutation —
mode transitions, kill switch, promotions and every Telegram command — so the
system is fully accountable (doc §13 point 4).
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


class Setting(Base):
    """One application-state key (doc §11). Sensitive values are stored encrypted."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AuditLog(Base):
    """One accountable action (doc §13 point 4)."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)  # ms UTC
    actor: Mapped[str] = mapped_column(String(24))  # ui | api | telegram | system
    action: Mapped[str] = mapped_column(String(48))
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
