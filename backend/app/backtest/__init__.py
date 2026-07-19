"""Backtest engine wrappers, cost model, metrics (Phase 3)."""

from __future__ import annotations

from app.backtest.config import (
    CapitalConfig,
    CostConfig,
    IndicatorSpec,
    RuleClause,
    Rules,
    RunConfig,
    config_hash,
)
from app.backtest.engine import BacktestResult, Trade, run_engine
from app.backtest.metrics import compute_metrics
from app.backtest.runner import NoDataError, run_backtest

__all__ = [
    "BacktestResult",
    "CapitalConfig",
    "CostConfig",
    "IndicatorSpec",
    "NoDataError",
    "RuleClause",
    "Rules",
    "RunConfig",
    "Trade",
    "compute_metrics",
    "config_hash",
    "run_backtest",
    "run_engine",
]
