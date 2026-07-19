"""Finalist engine seam (doc §6.1).

The lean engine is the mass-scan motor; a *finalist* engine re-runs a candidate a
second time and its metrics are compared against the primary run. Any engine that
implements :class:`FinalistEngine` slots in behind the same seam — backtesting.py
when it imports, an independent lean re-implementation otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.backtest.config import RunConfig


@dataclass
class FinalistResult:
    """The reduced metric set the cross-check compares (doc §6.3 subset)."""

    net_return: float
    num_trades: int
    sharpe: float
    final_equity: float
    engine: str  # "backtesting_py" | "lean_second"


class FinalistEngine(Protocol):
    """A second, independent engine for finalist cross-validation."""

    name: str

    def verify(self, config: RunConfig) -> FinalistResult: ...
