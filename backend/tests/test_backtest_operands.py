"""Operand validation for backtest rules (unknown-operand guard).

A rule may reference an operand that no configured indicator produces — e.g. after
the UI swaps an indicator slot to a multi-output indicator, leaving a bare key
dangling. Instead of a raw ``KeyError``, the runner surfaces a clear, actionable
error listing the available operands.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtest.config import RuleClause, Rules
from app.backtest.rules import (
    OperandError,
    assert_operands_resolve,
    unknown_operands,
)


def _ops() -> dict[str, pd.Series]:
    s = pd.Series([1.0, 2.0, 3.0])
    return {"close": s, "ema_slow": s, "ema_fast.macd": s}


def test_unknown_operand_detected() -> None:
    rules = Rules(
        long_entry=[
            RuleClause(primitive="line_cross", args={"a": "ema_fast", "b": "ema_slow"})
        ]
    )
    assert unknown_operands(rules, _ops()) == ["ema_fast"]


def test_resolvable_operands_pass() -> None:
    rules = Rules(
        long_entry=[
            RuleClause(primitive="line_cross", args={"a": "close", "b": "ema_slow"})
        ]
    )
    assert unknown_operands(rules, _ops()) == []
    assert_operands_resolve(rules, _ops())  # no raise


def test_assert_raises_with_available_list() -> None:
    rules = Rules(
        long_entry=[RuleClause(primitive="threshold_cross", args={"x": "ema_fast"})]
    )
    with pytest.raises(OperandError) as exc:
        assert_operands_resolve(rules, _ops())
    msg = str(exc.value)
    assert "ema_fast" in msg
    assert "close" in msg and "ema_slow" in msg  # lists what IS available


def test_plugin_primitive_operands_are_skipped() -> None:
    # Unknown (plugin) primitives resolve their own operands, so validation ignores them.
    rules = Rules(
        long_entry=[RuleClause(primitive="my_custom", args={"foo": "whatever"})]
    )
    assert unknown_operands(rules, _ops()) == []
