"""Live-vs-paper tracking error (doc §15/Faz-7 canlı-paper sapma izleme)."""

from __future__ import annotations

from app.bot.tracking import compute_tracking_error, load_tracking_error
from app.models.trading import EquitySnapshot


def test_identical_returns_have_zero_tracking_error() -> None:
    # Same *returns* on different capital → the series track perfectly.
    live = [(1, 1000.0), (2, 1010.0), (3, 1005.0), (4, 1020.0)]
    paper = [(1, 100.0), (2, 101.0), (3, 100.5), (4, 102.0)]  # ×10 return-equivalent
    te = compute_tracking_error(live, paper)
    assert te.points == 4
    assert te.tracking_error is not None and te.tracking_error < 1e-9
    assert te.correlation is not None and abs(te.correlation - 1.0) < 1e-9
    assert abs(te.cum_gap) < 1e-9


def test_divergent_returns_have_positive_tracking_error() -> None:
    live = [(1, 1000.0), (2, 1030.0), (3, 990.0), (4, 1040.0)]
    paper = [(1, 1000.0), (2, 1005.0), (3, 1006.0), (4, 1007.0)]
    te = compute_tracking_error(live, paper)
    assert te.tracking_error is not None and te.tracking_error > 0.0
    assert te.cum_gap is not None  # live diverged from paper


def test_only_shared_timestamps_are_compared() -> None:
    live = [(1, 1000.0), (2, 1010.0), (5, 1015.0)]
    paper = [(2, 500.0), (3, 505.0), (5, 508.0)]
    te = compute_tracking_error(live, paper)
    assert te.points == 2  # ts 2 and 5 only


def test_insufficient_overlap_returns_none() -> None:
    te = compute_tracking_error([(1, 1000.0)], [(9, 100.0)])
    assert te.points == 0
    assert te.tracking_error is None


async def test_load_tracking_error_from_snapshots(db_session) -> None:
    for ts, eq in [(1, 100.0), (2, 101.0), (3, 102.0)]:
        db_session.add(EquitySnapshot(ts=ts, mode="paper", equity=eq, exposure=0.0))
        db_session.add(EquitySnapshot(ts=ts, mode="live", equity=eq * 5, exposure=0.0))
    await db_session.commit()
    te = await load_tracking_error(db_session)
    assert te.points == 3
    assert te.tracking_error is not None and te.tracking_error < 1e-9
