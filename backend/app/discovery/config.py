"""Discovery scan configuration + reproducible hash (doc §7, rule #6).

A scan is fully described by this config: the universe (explicit symbols or a dated
snapshot), the timeframes, the candidate indicator selection, the correlation /
combination / Optuna / WFO / Monte-Carlo budgets, and the shared cost + capital
model. ``config_hash`` is a canonical SHA-256 so the same config + seed reproduces
the same leaderboard (pazarlıksız rule #6).

``fast_mode`` is a dev shortcut: :func:`apply_fast_mode` shrinks the universe,
timeframes, candidate set and budgets so an end-to-end scan finishes in seconds.
Everything else is forward-compatible with the Phase-5 strategy genome (§8.1).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.backtest.config import CapitalConfig, CostConfig, Direction, RiskExitConfig

CandidateMode = Literal["all", "categories", "ids"]

# A compact subset spanning all three combination roles (doc §7 Aşama 3) — used by
# fast mode (and available via ``candidate.mode == "ids"``). All ids are TA-Lib.
# Roles follow roles.ROLE_BY_CATEGORY: momentum/overlap → trigger, volume/statistic
# → filter, volatility → exit. A viable combo needs ≥1 of each.
FAST_CANDIDATE_IDS = (
    "rsi", "cci", "mom", "willr",          # momentum → trigger
    "ema", "sma",                           # overlap → trigger
    "obv", "linearreg",                     # volume / statistic → filter
    "atr", "natr", "bbands",                # volatility → exit
)


class CandidateSelection(BaseModel):
    """Which registry indicators Stage 1 scans (doc §7 Aşama 1)."""

    mode: CandidateMode = "all"
    categories: list[str] = Field(default_factory=list)  # mode == "categories"
    ids: list[str] = Field(default_factory=list)  # mode == "ids"


class WFOConfig(BaseModel):
    """Walk-forward windows (doc §6.5). Days are wall-clock, not bars.

    ``reoptimize`` defaults **on** (doc §6.5.1 "nihai skor OOS'tan gelir"): each fold
    re-runs Optuna on its own train window, so the test-window score is genuinely
    out-of-sample. With it off the same full-range params are scored on windows that
    were part of the fit — an optimistic, contaminated "OOS".
    """

    train_days: int = 90
    test_days: int = 30
    step_days: int = 30
    reoptimize: bool = True  # re-run Optuna on each train fold ⇒ genuine OOS
    # Survival thresholds (doc §6.5): OOS must stay a real fraction of the in-sample
    # score and carry enough out-of-sample trades to be evidence, not noise.
    min_oos_is_ratio: float = 0.5
    min_oos_trades: int = 10


class PlateauConfig(BaseModel):
    """Parameter-plateau test (doc §6.5 point 3)."""

    enabled: bool = True
    neighbor_steps: int = 1  # perturb each param ±(neighbor_steps · step)
    min_neighbor_ratio: float = 0.5  # neighbours must score ≥ ratio × best


class FinalistConfig(BaseModel):
    """backtesting.py cross-validation of the top finalists (doc §6.1)."""

    enabled: bool = True
    top_k: int = 5
    # Relative tolerance per key metric; divergence beyond it raises an alarm.
    tolerance: dict[str, float] = Field(
        default_factory=lambda: {"net_return": 0.25, "num_trades": 0.20, "sharpe": 0.35}
    )


class ScanConfig(BaseModel):
    """A complete, reproducible discovery scan request (doc §7)."""

    market: str = "binance_usdm"
    # Universe: explicit ``symbols`` win; else the snapshot valid at
    # ``universe_as_of`` (survivorship guard, §4.5); else the latest snapshot.
    symbols: list[str] | None = None
    universe_as_of: date | None = None
    timeframes: list[str] = Field(default_factory=lambda: ["15m", "1h", "4h", "1d"])
    start_ts: int | None = None
    end_ts: int | None = None
    direction: Direction = "both"

    candidate: CandidateSelection = Field(default_factory=CandidateSelection)
    correlation_threshold: float = 0.85  # |ρ| above which signals cluster (§7 Aşama 2)
    combo_pool_per_role: int = 8  # top-K per role per cell before combining (§7 Aşama 3)
    top_n_combos: int = 50  # combos carried into Optuna (§7 Aşama 4)
    optuna_trials: int = 30
    wfo: WFOConfig = Field(default_factory=WFOConfig)
    monte_carlo_runs: int = 500
    plateau: PlateauConfig = Field(default_factory=PlateauConfig)
    finalist: FinalistConfig = Field(default_factory=FinalistConfig)

    costs: CostConfig = Field(default_factory=CostConfig)
    capital: CapitalConfig = Field(default_factory=CapitalConfig)
    risk_exit: RiskExitConfig = Field(
        default_factory=lambda: RiskExitConfig(atr_stop_mult=2.0, atr_target_mult=3.0)
    )

    fast_mode: bool = False
    seed: int = 42


def apply_fast_mode(config: ScanConfig) -> ScanConfig:
    """Shrink a config for a dev-sized end-to-end scan (idempotent)."""
    if not config.fast_mode:
        return config
    c = config.model_copy(deep=True)
    c.timeframes = ["1h"]
    c.candidate = CandidateSelection(mode="ids", ids=list(FAST_CANDIDATE_IDS))
    c.combo_pool_per_role = 3
    c.top_n_combos = 6
    c.optuna_trials = 8
    c.monte_carlo_runs = 100
    c.wfo = WFOConfig(train_days=20, test_days=10, step_days=10)
    c.finalist = FinalistConfig(
        enabled=True, top_k=3, tolerance=config.finalist.tolerance
    )
    # Symbol trimming happens at Stage-0 resolution (needs the resolved universe).
    return c


def canonical_config(config: ScanConfig) -> str:
    """Canonical JSON of a config: sorted keys, compact separators (rule #6)."""
    payload = config.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def config_hash(config: ScanConfig) -> str:
    """Reproducible 16-char SHA-256 of the canonical config (rule #6)."""
    return hashlib.sha256(canonical_config(config).encode()).hexdigest()[:16]
