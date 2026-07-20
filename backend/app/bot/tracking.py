"""Live-vs-paper tracking error (doc §15/Faz-7: canlı-paper sapma izleme).

A live strategy and its paper twin trade the *same genome* on the *same signals*, so
their **returns** should track closely; a widening gap means live execution (slippage,
latency, partial fills, funding timing) is diverging from the simulation and is an
early warning worth surfacing. We compare returns, not equity levels, because the two
run different capital — returns normalise that away.

The metric is the standard **tracking error**: the standard deviation of the per-tick
return difference (live − paper), plus the cumulative return gap and the correlation.
The math is a pure function over two equity series so it is unit-testable; the async
loader just pulls the snapshots and hands them in.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import EquitySnapshot


@dataclass
class TrackingError:
    """Live-vs-paper divergence over the aligned window (all fractions, not %)."""

    points: int
    tracking_error: float | None  # stdev of per-tick return diff
    cum_return_live: float | None
    cum_return_paper: float | None
    cum_gap: float | None  # live − paper cumulative return
    correlation: float | None

    def as_dict(self) -> dict:
        return {
            "points": self.points,
            "tracking_error": self.tracking_error,
            "cum_return_live": self.cum_return_live,
            "cum_return_paper": self.cum_return_paper,
            "cum_gap": self.cum_gap,
            "correlation": self.correlation,
        }


def _returns(equities: list[float]) -> list[float]:
    out: list[float] = []
    for prev, cur in zip(equities, equities[1:], strict=False):
        out.append((cur / prev - 1.0) if prev else 0.0)
    return out


def _std(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return var**0.5


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=False))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return cov / (va**0.5 * vb**0.5)


def compute_tracking_error(
    live: list[tuple[int, float]], paper: list[tuple[int, float]]
) -> TrackingError:
    """Align two (ts, equity) series on shared timestamps and score the divergence."""
    live_map = dict(live)
    paper_map = dict(paper)
    shared = sorted(set(live_map) & set(paper_map))
    if len(shared) < 2:
        return TrackingError(len(shared), None, None, None, None, None)

    le = [live_map[t] for t in shared]
    pe = [paper_map[t] for t in shared]
    lr, pr = _returns(le), _returns(pe)
    diff = [x - y for x, y in zip(lr, pr, strict=False)]

    cum_live = (le[-1] / le[0] - 1.0) if le[0] else None
    cum_paper = (pe[-1] / pe[0] - 1.0) if pe[0] else None
    gap = (cum_live - cum_paper) if (cum_live is not None and cum_paper is not None) else None
    return TrackingError(
        points=len(shared),
        tracking_error=_std(diff),
        cum_return_live=cum_live,
        cum_return_paper=cum_paper,
        cum_gap=gap,
        correlation=_corr(lr, pr),
    )


async def _series(session: AsyncSession, mode: str, limit: int) -> list[tuple[int, float]]:
    rows = (
        await session.execute(
            select(EquitySnapshot)
            .where(EquitySnapshot.mode == mode)
            .order_by(EquitySnapshot.ts.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [(r.ts, r.equity) for r in reversed(rows)]


async def load_tracking_error(session: AsyncSession, limit: int = 1000) -> TrackingError:
    """Compute the live-vs-paper tracking error from persisted equity snapshots."""
    live = await _series(session, "live", limit)
    paper = await _series(session, "paper", limit)
    return compute_tracking_error(live, paper)
