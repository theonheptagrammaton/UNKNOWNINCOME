"""Example strategy plugin: a ``pct_above`` primitive (doc §8.6, Python layer).

Demonstrates the plugin contract end to end. This primitive is true where operand
``x`` sits at least ``pct`` percent above operand ``ref`` on the current bar —
e.g. "close is ≥ 2% above ema:200". It is deliberately something the six built-ins
don't express directly, showing that a plugin genuinely extends the grammar.

Lookahead-safe by construction: it reads only bar ``t`` (no forward shift).

Usage in a genome rule clause::

    {"primitive": "pct_above", "args": {"x": "close", "ref": "ema_slow", "pct": 2.0}}
"""

from __future__ import annotations

import pandas as pd

from app.strategy.plugin_registry import PluginRegistry


def pct_above(ops: dict[str, pd.Series], args: dict) -> pd.Series:
    """True where ``x`` is ≥ ``pct``% above ``ref`` (current bar only)."""
    x = ops[str(args["x"])]
    ref = ops[str(args["ref"])]
    pct = float(args.get("pct", 0.0)) / 100.0
    return (x >= ref * (1.0 + pct)).fillna(False).astype(bool)


def register(registry: PluginRegistry) -> None:
    """Entry point the loader calls (doc §8.6)."""
    registry.register_primitive("pct_above", pct_above)
