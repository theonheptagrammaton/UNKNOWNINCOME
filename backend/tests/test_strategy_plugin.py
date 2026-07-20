"""Plugin loader + custom primitive slot into the rule engine (doc §8.6)."""

from __future__ import annotations

import pandas as pd

from app.backtest.config import RuleClause
from app.backtest.rules import build_clause
from app.strategy.plugin_loader import load_plugins
from app.strategy.plugin_registry import get_plugin_registry


def test_example_plugin_registers_pct_above() -> None:
    loaded = load_plugins()
    assert "example_pct_above" in loaded
    assert "pct_above" in get_plugin_registry().names()


def test_custom_primitive_evaluates_via_rule_engine() -> None:
    load_plugins()  # ensure registered
    ops = {
        "close": pd.Series([100.0, 100.0, 100.0]),
        "ema": pd.Series([100.0, 98.0, 95.0]),
    }
    clause = RuleClause(primitive="pct_above", args={"x": "close", "ref": "ema", "pct": 2.0})
    out = build_clause(clause, ops)
    # close ≥ ema×1.02 ⇒ [100≥102 F, 100≥99.96 T, 100≥96.9 T].
    assert list(out) == [False, True, True]


def test_reload_is_idempotent() -> None:
    first = load_plugins()
    second = load_plugins()
    assert first == second
    assert get_plugin_registry().names() == ["pct_above"]
