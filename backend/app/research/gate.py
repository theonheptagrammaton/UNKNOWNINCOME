"""Aşama 5.5 — the deflation gate (doc §23.5).

A non-negotiable stage between walk-forward (Aşama 5) and the leaderboard (Aşama 6).
A WFO survivor stays a *candidate* only if it also clears **all four** hard checks::

    DSR < 0.95        → REJECT   (Sharpe is probably luck)
    PBO ≥ 0.40        → REJECT   (selection is probably overfit)
    OOS trades < 30   → REJECT   (evidence, not anecdote)
    OOS return ≤ B&H  → REJECT   (must beat simply holding)

The thresholds are code constants imported from :mod:`app.research.deflation`; there
is no config path that loosens them (§23.5). An uncomputable PBO (a single-config
cohort, or too few observations) is a **failure**, never a pass — passing the gate by
being unable to test is loosening the gate (§30).

This module is pure: it turns numbers into a verdict. The pipeline computes the inputs
(moments, trial counts, PBO cohorts, buy & hold) and calls :func:`evaluate_gate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.research.deflation import (
    DSR_MIN,
    MIN_OOS_TRADES,
    PBO_MAX,
    deflated_sharpe,
    expected_max_sharpe,
)


def sharpe_moments(returns: np.ndarray) -> tuple[float, float, float, int]:
    """Per-observation Sharpe, skew, (non-excess) kurtosis and count of a return series.

    Sharpe uses the sample std (ddof=1); skew and kurtosis are the population
    standardized moments (Fisher–Pearson, non-excess so a normal series reads ~3) —
    the exact inputs :func:`app.research.deflation.deflated_sharpe` expects.
    """
    arr = np.asarray(returns, dtype="float64")
    arr = arr[np.isfinite(arr)]
    T = int(arr.size)
    if T < 2:
        return 0.0, 0.0, 3.0, T
    mean = float(arr.mean())
    std_sample = float(arr.std(ddof=1))
    sr = mean / std_sample if std_sample > 0 else 0.0
    std_pop = float(arr.std(ddof=0))
    if std_pop <= 0:
        return sr, 0.0, 3.0, T
    z = (arr - mean) / std_pop
    skew = float((z**3).mean())
    kurtosis = float((z**4).mean())  # non-excess (normal ≈ 3)
    return sr, skew, kurtosis, T


@dataclass
class GateInputs:
    """Everything the gate needs to judge one candidate (all raw, per-observation)."""

    sr: float  # per-trade OOS Sharpe (non-annualized)
    skew: float
    kurtosis: float  # non-excess
    oos_trades: int
    n_trials: int  # all-time family trials + this scan's breadth
    var_sr: float  # variance of the trial Sharpe estimates (scan-level)
    pbo: float | None  # None ⇒ uncomputable ⇒ fails
    oos_net_return: float
    bh_return: float  # buy & hold over the matched OOS windows


@dataclass
class GateResult:
    """The verdict for one candidate."""

    dsr: float
    sr_star: float
    pbo: float | None
    passed: bool
    reasons: list[str] = field(default_factory=list)  # empty iff passed

    def as_dict(self) -> dict:
        return {
            "dsr": self.dsr,
            "sr_star": self.sr_star,
            "pbo": self.pbo,
            "passed": self.passed,
            "reasons": self.reasons,
        }


def evaluate_gate(inp: GateInputs) -> GateResult:
    """Apply the four hard checks (doc §23.5). Fails closed on missing evidence."""
    sr_star = expected_max_sharpe(inp.n_trials, inp.var_sr)
    dsr = deflated_sharpe(inp.sr, sr_star, inp.oos_trades, inp.skew, inp.kurtosis)

    reasons: list[str] = []
    if dsr < DSR_MIN:
        reasons.append(f"DSR {dsr:.3f} < {DSR_MIN}")
    if inp.pbo is None:
        reasons.append("PBO uncomputable (cohort too small)")
    elif inp.pbo >= PBO_MAX:
        reasons.append(f"PBO {inp.pbo:.3f} ≥ {PBO_MAX}")
    if inp.oos_trades < MIN_OOS_TRADES:
        reasons.append(f"OOS trades {inp.oos_trades} < {MIN_OOS_TRADES}")
    if inp.oos_net_return <= inp.bh_return:
        reasons.append(
            f"OOS return {inp.oos_net_return:.4f} ≤ B&H {inp.bh_return:.4f}"
        )

    return GateResult(
        dsr=dsr, sr_star=sr_star, pbo=inp.pbo, passed=not reasons, reasons=reasons
    )


def gate_constants() -> dict:
    """The active gate constants — for the audit trail (§23.5) and the report."""
    return {"dsr_min": DSR_MIN, "pbo_max": PBO_MAX, "min_oos_trades": MIN_OOS_TRADES}
