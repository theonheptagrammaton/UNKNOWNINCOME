"""Rebuild the learned slippage model and re-run when reality is worse (doc §26.1).

Two async jobs the worker drives:

* :func:`rebuild_slippage_model` — fold the real (``mode == "live"``) fills in
  ``slippage_observations`` into the bucketed model and materialise it so the next
  backtest reads the *measured* slippage instead of the 5 bps guess.
* :func:`reconcile_slippage` — the painful part (doc §26.1): if a trusted bucket's
  learned slippage is **worse** than the assumption, past backtests under-costed those
  fills, so the leaderboard is stale. We emit a ``risk_event`` per offending bucket,
  notify, and invoke the injected ``rerun`` seam for each affected ``(symbol, tf)`` — the
  worker wires the real re-run + re-rank; tests inject a fake. Re-running on real data is
  an operator step; the *trigger* is code and tested.

Kept honest by rule #13: only live fills teach the model. A paper fill is simulated —
it would just teach the model back its own assumption.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.execution.slippage_model import (
    MIN_SAMPLES_DEFAULT,
    FillObservation,
    LearnedSlippageModel,
    learn,
    materialize,
    worse_than_assumption,
)
from app.models.risk import RiskEvent
from app.models.trading import SlippageObservation

# The assumption past backtests priced fills at (the fixed-bps default, doc §26.1).
ASSUMED_SLIPPAGE_BPS = 5.0


@dataclass
class ReconcileReport:
    """What one reconciliation pass found and did."""

    observations: int
    trusted_buckets: int
    worse_buckets: list[tuple[str, float]] = field(default_factory=list)
    reran: list[str] = field(default_factory=list)  # affected "symbol|tf" keys

    @property
    def rerun_needed(self) -> bool:
        return bool(self.worse_buckets)


async def _load_live_observations(session: AsyncSession) -> list[FillObservation]:
    rows = (
        await session.execute(
            select(SlippageObservation).where(SlippageObservation.mode == "live")
        )
    ).scalars().all()
    return [
        FillObservation(
            symbol=r.symbol, tf=r.tf, side=r.side,
            expected_price=r.expected_price, fill_price=r.fill_price,
            order_notional=r.order_notional, atr=r.atr, ts=r.ts,
        )
        for r in rows
    ]


async def rebuild_slippage_model(
    session: AsyncSession, *, min_samples: int = MIN_SAMPLES_DEFAULT
) -> LearnedSlippageModel:
    """Learn the model from live fills and materialise the sync-readable artifact."""
    observations = await _load_live_observations(session)
    model = learn(observations, min_samples=min_samples)
    materialize(model)
    return model


def _affected_symbol_tf(worse: list[tuple[str, float]]) -> list[str]:
    """The distinct ``symbol|tf`` prefixes of the worse buckets (``symbol|tf|nt|vt``)."""
    seen: dict[str, None] = {}
    for key, _bps in worse:
        parts = key.split("|")
        if len(parts) >= 2:
            seen.setdefault(f"{parts[0]}|{parts[1]}", None)
    return list(seen)


async def reconcile_slippage(
    session: AsyncSession,
    *,
    assumed_bps: float = ASSUMED_SLIPPAGE_BPS,
    tolerance_bps: float = 0.0,
    min_samples: int = MIN_SAMPLES_DEFAULT,
    rerun: Callable[[str, str], Awaitable[None]] | None = None,
    notifier: object | None = None,
) -> ReconcileReport:
    """Rebuild the model; if reality is worse than assumed, flag + re-run (doc §26.1)."""
    model = await rebuild_slippage_model(session, min_samples=min_samples)
    observations = sum(b.samples for b in model.buckets.values())
    worse = worse_than_assumption(model, assumed_bps, tolerance_bps=tolerance_bps)
    report = ReconcileReport(
        observations=observations, trusted_buckets=model.trusted_buckets, worse_buckets=worse
    )
    if not worse:
        return report

    ts = now_ms()
    for key, bps in worse:
        session.add(RiskEvent(
            ts=ts, type="slippage_worse", mode="live",
            detail={
                "bucket": key, "learned_bps": round(bps, 4), "assumed_bps": assumed_bps,
                "note": "learned slippage exceeds the assumption — leaderboard is stale",
            },
        ))
    if notifier is not None:
        await notifier.notify(
            f"⚠️ learned slippage worse than assumed in {len(worse)} bucket(s) — "
            "re-running affected backtests (doc §26.1)"
        )

    for sym_tf in _affected_symbol_tf(worse):
        if rerun is not None:
            symbol, tf = sym_tf.split("|", 1)
            try:
                await rerun(symbol, tf)
                report.reran.append(sym_tf)
            except Exception:  # pragma: no cover - re-run best-effort, logged upstream
                pass
    return report
