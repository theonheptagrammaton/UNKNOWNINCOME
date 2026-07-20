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


def test_sub_interval_jitter_is_not_a_gap() -> None:
    # Binance funding stamps drift a few ms off the 8h grid; contiguous data with
    # ±16 ms jitter must report zero gaps (regression for the funding false-positive).
    step = tf_to_ms("funding")
    jitter = [0, 7, -14, 16, 3, -9, 11, -2, 5, -16]
    ts = [i * step + jitter[i % len(jitter)] for i in range(60)]
    gaps = find_gaps(ts, "funding")
    assert gaps == []
    assert count_missing(gaps, "funding") == 0


def test_real_gap_survives_jitter() -> None:
    # A genuinely missing interior bar is still detected even with stamp jitter.
    step = tf_to_ms("funding")
    ts = [0, step + 5, 2 * step - 8, 4 * step + 11]  # bar 3 (≈3*step) missing
    gaps = find_gaps(ts, "funding")
    assert len(gaps) == 1
    assert count_missing(gaps, "funding") == 1
