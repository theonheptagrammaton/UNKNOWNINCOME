"""Regime labelling (doc §8.4): trend/range × low/high + trend-axis matching."""

from __future__ import annotations

import numpy as np

from app.data.parquet_store import ohlcv_rows_to_frame
from app.strategy.regime import RegimeLabel, classify_regime, regime_matches
from fakes import make_ohlcv


def _choppy(count: int, tf: str = "1h") -> list[list[float]]:
    """A flat, oscillating tape (low ADX ⇒ range)."""
    from app.data.timeframes import tf_to_ms

    step = tf_to_ms(tf)
    bars: list[list[float]] = []
    for i in range(count):
        c = 100.0 + (0.4 if i % 2 == 0 else -0.4)  # tiny ±0.4 wiggle, no direction
        bars.append([i * step, c, c + 0.5, c - 0.5, c, 10.0])
    return bars


def test_strong_uptrend_is_trend() -> None:
    # make_ohlcv is a clean monotonic ramp ⇒ ADX should be high.
    frame = ohlcv_rows_to_frame(make_ohlcv(0, 120, "1h"))
    label = classify_regime(frame)
    assert label is not None
    assert label.trend == "trend"
    assert label.adx >= 25.0


def test_choppy_tape_is_range() -> None:
    frame = ohlcv_rows_to_frame(_choppy(120))
    label = classify_regime(frame)
    assert label is not None
    assert label.trend == "range"
    assert label.adx < 25.0


def test_atr_percentile_drives_volatility_bucket() -> None:
    # A ramp with a widening range in the last third ⇒ latest ATR is high-percentile.
    bars = make_ohlcv(0, 90, "1h")
    for i in range(60, 90):
        bars[i][2] += (i - 60) * 2.0  # blow the highs out ⇒ ATR climbs
        bars[i][3] -= (i - 60) * 2.0
    label = classify_regime(ohlcv_rows_to_frame(bars))
    assert label is not None
    assert label.volatility == "high"
    assert 0.0 <= label.atr_percentile <= 1.0


def test_thin_data_returns_none() -> None:
    frame = ohlcv_rows_to_frame(make_ohlcv(0, 5, "1h"))
    assert classify_regime(frame) is None


def test_regime_matches_is_forgiving() -> None:
    # Unlabelled versions always run; matching is trend-axis only.
    assert regime_matches(None, "trend/high") is True
    assert regime_matches("trend/high", None) is True
    assert regime_matches("trend/high", "trend/low") is True  # same trend axis
    assert regime_matches("trend/high", "range/high") is False
    market = RegimeLabel(trend="trend", volatility="low", adx=30.0, atr_percentile=0.2)
    assert regime_matches("trend/high", market) is True
    assert regime_matches("range/low", market) is False


def test_label_string_and_axes() -> None:
    label = RegimeLabel(trend="trend", volatility="high", adx=40.0, atr_percentile=0.9)
    assert label.label == "trend/high"
    assert np.isfinite(label.adx)
