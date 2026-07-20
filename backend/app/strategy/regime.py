"""Regime labelling — the simple-but-effective awareness layer (doc §8.4).

The market is tagged on two axes with two cheap, well-understood indicators:

* **trend vs range** — Wilder's ADX. ADX ≥ ``adx_trend_threshold`` ⇒ a directional
  regime is present ("trend"); below it the tape is choppy ("range").
* **low vs high volatility** — the ATR's *percentile rank* over a rolling lookback.
  Rank ≥ ``atr_high_pct`` ⇒ "high" volatility, else "low". A percentile (not an
  absolute ATR) keeps the split asset- and price-agnostic (pazarlıksız rule #8).

Strategies are stored with the regime they suit; the bot runs the pool matching the
*current* regime (manual lock always possible — see the bot's regime gate). Both the
ADX and the ATR are pure NumPy (Wilder's RMA), so this layer has **no TA-Lib
dependency** and is deterministic + unit-testable on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.backtest.engine import _atr

# Axis vocabularies (kept tiny + stable — they end up in DB + UI).
TREND, RANGE = "trend", "range"
LOW, HIGH = "low", "high"


@dataclass(frozen=True)
class RegimeLabel:
    """A market-regime verdict on the two §8.4 axes."""

    trend: str  # "trend" | "range"
    volatility: str  # "low" | "high"
    adx: float
    atr_percentile: float  # rank of the latest ATR in [0, 1]

    @property
    def label(self) -> str:
        """Compact tag stored on a version, e.g. ``"trend/high"``."""
        return f"{self.trend}/{self.volatility}"

    def matches(self, other: RegimeLabel | str | None) -> bool:
        """Whether a version tagged ``self`` should run in the ``other`` market regime.

        Matching is on the **trend axis only** — the forgiving choice (§8.4): a
        strategy is admitted when its trend axis agrees with the market, regardless
        of the volatility bucket, so a slightly noisier tape doesn't starve the pool.
        """
        if other is None:
            return True
        trend = other.trend if isinstance(other, RegimeLabel) else str(other).split("/", 1)[0]
        return self.trend == trend


def regime_matches(version_regime: str | None, target: RegimeLabel | str | None) -> bool:
    """Whether a version tagged ``version_regime`` may run in the ``target`` regime.

    Forgiving on purpose (doc §8.4): unlabelled versions always run, and matching is
    on the trend axis only so a differing volatility bucket doesn't starve the pool.
    """
    if version_regime is None or target is None:
        return True
    v_trend = version_regime.split("/", 1)[0]
    t_trend = target.trend if isinstance(target, RegimeLabel) else str(target).split("/", 1)[0]
    return v_trend == t_trend


def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """Wilder's ADX (pure NumPy, no TA-Lib). NaN until it warms up (~2·length bars)."""
    n = len(close)
    adx = np.full(n, np.nan)
    if n < 2:
        return adx

    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = np.empty(n - 1)
    for i in range(1, n):
        tr[i - 1] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    def _rma(x: np.ndarray) -> np.ndarray:
        """Wilder's running moving average, seeded with the first ``length`` sum."""
        out = np.full(len(x), np.nan)
        if len(x) < length:
            return out
        out[length - 1] = x[:length].sum()
        for i in range(length, len(x)):
            out[i] = out[i - 1] - out[i - 1] / length + x[i]
        return out

    tr_s = _rma(tr)
    plus_s = _rma(plus_dm)
    minus_s = _rma(minus_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * np.where(tr_s > 0, plus_s / tr_s, np.nan)
        minus_di = 100.0 * np.where(tr_s > 0, minus_s / tr_s, np.nan)
        dx = 100.0 * np.abs(plus_di - minus_di) / np.where(
            (plus_di + minus_di) > 0, plus_di + minus_di, np.nan
        )
    # ADX is Wilder's RMA (as an average, not a sum) of DX over ``length``.
    dx = np.nan_to_num(dx, nan=0.0)
    start = 2 * length - 1
    if n - 1 <= start:
        return adx  # not enough bars to seed the ADX average
    # Map DX index (offset by 1 from bars) back onto the bar axis.
    adx_line = np.full(n - 1, np.nan)
    adx_line[start] = dx[length - 1 : start + 1].mean()
    for i in range(start + 1, n - 1):
        adx_line[i] = (adx_line[i - 1] * (length - 1) + dx[i]) / length
    adx[1:] = adx_line
    return adx


def _percentile_rank(series: np.ndarray, value: float) -> float:
    """Fraction of finite ``series`` values ≤ ``value`` (∈ [0, 1])."""
    finite = series[np.isfinite(series)]
    if len(finite) == 0 or not np.isfinite(value):
        return 0.0
    return float((finite <= value).mean())


def classify_regime(
    ohlcv: pd.DataFrame,
    *,
    adx_period: int = 14,
    adx_trend_threshold: float = 25.0,
    atr_period: int = 14,
    atr_high_pct: float = 0.5,
    lookback: int = 200,
) -> RegimeLabel | None:
    """Label the *latest* bar's regime (doc §8.4). ``None`` when data is too thin.

    ``lookback`` bounds the ATR-percentile window so the volatility bucket reflects
    the recent regime, not the whole history.
    """
    need = max(2 * adx_period + 1, atr_period + 1)
    if ohlcv is None or len(ohlcv) < need:
        return None

    high = ohlcv["high"].to_numpy("float64")
    low = ohlcv["low"].to_numpy("float64")
    close = ohlcv["close"].to_numpy("float64")

    adx_line = _adx(high, low, close, adx_period)
    adx_val = float(adx_line[-1]) if np.isfinite(adx_line[-1]) else 0.0

    atr_line = _atr(high, low, close, atr_period)
    window = atr_line[-lookback:] if lookback and lookback > 0 else atr_line
    atr_val = float(atr_line[-1]) if np.isfinite(atr_line[-1]) else float("nan")
    rank = _percentile_rank(window, atr_val)

    trend = TREND if adx_val >= adx_trend_threshold else RANGE
    volatility = HIGH if rank >= atr_high_pct else LOW
    return RegimeLabel(trend=trend, volatility=volatility, adx=adx_val, atr_percentile=rank)
