"""Deflation math against known reference behavior (Faz 9, doc §23.3-4).

These are the reference-value checks the phase demands: the pure functions in
``app.research.deflation`` must reproduce the documented Bailey & López de Prado
identities before anything is allowed to depend on them.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from app.research.deflation import (
    EULER_MASCHERONI,
    deflated_sharpe,
    expected_max_sharpe,
    pbo_cscv,
)

_NORM = NormalDist()


# ── expected_max_sharpe (SR*₀) ──────────────────────────────────────────────────
def test_expected_max_sharpe_matches_closed_form() -> None:
    """SR*₀ equals the §23.3 formula recomputed independently."""
    n, var = 1000, 0.5
    gamma = EULER_MASCHERONI
    z1 = _NORM.inv_cdf(1 - 1 / n)
    z2 = _NORM.inv_cdf(1 - 1 / (n * math.e))
    want = math.sqrt(var) * ((1 - gamma) * z1 + gamma * z2)
    assert expected_max_sharpe(n, var) == pytest.approx(want, rel=1e-12)


def test_expected_max_sharpe_monotone_in_trials() -> None:
    """More trials ⇒ a higher benchmark the observed Sharpe must beat (§23.1)."""
    vals = [expected_max_sharpe(n, 1.0) for n in (2, 10, 100, 1000, 10000)]
    assert all(a < b for a, b in zip(vals, vals[1:], strict=False))


def test_expected_max_sharpe_scales_with_sqrt_var() -> None:
    """SR*₀ ∝ √Var[SR]."""
    a = expected_max_sharpe(500, 1.0)
    b = expected_max_sharpe(500, 4.0)
    assert b == pytest.approx(2.0 * a, rel=1e-12)


def test_expected_max_sharpe_degenerate_cases() -> None:
    """A single trial or zero variance ⇒ no selection benchmark (0)."""
    assert expected_max_sharpe(1, 5.0) == 0.0
    assert expected_max_sharpe(100, 0.0) == 0.0
    with pytest.raises(ValueError):
        expected_max_sharpe(0, 1.0)


# ── deflated_sharpe (DSR) ───────────────────────────────────────────────────────
def test_dsr_half_at_benchmark() -> None:
    """SR exactly at the benchmark ⇒ DSR = 0.5 (a coin flip)."""
    assert deflated_sharpe(0.5, 0.5, 250, 0.0, 3.0) == pytest.approx(0.5, abs=1e-12)


def test_dsr_extremes() -> None:
    """Far above the benchmark ⇒ →1; far below ⇒ →0."""
    assert deflated_sharpe(1.5, 0.1, 500, 0.0, 3.0) > 0.999
    assert deflated_sharpe(0.0, 0.8, 500, 0.0, 3.0) < 0.001


def test_dsr_matches_closed_form_normal() -> None:
    """For a normal series the denominator collapses to √(1 + ½·SR²) (Lo 2002)."""
    sr, sr_star, T = 0.30, 0.10, 200
    z = (sr - sr_star) * math.sqrt(T - 1) / math.sqrt(1.0 + 0.5 * sr * sr)
    assert deflated_sharpe(sr, sr_star, T, 0.0, 3.0) == pytest.approx(_NORM.cdf(z), rel=1e-12)


def test_dsr_penalizes_negative_skew_and_fat_tails() -> None:
    """Negative skew / excess kurtosis widen the SE ⇒ a lower, more honest DSR."""
    base = deflated_sharpe(0.3, 0.1, 200, 0.0, 3.0)
    fat = deflated_sharpe(0.3, 0.1, 200, -0.5, 8.0)
    assert fat < base


def test_dsr_too_few_observations() -> None:
    assert deflated_sharpe(1.0, 0.0, 1, 0.0, 3.0) == 0.0


# ── pbo_cscv ────────────────────────────────────────────────────────────────────
def test_pbo_dominant_config_is_zero() -> None:
    """A config that is best in every block is never OOS-below-median ⇒ PBO = 0."""
    rng = np.random.default_rng(0)
    m = rng.standard_normal((512, 8))
    m[:, 0] += 0.6  # config 0 dominates everywhere
    assert pbo_cscv(m, n_splits=8) < 0.05


def test_pbo_iid_noise_averages_near_half() -> None:
    """Pure noise ⇒ the IS winner is an OOS coin flip ⇒ mean PBO ≈ 0.5 (§23.4)."""
    pbos = [
        pbo_cscv(np.random.default_rng(s).standard_normal((1024, 12)), n_splits=16)
        for s in range(20)
    ]
    assert float(np.mean(pbos)) == pytest.approx(0.5, abs=0.08)


def test_pbo_anticorrelated_is_high() -> None:
    """When the IS winner is engineered to be the OOS loser, PBO → 1."""
    s, per = 16, 64
    T = s * per
    m = np.zeros((T, 2))
    for b in range(s):
        sl = slice(b * per, (b + 1) * per)
        good = 1.0 if b < s // 2 else -1.0
        m[sl, 0] = good * 0.5
        m[sl, 1] = -good * 0.5
    m += np.random.default_rng(0).standard_normal((T, 2)) * 0.01
    assert pbo_cscv(m, n_splits=16) > 0.9


def test_pbo_input_validation() -> None:
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 1)), n_splits=8)  # <2 configs
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 4)), n_splits=7)  # odd splits
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((4, 4)), n_splits=8)  # fewer obs than splits
