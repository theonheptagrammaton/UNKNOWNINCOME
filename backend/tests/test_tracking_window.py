"""Before/after tracking-error comparison around the learned-model activation (doc §26.4).

The pure comparison is unit-tested here; the *real* narrowing on live data is an operator
step (needs a live-vs-paper run), exactly like the acceptance criterion states."""

from __future__ import annotations

from app.bot.tracking import compare_tracking_error


def _series(equities: list[float], start_ts: int = 0, step: int = 1) -> list[tuple[int, float]]:
    return [(start_ts + i * step, e) for i, e in enumerate(equities)]


def test_narrowed_true_when_after_window_tracks_tighter() -> None:
    # Before split (ts < 100): live and paper returns diverge every step (wide TE).
    # After split (ts ≥ 100): live and paper move in lockstep (near-zero TE).
    live_before = [100.0, 101.0, 100.0, 101.0, 100.0]
    paper_before = [100.0, 100.5, 100.7, 100.6, 100.8]
    live_after = [100.0, 101.0, 102.0, 103.0, 104.0]
    paper_after = [100.0, 101.0, 102.0, 103.0, 104.0]

    live = _series(live_before, 0, 10) + _series(live_after, 100, 10)
    paper = _series(paper_before, 0, 10) + _series(paper_after, 100, 10)

    cmp = compare_tracking_error(live, paper, split_ts=100)
    assert cmp.before.tracking_error is not None
    assert cmp.after.tracking_error is not None
    assert cmp.after.tracking_error < cmp.before.tracking_error
    assert cmp.narrowed is True


def test_narrowed_none_when_a_window_is_too_short() -> None:
    live = _series([100.0, 101.0], 0, 10)  # everything before the split
    paper = _series([100.0, 100.5], 0, 10)
    cmp = compare_tracking_error(live, paper, split_ts=100)
    assert cmp.after.points < 2
    assert cmp.narrowed is None  # can't compare with an empty after-window


def test_as_dict_shape() -> None:
    live = _series([100.0, 101.0, 102.0], 0, 10) + _series([100.0, 100.5], 100, 10)
    paper = _series([100.0, 100.4, 101.0], 0, 10) + _series([100.0, 100.5], 100, 10)
    d = compare_tracking_error(live, paper, split_ts=100).as_dict()
    assert set(d) == {"split_ts", "before", "after", "narrowed"}
    assert d["split_ts"] == 100
