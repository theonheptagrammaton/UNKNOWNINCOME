"""WFO primitives: rolling windows, parameter plateau helper, Monte-Carlo (§6.5)."""

from __future__ import annotations

import numpy as np

from app.discovery.wfo import Window, evaluate_survival, monte_carlo, rolling_windows

DAY = 86_400_000


def _survives(**kw) -> bool:
    base = dict(
        oos_score=0.6, oos_mean_net=0.15, oos_trades=20, is_score=1.0,
        plateau_ok=True, passes_hard_filters=True,
        min_oos_is_ratio=0.5, min_oos_trades=10,
    )
    base.update(kw)
    return evaluate_survival(**base)


def test_survival_requires_genuine_oos() -> None:
    # Baseline: profitable OOS, keeps ≥50% of the IS score, enough trades ⇒ survives.
    assert _survives()
    # Overfit: great in-sample (is_score=1.0) but the OOS score collapsed ⇒ rejected.
    assert not _survives(oos_score=0.1)
    # OOS not actually profitable ⇒ rejected (the old gate let oos_score>0 through).
    assert not _survives(oos_mean_net=-0.01)
    # Too few OOS trades ⇒ noise, not evidence ⇒ rejected.
    assert not _survives(oos_trades=5)
    # Plateau / hard-filter failures still veto.
    assert not _survives(plateau_ok=False)
    assert not _survives(passes_hard_filters=False)


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
