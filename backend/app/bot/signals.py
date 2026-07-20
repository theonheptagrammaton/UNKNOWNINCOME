"""Latest-bar signal evaluation with full justification (doc §10.2, rule #1).

The backtest produces boolean signal *series*; a live bot needs, for the single
just-closed bar, (a) which of the four signal groups fire and (b) *why* — the exact
clauses that fired and the indicator values behind them. This module reuses the
identical rule engine (:mod:`app.backtest.rules`), so a paper signal is computed by
the same code the strategy was validated with.

Every signal therefore carries a non-empty ``reason`` and an ``indicator_snapshot``
— pazarlıksız (doc §2, §10.2). Evaluation is at bar close (rule #1); the order it
implies is filled at the current price on the next tick, exactly like the backtest's
next-open fill.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtest.config import RunConfig
from app.backtest.rules import build_clause, resolve_operands

_GROUPS = ("long_entry", "long_exit", "short_entry", "short_exit")


@dataclass
class LatestSignal:
    """The four group verdicts at the last bar + fired clauses + snapshot."""

    ts: int
    long_entry: bool = False
    long_exit: bool = False
    short_entry: bool = False
    short_exit: bool = False
    reason: dict[str, list[dict]] = field(default_factory=dict)  # group → fired clauses
    snapshot: dict[str, float | None] = field(default_factory=dict)

    def group(self, name: str) -> bool:
        return bool(getattr(self, name))


def _last_value(series: pd.Series, i: int) -> float | None:
    if i < 0 or i >= len(series):
        return None
    val = series.iloc[i]
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _clause_operands(args: dict, ops: dict[str, pd.Series]) -> list[str]:
    """Arg values that name a resolvable operand (price field or indicator key)."""
    return [str(v) for v in args.values() if isinstance(v, str) and str(v) in ops]


def evaluate_latest(
    config: RunConfig, ohlcv: pd.DataFrame, frames: dict[str, pd.DataFrame]
) -> LatestSignal | None:
    """Evaluate all rule groups at the final bar; return the verdict + justification."""
    n = len(ohlcv)
    if n == 0:
        return None
    ops = resolve_operands(ohlcv, frames)
    i = n - 1
    ts = int(ohlcv["ts"].iloc[-1])

    groups = {
        "long_entry": config.rules.long_entry,
        "long_exit": config.rules.long_exit,
        "short_entry": config.rules.short_entry,
        "short_exit": config.rules.short_exit,
    }
    verdict: dict[str, bool] = {}
    reason: dict[str, list[dict]] = {}
    referenced: set[str] = set()

    for name in _GROUPS:
        clauses = groups[name]
        if not clauses:
            verdict[name] = False
            continue
        fired_records: list[dict] = []
        all_true = True
        for clause in clauses:
            series = build_clause(clause, ops)
            is_true = bool(series.iloc[i]) if i < len(series) else False
            all_true = all_true and is_true
            for op in _clause_operands(clause.args, ops):
                referenced.add(op)
            if is_true:
                fired_records.append({"primitive": clause.primitive, "args": dict(clause.args)})
        verdict[name] = all_true
        if all_true:
            reason[name] = fired_records

    # Direction mask (doc §6.2 / rules.build_signals).
    if config.direction == "long":
        verdict["short_entry"] = verdict["short_exit"] = False
        reason.pop("short_entry", None)
        reason.pop("short_exit", None)
    elif config.direction == "short":
        verdict["long_entry"] = verdict["long_exit"] = False
        reason.pop("long_entry", None)
        reason.pop("long_exit", None)

    snapshot: dict[str, float | None] = {op: _last_value(ops[op], i) for op in sorted(referenced)}
    if "close" in ops:
        snapshot.setdefault("close", _last_value(ops["close"], i))

    return LatestSignal(
        ts=ts,
        long_entry=verdict["long_entry"],
        long_exit=verdict["long_exit"],
        short_entry=verdict["short_entry"],
        short_exit=verdict["short_exit"],
        reason={k: v for k, v in reason.items() if v},
        snapshot=snapshot,
    )
