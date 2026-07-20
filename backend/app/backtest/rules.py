"""Turn a config's rule clauses (§5.4 primitives) into boolean signal series.

Operands in a clause reference either a price field (``open/high/low/close/
volume``), an indicator ``key`` (single-output), or ``key.output`` (multi-output).
Every primitive evaluates at bar *close* (see ``app.indicators.signals``), so the
signals produced here are lookahead-safe by construction.
"""

from __future__ import annotations

from functools import reduce

import pandas as pd

from app.backtest.config import Direction, RuleClause, Rules
from app.indicators.signals import (
    band_touch,
    line_cross,
    pattern,
    regime,
    slope,
    threshold_cross,
)

_PRICE_FIELDS = ("open", "high", "low", "close", "volume")


def resolve_operands(
    ohlcv: pd.DataFrame, indicator_frames: dict[str, pd.DataFrame]
) -> dict[str, pd.Series]:
    """Build the operand → Series lookup rules reference.

    Every series is index-reset to align row-for-row with ``ohlcv``. Single-output
    indicators are reachable by bare ``key``; every output is also reachable by
    ``key.output``.
    """
    ops: dict[str, pd.Series] = {}
    for col in _PRICE_FIELDS:
        if col in ohlcv:
            ops[col] = ohlcv[col].reset_index(drop=True)
    for key, frame in indicator_frames.items():
        outputs = [c for c in frame.columns if c != "ts"]
        if len(outputs) == 1:
            ops[key] = frame[outputs[0]].reset_index(drop=True)
        for out in outputs:
            ops[f"{key}.{out}"] = frame[out].reset_index(drop=True)
    return ops


def _series(ops: dict[str, pd.Series], name: object) -> pd.Series:
    key = str(name)
    if key not in ops:
        raise KeyError(f"unknown operand: {key!r}")
    return ops[key]


def build_clause(clause: RuleClause, ops: dict[str, pd.Series]) -> pd.Series:
    """Evaluate one primitive clause to a boolean Series."""
    p = clause.primitive
    a = clause.args
    if p == "threshold_cross":
        return threshold_cross(_series(ops, a["x"]), float(a["level"]), a.get("direction", "up"))  # type: ignore[arg-type]
    if p == "line_cross":
        return line_cross(_series(ops, a["a"]), _series(ops, a["b"]), a.get("direction", "up"))  # type: ignore[arg-type]
    if p == "slope":
        return slope(
            _series(ops, a["x"]),
            int(a.get("lookback", 1)),
            a.get("direction", "up"),  # type: ignore[arg-type]
            float(a.get("eps", 0.0)),
        )
    if p == "band_touch":
        return band_touch(
            _series(ops, a["price"]),
            _series(ops, a["upper"]),
            _series(ops, a["lower"]),
            a.get("mode", "touch_lower"),  # type: ignore[arg-type]
        )
    if p == "regime":
        return regime(_series(ops, a["x"]), str(a["rule"]))
    if p == "pattern":
        return pattern(_series(ops, a["series"]), a.get("direction", "any"))  # type: ignore[arg-type]
    # Fall back to a plugin-contributed primitive (doc §8.6, Python layer). Lazy
    # import keeps the built-in path free of any strategy-plugin dependency.
    from app.strategy.plugin_registry import get_plugin_registry

    custom = get_plugin_registry().get_primitive(p)
    if custom is not None:
        return custom(ops, dict(a)).fillna(False).astype(bool)
    raise ValueError(f"unknown primitive: {p!r}")


def _combine(clauses: list[RuleClause], ops: dict[str, pd.Series], n: int) -> pd.Series:
    """AND-combine a clause list into one boolean Series (empty list → all False)."""
    if not clauses:
        return pd.Series(False, index=range(n))
    parts = [build_clause(c, ops) for c in clauses]
    return reduce(lambda x, y: x & y, parts).fillna(False).astype(bool)


def build_signals(
    rules: Rules, ops: dict[str, pd.Series], direction: Direction, n: int
) -> dict[str, pd.Series]:
    """Return the four boolean signal series, masked by the allowed direction."""
    long_entry = _combine(rules.long_entry, ops, n)
    long_exit = _combine(rules.long_exit, ops, n)
    short_entry = _combine(rules.short_entry, ops, n)
    short_exit = _combine(rules.short_exit, ops, n)

    false = pd.Series(False, index=range(n))
    if direction == "long":
        short_entry, short_exit = false, false
    elif direction == "short":
        long_entry, long_exit = false, false
    return {
        "long_entry": long_entry,
        "long_exit": long_exit,
        "short_entry": short_entry,
        "short_exit": short_exit,
    }
