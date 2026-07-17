"""Gap detection over bar-open-time series (doc §4.4).

A *gap* is a run of missing interior bars. Bars missing after the last stored
bar are 'not yet fetched', not gaps.
"""

from __future__ import annotations

from app.data.timeframes import tf_to_ms


def find_gaps(present_ts: list[int], tf: str) -> list[tuple[int, int]]:
    """Return ``(first_missing_open, last_missing_open)`` ranges within the series."""
    if len(present_ts) < 2:
        return []
    step = tf_to_ms(tf)
    present = sorted({int(t) for t in present_ts})
    gaps: list[tuple[int, int]] = []
    for a, b in zip(present, present[1:], strict=False):
        if b - a > step:
            gaps.append((a + step, b - step))
    return gaps


def count_missing(gaps: list[tuple[int, int]], tf: str) -> int:
    """Total number of missing bars across all gaps."""
    step = tf_to_ms(tf)
    return sum((end - start) // step + 1 for start, end in gaps)


def expected_count(first_ts: int, last_ts: int, tf: str) -> int:
    """Number of bars an unbroken series would have over ``[first_ts, last_ts]``."""
    if last_ts < first_ts:
        return 0
    return (last_ts - first_ts) // tf_to_ms(tf) + 1
