"""Tests for timeframe helpers."""

from __future__ import annotations

import pytest

from app.data.timeframes import (
    FUNDING_INTERVAL_MS,
    FUNDING_TF,
    last_closed_open_ts,
    tf_to_ms,
)


def test_tf_to_ms() -> None:
    assert tf_to_ms("1m") == 60_000
    assert tf_to_ms("1h") == 3_600_000
    assert tf_to_ms("1d") == 86_400_000
    assert tf_to_ms(FUNDING_TF) == FUNDING_INTERVAL_MS


def test_tf_to_ms_invalid() -> None:
    with pytest.raises(ValueError):
        tf_to_ms("3m")


def test_last_closed_open_ts_on_boundary() -> None:
    step = tf_to_ms("1h")
    assert last_closed_open_ts(100 * step, "1h") == 99 * step


def test_last_closed_open_ts_mid_bar() -> None:
    step = tf_to_ms("1h")
    # forming bar (open 100*step) is excluded; last closed opens at 99*step
    assert last_closed_open_ts(100 * step + 123, "1h") == 99 * step
