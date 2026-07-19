"""Synthesize default entry/exit rules for an indicator (doc §5.4, §7).

Stage 1 runs every indicator standalone with a *default* rule so it produces a
comparable score; Stage 3 reuses the trigger's entry/exit and adds a filter's
confirmation. The synthesis is deliberately **scale-free** where the indicator's
range is unknown — a momentum oscillator with a known band uses ``threshold_cross``,
a price-scale moving average uses ``line_cross`` against price, everything else
uses ``slope`` (turning up/down), and candlesticks use ``pattern``. This keeps the
grammar valid for any of the 225 registry indicators without per-indicator tables.
"""

from __future__ import annotations

from app.backtest.config import Direction, RuleClause, Rules

# Known oscillator bands (oversold, overbought) for the well-known momentum ids;
# anything not listed falls back to the scale-free ``slope`` trigger.
OSCILLATOR_LEVELS: dict[str, tuple[float, float]] = {
    "rsi": (30.0, 70.0),
    "stochrsi": (20.0, 80.0),
    "stoch": (20.0, 80.0),
    "stochf": (20.0, 80.0),
    "cci": (-100.0, 100.0),
    "cmo": (-50.0, 50.0),
    "mfi": (20.0, 80.0),
    "willr": (-80.0, -20.0),
    "ultosc": (30.0, 70.0),
    "mom": (0.0, 0.0),  # zero-line cross
    "roc": (0.0, 0.0),
    "rocp": (0.0, 0.0),
    "trix": (0.0, 0.0),
    "apo": (0.0, 0.0),
    "ppo": (0.0, 0.0),
}

_PRICE_SCALE_CATEGORIES = frozenset({"overlap", "price"})
_SLOPE_LOOKBACK = 1
_FILTER_LOOKBACK = 3


def _clause(primitive: str, **args: str | float | int) -> RuleClause:
    return RuleClause(primitive=primitive, args=args)  # type: ignore[arg-type]


def _threshold_rules(operand: str, low: float, high: float, direction: Direction) -> Rules:
    """Oversold-bounce entry / overbought-fade exit (mirror for shorts)."""
    return _mask(
        [_clause("threshold_cross", x=operand, level=low, direction="up")],
        [_clause("threshold_cross", x=operand, level=high, direction="down")],
        [_clause("threshold_cross", x=operand, level=high, direction="down")],
        [_clause("threshold_cross", x=operand, level=low, direction="up")],
        direction,
    )


def _line_cross_rules(operand: str, direction: Direction) -> Rules:
    """Price crossing a price-scale line (e.g. close × EMA)."""
    return _mask(
        [_clause("line_cross", a="close", b=operand, direction="up")],
        [_clause("line_cross", a="close", b=operand, direction="down")],
        [_clause("line_cross", a="close", b=operand, direction="down")],
        [_clause("line_cross", a="close", b=operand, direction="up")],
        direction,
    )


def _slope_rules(operand: str, direction: Direction) -> Rules:
    """Scale-free fallback: enter when the series turns up, exit when it turns down."""
    return _mask(
        [_clause("slope", x=operand, lookback=_SLOPE_LOOKBACK, direction="up")],
        [_clause("slope", x=operand, lookback=_SLOPE_LOOKBACK, direction="down")],
        [_clause("slope", x=operand, lookback=_SLOPE_LOOKBACK, direction="down")],
        [_clause("slope", x=operand, lookback=_SLOPE_LOOKBACK, direction="up")],
        direction,
    )


def _pattern_rules(operand: str, direction: Direction) -> Rules:
    """Candlestick pattern: bullish opens long, bearish opens short."""
    return _mask(
        [_clause("pattern", series=operand, direction="bullish")],
        [_clause("pattern", series=operand, direction="bearish")],
        [_clause("pattern", series=operand, direction="bearish")],
        [_clause("pattern", series=operand, direction="bullish")],
        direction,
    )


def _mask(
    le: list[RuleClause], lx: list[RuleClause],
    se: list[RuleClause], sx: list[RuleClause], direction: Direction,
) -> Rules:
    if direction == "long":
        se, sx = [], []
    elif direction == "short":
        le, lx = [], []
    return Rules(long_entry=le, long_exit=lx, short_entry=se, short_exit=sx)


def standalone_rules(
    indicator_id: str, category: str, operand: str, direction: Direction = "both"
) -> Rules:
    """Default entry/exit rules for a single indicator (Stage 1)."""
    if category == "pattern":
        return _pattern_rules(operand, direction)
    if category in _PRICE_SCALE_CATEGORIES:
        return _line_cross_rules(operand, direction)
    levels = OSCILLATOR_LEVELS.get(indicator_id)
    if levels is not None:
        return _threshold_rules(operand, levels[0], levels[1], direction)
    return _slope_rules(operand, direction)


def filter_confirm(operand: str) -> tuple[list[RuleClause], list[RuleClause]]:
    """Directional confirmation clauses (long_confirm, short_confirm) for a filter.

    A filter is a *state*, not a crossing: the series rising over a few bars
    confirms longs, falling confirms shorts (doc §7 Aşama 3, regime/trend onayı).
    """
    long_confirm = [_clause("slope", x=operand, lookback=_FILTER_LOOKBACK, direction="up")]
    short_confirm = [_clause("slope", x=operand, lookback=_FILTER_LOOKBACK, direction="down")]
    return long_confirm, short_confirm
