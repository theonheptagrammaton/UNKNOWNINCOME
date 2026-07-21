"""Deflated Sharpe Ratio + PBO/CSCV — the pure statistics of luck (doc §23.3-4).

Bailey & López de Prado (2014), *The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting and Non-Normality*. Three pure functions, no
DB, no I/O, tested against known reference values:

* :func:`expected_max_sharpe` — the Sharpe you expect to see from the *best* of N
  independent strategies that all truly have zero edge. The benchmark a real edge
  must beat.
* :func:`deflated_sharpe` — the probability the observed Sharpe is above that
  benchmark, corrected for skew, kurtosis and sample length. A probability, 0..1.
* :func:`pbo_cscv` — the Probability of Backtest Overfitting via Combinatorially
  Symmetric Cross-Validation: how often the in-sample winner is an out-of-sample
  loser. ``PBO ≥ 0.5`` ⇒ your selection is a coin flip.

Normal cdf/ppf come from :class:`statistics.NormalDist` (stdlib, reference quality)
so the package needs no SciPy.

The hard-gate thresholds live here as **code constants** (doc §23.5): loosening
them is a source change, never a config knob — a commit, reviewed and audited.
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np

# Euler–Mascheroni constant (doc §23.3 formula for SR*₀).
EULER_MASCHERONI = 0.5772156649015329

_NORM = NormalDist()  # standard normal N(0, 1)

# ── Aşama 5.5 hard gate — CODE CONSTANTS, not config (doc §23.5, rule #14). ──────
# Loosening any of these requires a source change (commit + audit_log row); there is
# deliberately no configuration path that relaxes them (§30: the leaderboard emptying
# out is the gate working — do not lower it).
DSR_MIN = 0.95  # deflated Sharpe must clear this probability
PBO_MAX = 0.40  # probability of overfitting must stay below this
MIN_OOS_TRADES = 30  # fewer than this is anecdote, not evidence


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Expected maximum Sharpe under the null of zero edge (SR*₀, doc §23.3 step 1).

    With ``n_trials`` independent strategies that all truly have zero Sharpe, the best
    one still shows a positive Sharpe by chance alone. Its expected value is::

        SR*₀ = √Var[SR] · [ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]

    where ``γ`` is Euler–Mascheroni and ``Z⁻¹`` the standard-normal quantile. ``SR``
    and ``var_sr`` must be in the same (per-observation, non-annualized) units as the
    Sharpe later handed to :func:`deflated_sharpe`.

    A single trial means no selection, so the benchmark is 0. ``var_sr <= 0`` (all
    trials identical) likewise yields 0.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be ≥ 1, got {n_trials}")
    if n_trials == 1 or var_sr <= 0.0:
        return 0.0
    n = float(n_trials)
    gamma = EULER_MASCHERONI
    z1 = _NORM.inv_cdf(1.0 - 1.0 / n)
    z2 = _NORM.inv_cdf(1.0 - 1.0 / (n * math.e))
    return math.sqrt(var_sr) * ((1.0 - gamma) * z1 + gamma * z2)


def deflated_sharpe(
    sr: float, sr_star: float, T: int, skew: float, kurtosis: float
) -> float:
    """Deflated Sharpe Ratio — P(observed Sharpe beats the null benchmark) (§23.3 step 2).

    ::

        DSR = Z[ (SR − SR*₀)·√(T−1) / √(1 − γ₃·SR + ((γ₄−1)/4)·SR²) ]

    ``sr`` is the observed **per-observation** Sharpe, ``sr_star`` the benchmark from
    :func:`expected_max_sharpe`, ``T`` the number of observations (trades/returns),
    ``skew`` (γ₃) and ``kurtosis`` (γ₄, **non-excess** — a normal distribution is 3)
    of the return series.

    Returns a probability in ``[0, 1]``. ``DSR = 0.95`` means "a 5% chance this Sharpe
    is luck"; at ``SR = SR*₀`` it is exactly 0.5.
    """
    if T <= 1:
        return 0.0
    denom_var = 1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * sr * sr
    # The standard error of the Sharpe estimator; guard the (numerically rare)
    # non-positive case from extreme skew/kurtosis so we never take √ of a negative.
    if denom_var <= 0.0:
        denom_var = 1e-12
    z = (sr - sr_star) * math.sqrt(T - 1) / math.sqrt(denom_var)
    return float(_NORM.cdf(z))


def _block_stats(
    matrix: np.ndarray, blocks: list[np.ndarray]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-block (count, Σr, Σr²) over configs — the CSCV precompute.

    Returns three arrays indexed ``[block, config]`` so any IS/OOS union's per-config
    Sharpe is an O(S) sum of blocks instead of an O(T) re-scan (makes C(16,8)=12 870
    combinations feasible).
    """
    n_blocks = len(blocks)
    n_cfg = matrix.shape[1]
    counts = np.empty(n_blocks)
    sums = np.empty((n_blocks, n_cfg))
    sqsums = np.empty((n_blocks, n_cfg))
    for b, rows in enumerate(blocks):
        sub = matrix[rows]
        counts[b] = sub.shape[0]
        sums[b] = sub.sum(axis=0)
        sqsums[b] = np.square(sub).sum(axis=0)
    return counts, sums, sqsums


def _sharpe_from_blocks(
    block_ids: tuple[int, ...],
    counts: np.ndarray,
    sums: np.ndarray,
    sqsums: np.ndarray,
) -> np.ndarray:
    """Per-config Sharpe over the union of ``block_ids`` from precomputed moments."""
    n = counts[list(block_ids)].sum()
    s = sums[list(block_ids)].sum(axis=0)
    sq = sqsums[list(block_ids)].sum(axis=0)
    if n <= 1:
        return np.zeros(sums.shape[1])
    mean = s / n
    var = sq / n - np.square(mean)
    std = np.sqrt(np.clip(var, 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(std > 0, mean / std, 0.0)
    return np.nan_to_num(sharpe, nan=0.0, posinf=0.0, neginf=0.0)


def pbo_cscv(returns_matrix: np.ndarray, n_splits: int = 16) -> float:
    """Probability of Backtest Overfitting via CSCV (doc §23.4).

    ``returns_matrix`` is ``(T observations, N configs)`` of per-observation returns on
    a **shared** time axis. The series is cut into ``n_splits`` (S) contiguous blocks;
    over all ``C(S, S/2)`` ways to choose S/2 blocks as in-sample (the complement is
    out-of-sample) we pick the IS-best config and record its OOS relative rank ω. With
    ``λ = ln(ω/(1−ω))``::

        PBO = fraction of combinations with λ ≤ 0  (IS-winner lands OOS-below-median)

    ``PBO ≥ 0.5`` means the selection process is no better than a coin flip. Raises
    ``ValueError`` if there are fewer than 2 configs, ``n_splits`` is odd, or there are
    fewer observations than blocks — the caller (Aşama 5.5) treats an uncomputable PBO
    as a gate failure, never a pass.
    """
    matrix = np.asarray(returns_matrix, dtype="float64")
    if matrix.ndim != 2:
        raise ValueError(f"returns_matrix must be 2-D (T, N), got shape {matrix.shape}")
    T, n_cfg = matrix.shape
    if n_cfg < 2:
        raise ValueError(f"CSCV needs ≥ 2 configs, got {n_cfg}")
    if n_splits < 2 or n_splits % 2 != 0:
        raise ValueError(f"n_splits must be a positive even integer, got {n_splits}")
    if T < n_splits:
        raise ValueError(f"need ≥ n_splits ({n_splits}) observations, got {T}")

    blocks = np.array_split(np.arange(T), n_splits)
    counts, sums, sqsums = _block_stats(matrix, blocks)
    all_blocks = set(range(n_splits))

    below_median = 0
    total = 0
    for is_blocks in combinations(range(n_splits), n_splits // 2):
        oos_blocks = tuple(sorted(all_blocks - set(is_blocks)))
        is_perf = _sharpe_from_blocks(is_blocks, counts, sums, sqsums)
        oos_perf = _sharpe_from_blocks(oos_blocks, counts, sums, sqsums)
        best = int(np.argmax(is_perf))
        # Relative rank ω of the IS-winner among all configs OOS, in (0, 1). Ties on
        # OOS performance count as "at or below", so identical configs read as median.
        rank = int(np.sum(oos_perf <= oos_perf[best]))  # 1..N
        omega = rank / (n_cfg + 1.0)
        if omega <= 0.5:  # λ = ln(ω/(1−ω)) ≤ 0
            below_median += 1
        total += 1
    return below_median / total if total else 0.0
