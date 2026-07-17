"""Tests for gap detection."""

from __future__ import annotations

from app.data.gaps import count_missing, expected_count, find_gaps
from app.data.timeframes import tf_to_ms


def test_no_gaps() -> None:
    step = tf_to_ms("1h")
    assert find_gaps([i * step for i in range(10)], "1h") == []


def test_single_gap() -> None:
    step = tf_to_ms("1h")
    ts = [0, step, 2 * step, 5 * step, 6 * step]  # 3,4 missing
    gaps = find_gaps(ts, "1h")
    assert gaps == [(3 * step, 4 * step)]
    assert count_missing(gaps, "1h") == 2


def test_multiple_gaps() -> None:
    step = tf_to_ms("1h")
    ts = [0, step, 4 * step, 5 * step, 9 * step]  # 2,3 and 6,7,8 missing
    gaps = find_gaps(ts, "1h")
    assert gaps == [(2 * step, 3 * step), (6 * step, 8 * step)]
    assert count_missing(gaps, "1h") == 5


def test_expected_count() -> None:
    step = tf_to_ms("1h")
    assert expected_count(0, 9 * step, "1h") == 10
    assert expected_count(5, 4, "1h") == 0
