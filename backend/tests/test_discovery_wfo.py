"""WFO primitives: rolling windows, parameter plateau helper, Monte-Carlo (§6.5)."""

from __future__ import annotations

import numpy as np

from app.discovery.wfo import Window, monte_carlo, rolling_windows

DAY = 86_400_000


def test_rolling_windows_shape_and_step() -> None:
    windows = rolling_windows(0, 100 * DAY, train_days=20, test_days=10, step_days=10)
    assert len(windows) > 0
    for w in windows:
        assert isinstance(w, Window)
        assert w.train_end - w.train_start == 20 * DAY
        assert w.test_end - w.test_start == 10 * DAY
        assert w.test_start == w.train_end  # test immediately follows train
        assert w.test_end <= 100 * DAY  # never runs past the data
    assert windows[1].train_start - windows[0].train_start == 10 * DAY  # step


def test_rolling_windows_too_short_returns_empty() -> None:
    # 24-month note (§4.2): a 6-day span can't hold a 20+10 day window.
    assert rolling_windows(0, 6 * DAY, 20, 10, 10) == []


def test_monte_carlo_deterministic_for_a_seed() -> None:
    rets = np.array([0.1, -0.05, 0.2, -0.1, 0.03, -0.02, 0.05, -0.08])
    a = monte_carlo(rets, runs=300, seed=42)
    b = monte_carlo(rets, runs=300, seed=42)
    assert a == b  # same seed ⇒ identical distribution
    assert a["runs"] == 300
    assert 0.0 <= a["p95_max_drawdown"] <= 1.0
    assert 0.0 <= a["mean_max_drawdown"] <= a["p95_max_drawdown"]


def test_monte_carlo_needs_at_least_two_trades() -> None:
    assert monte_carlo(np.array([0.1]), runs=100, seed=1)["runs"] == 0
    assert monte_carlo(np.zeros(0), runs=100, seed=1)["p95_max_drawdown"] == 0.0
