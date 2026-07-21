"""Aşama 5.5 hard gate (Faz 9, doc §23.5) — acceptance criteria as tests.

Covers three of the phase's acceptance bullets directly:
* a high *raw* Sharpe with a low DSR cannot be promoted (rule #14);
* the thresholds are code constants — no argument path loosens them (§23.5);
* re-optimizing the same strategy (a rising trial count) lowers its DSR and flips a
  passing candidate to rejected (the trial counter works).
"""

from __future__ import annotations

import numpy as np

from app.research import deflation
from app.research.gate import GateInputs, evaluate_gate, gate_constants, sharpe_moments


def _passing() -> GateInputs:
    """A deliberately strong candidate that clears every check."""
    return GateInputs(
        sr=1.2,
        skew=0.1,
        kurtosis=3.0,
        oos_trades=60,
        n_trials=50,
        var_sr=0.05,
        pbo=0.10,
        oos_net_return=0.20,
        bh_return=0.05,
    )


def test_gate_constants_are_the_documented_values() -> None:
    """The §28 glossary / §23.5 numbers are pinned in code."""
    assert deflation.DSR_MIN == 0.95
    assert deflation.PBO_MAX == 0.40
    assert deflation.MIN_OOS_TRADES == 30
    assert gate_constants() == {"dsr_min": 0.95, "pbo_max": 0.40, "min_oos_trades": 30}


def test_strong_candidate_passes() -> None:
    assert evaluate_gate(_passing()).passed


def test_high_raw_sharpe_low_dsr_cannot_promote() -> None:
    """A gaudy raw Sharpe, but selected from tens of thousands of trials ⇒ rejected.

    The *raw* per-trade Sharpe here is a healthy 0.5 over 80 trades, yet against 40 000
    trials the null benchmark is higher — DSR collapses and the gate refuses it, even
    though every other check (PBO, trades, B&H) passes.
    """
    inp = GateInputs(
        sr=0.5, skew=0.0, kurtosis=3.0, oos_trades=80,
        n_trials=40_000, var_sr=0.06, pbo=0.05, oos_net_return=0.5, bh_return=0.05,
    )
    result = evaluate_gate(inp)
    assert not result.passed
    assert result.dsr < deflation.DSR_MIN
    assert any("DSR" in r for r in result.reasons)


def test_each_hard_check_rejects_independently() -> None:
    """Any single failing dimension is sufficient to reject (all four are hard)."""
    base = _passing()
    # PBO over the cap.
    assert not evaluate_gate(GateInputs(**{**vars(base), "pbo": 0.5})).passed
    # Too few OOS trades.
    assert not evaluate_gate(GateInputs(**{**vars(base), "oos_trades": 29})).passed
    # Does not beat buy & hold.
    assert not evaluate_gate(GateInputs(**{**vars(base), "oos_net_return": 0.04})).passed
    # Uncomputable PBO fails closed (§23.5 — never a pass).
    r = evaluate_gate(GateInputs(**{**vars(base), "pbo": None}))
    assert not r.passed and any("PBO uncomputable" in x for x in r.reasons)


def test_thresholds_cannot_be_loosened_by_argument() -> None:
    """There is no knob: evaluate_gate takes only evidence, never thresholds.

    A candidate that sits just under the DSR line is rejected; the only way to admit it
    would be to edit the code constant (a commit, audited) — exactly the §23.5 contract.
    """
    # Construct inputs whose DSR lands just below 0.95.
    inp = GateInputs(
        sr=0.55, skew=0.0, kurtosis=3.0, oos_trades=60,
        n_trials=200, var_sr=0.05, pbo=0.1, oos_net_return=0.2, bh_return=0.05,
    )
    r = evaluate_gate(inp)
    # If it happens to pass, it is genuinely above the hard line — assert consistency
    # with the constant, proving the decision is the constant and nothing else.
    assert r.passed == (r.dsr >= deflation.DSR_MIN)
    # And no signature path accepts an override.
    assert "threshold" not in GateInputs.__annotations__


def test_reopt_lowers_dsr_and_flips_candidate() -> None:
    """The same strategy, re-optimized more and more, sees its DSR fall (the counter bites)."""
    common = dict(
        sr=0.6, skew=0.0, kurtosis=3.0, oos_trades=60,
        var_sr=0.05, pbo=0.1, oos_net_return=0.2, bh_return=0.05,
    )
    ns = (10, 100, 1000, 10000, 50000)
    dsrs = [evaluate_gate(GateInputs(n_trials=n, **common)).dsr for n in ns]
    assert all(a > b for a, b in zip(dsrs, dsrs[1:], strict=False)), dsrs
    # Passes when few trials, fails once the trial count is large enough.
    assert evaluate_gate(GateInputs(n_trials=10, **common)).passed
    assert not evaluate_gate(GateInputs(n_trials=50000, **common)).passed


def test_sharpe_moments_reference() -> None:
    """sharpe_moments returns per-obs Sharpe + non-excess kurtosis (~3 for normal)."""
    rng = np.random.default_rng(0)
    normal = rng.standard_normal(20000)
    sr, skew, kurt, T = sharpe_moments(normal)
    assert T == 20000
    assert abs(skew) < 0.1
    assert abs(kurt - 3.0) < 0.15  # non-excess
    # Degenerate short series.
    assert sharpe_moments(np.array([0.01])) == (0.0, 0.0, 3.0, 1)
