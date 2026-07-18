"""Signal primitives (§5.4): correctness + the lookahead-safety guarantee."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators.signals import (
    band_touch,
    line_cross,
    pattern,
    regime,
    slope,
    threshold_cross,
)


def test_threshold_cross_up_and_down() -> None:
    x = pd.Series([10.0, 20, 30, 25, 40, 15, 50])
    up = threshold_cross(x, 25, "up")
    assert up.tolist() == [False, False, True, False, True, False, True]
    down = threshold_cross(x, 25, "down")
    assert down.tolist() == [False, False, False, False, False, True, False]


def test_line_cross() -> None:
    a = pd.Series([1.0, 2, 3, 2, 1])
    b = pd.Series([2.0, 2, 2, 2, 2])
    assert line_cross(a, b, "up").tolist() == [False, False, True, False, False]
    assert line_cross(a, b, "down").tolist() == [False, False, False, False, True]


def test_slope_directions() -> None:
    x = pd.Series([1.0, 2, 3, 3, 1])
    assert slope(x, 1, "up").tolist() == [False, True, True, False, False]
    assert slope(x, 1, "down").tolist() == [False, False, False, False, True]
    assert slope(x, 1, "flat").tolist() == [False, False, False, True, False]


def test_band_touch_modes() -> None:
    price = pd.Series([5.0, 11, 9, 1, 6])
    upper = pd.Series([10.0, 10, 10, 10, 10])
    lower = pd.Series([2.0, 2, 2, 2, 2])
    assert band_touch(price, upper, lower, "touch_upper").tolist() == [
        False, True, False, False, False,
    ]
    assert band_touch(price, upper, lower, "touch_lower").tolist() == [
        False, False, False, True, False,
    ]
    # price re-enters the band from above at index 2 (11 → 9)
    assert band_touch(price, upper, lower, "revert_upper").tolist() == [
        False, False, True, False, False,
    ]


def test_regime_rules() -> None:
    x = pd.Series([10.0, 25, 30, 20])
    assert regime(x, "gt:25").tolist() == [False, False, True, False]
    assert regime(x, "ge:25").tolist() == [False, True, True, False]
    assert regime(x, "between:20:30").tolist() == [False, True, True, True]
    with pytest.raises(ValueError):
        regime(x, "bogus:1")


def test_pattern_directions() -> None:
    s = pd.Series([0, 100, -100, 0])
    assert pattern(s, "any").tolist() == [False, True, True, False]
    assert pattern(s, "bullish").tolist() == [False, True, False, False]
    assert pattern(s, "bearish").tolist() == [False, False, True, False]


# ── Lookahead safety (pazarlıksız kural #1) ──────────────────────────────────
@pytest.mark.parametrize("direction", ["up", "down", "cross"])
def test_threshold_cross_ignores_future(direction: str) -> None:
    rng = np.random.default_rng(3)
    x = pd.Series(rng.standard_normal(50).cumsum())
    cut = 30
    base = threshold_cross(x, 0.0, direction)  # type: ignore[arg-type]

    mutated = x.copy()
    mutated.iloc[cut:] = 999.0  # arbitrary future rewrite
    after = threshold_cross(mutated, 0.0, direction)  # type: ignore[arg-type]

    # Signals at bars < cut must be identical — no future leakage.
    pd.testing.assert_series_equal(base.iloc[:cut], after.iloc[:cut])


def test_line_cross_ignores_future() -> None:
    rng = np.random.default_rng(4)
    a = pd.Series(rng.standard_normal(40).cumsum())
    b = pd.Series(rng.standard_normal(40).cumsum())
    cut = 25
    base = line_cross(a, b, "cross")
    a2, b2 = a.copy(), b.copy()
    a2.iloc[cut:] = -50.0
    b2.iloc[cut:] = 50.0
    after = line_cross(a2, b2, "cross")
    pd.testing.assert_series_equal(base.iloc[:cut], after.iloc[:cut])
