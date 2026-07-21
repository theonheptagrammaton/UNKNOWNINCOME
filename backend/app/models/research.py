"""The experiment ledger — every hypothesis ever tried (doc §23.2).

Append-only and **scan-transcending**: one row per tried hypothesis, keyed by a
canonical ``genome_hash`` so the same idea is never counted twice *within* a scan
but every re-optimization *across* scans adds to the family's all-time trial count.
That count is what the Deflated Sharpe Ratio reads: re-running the same strategy for
weeks grows ``trials_total`` and lowers its deflated score — trying one idea fifty
times pays the same statistical price as fifty different ideas (§23.2).

Nothing is ever updated or deleted; the ledger is the audit trail of the search.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


class ExperimentTrial(Base):
    """One tried hypothesis (doc §23.2). Append-only; never mutated."""

    __tablename__ = "experiment_trials"
    __table_args__ = (
        # The hot read is "all-time trial count for this genome family".
        Index("ix_experiment_trials_family", "genome_hash"),
    )

    trial_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(String(36), index=True)
    genome_hash: Mapped[str] = mapped_column(String(16))  # canonical family hash
    symbol: Mapped[str] = mapped_column(String(32))
    tf: Mapped[str] = mapped_column(String(8))
    period: Mapped[dict] = mapped_column(JSON)  # {"start_ts": .., "end_ts": ..}
    is_metrics: Mapped[dict] = mapped_column(JSON)  # raw in-sample metrics
    oos_metrics: Mapped[dict] = mapped_column(JSON)  # raw out-of-sample metrics
    stage: Mapped[str] = mapped_column(String(32))  # where it was tried / eliminated
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow  # UTC (rule #5)
    )
