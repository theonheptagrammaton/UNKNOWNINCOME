"""Stage 2 — correlation elimination collapses redundant signals (§7 Aşama 2)."""

from __future__ import annotations

import numpy as np

from app.discovery.correlation import ClusterItem, eliminate_correlated, signal_correlation


def test_identical_signals_collapse_to_best_scored() -> None:
    n = 120
    base = (np.arange(n) % 5 == 0).astype(float)
    items = [
        ClusterItem("rsi", score=0.9, vector=base.copy()),
        ClusterItem("stochrsi", score=0.5, vector=base.copy()),  # same info → absorbed
        ClusterItem("willr", score=0.7, vector=(np.arange(n) % 7 == 0).astype(float)),
    ]
    res = eliminate_correlated(items, threshold=0.85)
    keys = {it.key for it in res.survivors}
    assert "rsi" in keys  # highest-scored representative survives
    assert "stochrsi" not in keys  # its duplicate is absorbed
    assert "willr" in keys  # genuinely different signal kept
    assert "stochrsi" in res.clusters["rsi"]


def test_uncorrelated_signals_all_survive() -> None:
    rng = np.random.default_rng(0)
    items = [
        ClusterItem(k, score=s, vector=rng.random(200))
        for k, s in (("x", 0.1), ("y", 0.2), ("z", 0.3))
    ]
    res = eliminate_correlated(items, threshold=0.85)
    assert len(res.survivors) == 3


def test_flat_series_correlation_is_zero() -> None:
    # A never-firing signal must not collapse everything into one cluster.
    assert signal_correlation(np.zeros(10), np.ones(10)) == 0.0
    assert signal_correlation(np.zeros(10), np.zeros(10)) == 0.0
