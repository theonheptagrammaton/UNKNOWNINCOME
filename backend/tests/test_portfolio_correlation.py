"""Strateji getiri korelasyonu — getiri serisi, equity değil (doc §24.2)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.portfolio.correlation import (
    correlation_matrix,
    daily_returns,
    max_abs_correlation,
    return_matrix,
)

DAY = 24 * 3600 * 1000


def test_daily_returns_normalise_by_capital_not_equity_level() -> None:
    """Getiri = günlük PnL / sermaye (equity seviyesi değil, doc §24.2)."""
    pnl = [(1 * DAY, 100.0), (1 * DAY, 50.0), (2 * DAY, -30.0)]
    r = daily_returns(pnl, capital=10_000.0)
    assert r.iloc[0] == pytest.approx(150.0 / 10_000)  # aynı gün toplanır
    assert r.iloc[1] == pytest.approx(-30.0 / 10_000)
    # Farklı sermaye ⇒ farklı ölçek (equity seviyesi değil, oran).
    r2 = daily_returns(pnl, capital=20_000.0)
    assert r2.iloc[0] == pytest.approx(150.0 / 20_000)


def test_empty_or_zero_capital_is_safe() -> None:
    assert daily_returns([], 10_000.0).empty
    assert daily_returns([(DAY, 10.0)], 0.0).empty


def test_correlation_matrix_perfect_and_anti() -> None:
    idx = pd.to_datetime([1, 2, 3, 4], unit="D")
    a = pd.Series([0.01, -0.02, 0.03, -0.01], index=idx)
    mat = return_matrix({"A": a, "B": a, "C": -a})
    corr = correlation_matrix(mat)
    assert corr.at["A", "B"] == pytest.approx(1.0)
    assert corr.at["A", "C"] == pytest.approx(-1.0)
    assert corr.at["A", "A"] == pytest.approx(1.0)


def test_constant_series_correlation_is_zero_not_nan() -> None:
    """Sabit (sıfır varyans) seri ⇒ korelasyon 0'a çekilir, NaN değil (kapı yanlış
    ateşlemez)."""
    idx = pd.to_datetime([1, 2, 3], unit="D")
    a = pd.Series([0.01, 0.02, -0.01], index=idx)
    flat = pd.Series([0.0, 0.0, 0.0], index=idx)
    corr = correlation_matrix(return_matrix({"A": a, "FLAT": flat}))
    assert corr.at["A", "FLAT"] == 0.0


def test_max_abs_correlation_picks_the_worst() -> None:
    idx = pd.to_datetime([1, 2, 3, 4], unit="D")
    a = pd.Series([0.01, -0.02, 0.03, -0.01], index=idx)
    b = pd.Series([0.01, -0.019, 0.028, -0.011], index=idx)  # A ile çok korele
    c = pd.Series([-0.01, 0.005, -0.02, 0.03], index=idx)  # zayıf
    corr = correlation_matrix(return_matrix({"A": a, "B": b, "C": c}))
    peer, rho = max_abs_correlation("A", corr, ["B", "C"])
    assert peer == "B"
    assert rho > 0.9
