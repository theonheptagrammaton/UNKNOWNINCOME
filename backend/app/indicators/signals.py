"""Signal primitives — the grammar of combination (doc §5.4).

Indicators are raw series; strategies need rules. Each primitive wraps indicator
outputs into a boolean Series so any two or three combine without grammar errors.

**Lookahead safety (pazarlıksız kural #1).** Every primitive is evaluated at bar
*close*: the signal at bar ``t`` depends only on bars ``≤ t``. Crossings compare
the current bar against the *previous* one via ``.shift(1)`` — never ``.shift(-1)``.
A signal computed now can therefore never change when a future bar arrives; the
test suite proves this by mutating future bars and asserting the past is stable.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

CrossDir = Literal["up", "down", "cross"]
SlopeDir = Literal["up", "down", "flat"]
BandMode = Literal[
    "touch_upper", "touch_lower", "break_upper", "break_lower", "revert_upper", "revert_lower"
]
PatternDir = Literal["any", "bullish", "bearish"]


def _as_bool(series: pd.Series) -> pd.Series:
    """Normalise a possibly-NaN boolean series to strict bool (NaN → False)."""
    return series.fillna(False).astype(bool)


def threshold_cross(x: pd.Series, level: float, direction: CrossDir = "up") -> pd.Series:
    """True where ``x`` crosses a constant ``level`` (e.g. RSI crossing 30 upward).

    ``up``: was ≤ level, now > level. ``down``: was ≥ level, now < level.
    ``cross``: either direction.
    """
    prev = x.shift(1)
    up = (x > level) & (prev <= level)
    down = (x < level) & (prev >= level)
    if direction == "up":
        return _as_bool(up)
    if direction == "down":
        return _as_bool(down)
    return _as_bool(up | down)


def line_cross(a: pd.Series, b: pd.Series, direction: CrossDir = "up") -> pd.Series:
    """True where line ``a`` crosses line ``b`` (e.g. EMA9 × EMA21).

    ``up``: a was ≤ b, now a > b. ``down``: a was ≥ b, now a < b.
    """
    a_prev, b_prev = a.shift(1), b.shift(1)
    up = (a > b) & (a_prev <= b_prev)
    down = (a < b) & (a_prev >= b_prev)
    if direction == "up":
        return _as_bool(up)
    if direction == "down":
        return _as_bool(down)
    return _as_bool(up | down)


def slope(
    x: pd.Series, lookback: int = 1, direction: SlopeDir = "up", eps: float = 0.0
) -> pd.Series:
    """Direction filter on the change over ``lookback`` bars.

    ``up``: x - x[-lookback] > eps. ``down``: < -eps. ``flat``: |diff| ≤ eps.
    """
    diff = x - x.shift(lookback)
    if direction == "up":
        return _as_bool(diff > eps)
    if direction == "down":
        return _as_bool(diff < -eps)
    return _as_bool(diff.abs() <= eps)


def band_touch(
    price: pd.Series, upper: pd.Series, lower: pd.Series, mode: BandMode = "touch_lower"
) -> pd.Series:
    """Band interaction for Bollinger/Keltner/Donchian-style envelopes.

    ``touch_*``: price at/beyond the band this bar. ``break_*``: crossed beyond the
    band this bar. ``revert_*``: crossed back inside the band this bar.
    """
    p_prev = price.shift(1)
    if mode == "touch_upper":
        return _as_bool(price >= upper)
    if mode == "touch_lower":
        return _as_bool(price <= lower)
    if mode == "break_upper":
        return _as_bool((price > upper) & (p_prev <= upper.shift(1)))
    if mode == "break_lower":
        return _as_bool((price < lower) & (p_prev >= lower.shift(1)))
    if mode == "revert_upper":
        return _as_bool((price < upper) & (p_prev >= upper.shift(1)))
    # revert_lower
    return _as_bool((price > lower) & (p_prev <= lower.shift(1)))


def regime(x: pd.Series, rule: str) -> pd.Series:
    """Stateful regime filter (e.g. ``"gt:25"`` for ADX > 25 → trend present).

    Supported rules: ``gt:V``, ``ge:V``, ``lt:V``, ``le:V``, ``between:LO:HI``.
    A regime is a *state* of the current bar, not a crossing.
    """
    parts = rule.split(":")
    op = parts[0]
    if op in ("gt", "ge", "lt", "le"):
        level = float(parts[1])
        if op == "gt":
            return _as_bool(x > level)
        if op == "ge":
            return _as_bool(x >= level)
        if op == "lt":
            return _as_bool(x < level)
        return _as_bool(x <= level)
    if op == "between":
        lo, hi = float(parts[1]), float(parts[2])
        return _as_bool((x >= lo) & (x <= hi))
    raise ValueError(f"unsupported regime rule: {rule!r}")


def pattern(series: pd.Series, direction: PatternDir = "any") -> pd.Series:
    """Boolean signal from a TA-Lib candlestick output (±100 → bull/bear, 0 → none)."""
    if direction == "bullish":
        return _as_bool(series > 0)
    if direction == "bearish":
        return _as_bool(series < 0)
    return _as_bool(series != 0)


PRIMITIVES = {
    "threshold_cross": threshold_cross,
    "line_cross": line_cross,
    "slope": slope,
    "band_touch": band_touch,
    "regime": regime,
    "pattern": pattern,
}
