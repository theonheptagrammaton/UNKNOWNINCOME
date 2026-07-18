"""Reference-value tests (KABUL #2): ≥10 core indicators vs independent maths.

Each expected series is computed by a second, independent implementation (pure
numpy/pandas) — not by the library under test — so this proves the registry →
compute → source pipeline returns mathematically correct numbers, not merely
that a library agrees with itself.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.data.parquet_store import ohlcv_rows_to_frame, read_ohlcv, write_ohlcv
from app.indicators.compute import compute_indicator
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
SYMBOL = "ETHUSDT"
TF = "1h"
N = 120


@pytest.fixture
def seeded(data_dir: Path) -> pd.DataFrame:
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(N, TF, seed=11)))
    return read_ohlcv(MARKET, SYMBOL, TF)


def _assert_matches(got: pd.Series, ref: np.ndarray) -> None:
    a = got.to_numpy(dtype="float64")
    b = np.asarray(ref, dtype="float64")
    assert (np.isfinite(a) == np.isfinite(b)).all(), "NaN warmup masks differ"
    mask = np.isfinite(a) & np.isfinite(b)
    assert mask.any(), "no finite values to compare"
    np.testing.assert_allclose(a[mask], b[mask], atol=1e-6)


# ── Independent reference implementations ────────────────────────────────────
def _sma(c: np.ndarray, p: int) -> np.ndarray:
    return pd.Series(c).rolling(p).mean().to_numpy()


def _stddev(c: np.ndarray, p: int) -> np.ndarray:
    return pd.Series(c).rolling(p).std(ddof=0).to_numpy()


def _ema(c: np.ndarray, p: int) -> np.ndarray:
    k = 2 / (p + 1)
    out = np.full(len(c), np.nan)
    out[p - 1] = c[:p].mean()
    for i in range(p, len(c)):
        out[i] = c[i] * k + out[i - 1] * (1 - k)
    return out


def _wma(c: np.ndarray, p: int) -> np.ndarray:
    w = np.arange(1, p + 1)
    return pd.Series(c).rolling(p).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).to_numpy()


def _rsi(c: np.ndarray, p: int) -> np.ndarray:
    d = np.diff(c)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = np.full(len(c), np.nan)
    al = np.full(len(c), np.nan)
    ag[p], al[p] = gain[:p].mean(), loss[:p].mean()
    for i in range(p + 1, len(c)):
        ag[i] = (ag[i - 1] * (p - 1) + gain[i - 1]) / p
        al[i] = (al[i - 1] * (p - 1) + loss[i - 1]) / p
    rs = ag / al
    return 100 - 100 / (1 + rs)


def _atr(h: np.ndarray, low: np.ndarray, c: np.ndarray, p: int) -> np.ndarray:
    tr = np.empty(len(c))
    tr[0] = h[0] - low[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - low[i], abs(h[i] - c[i - 1]), abs(low[i] - c[i - 1]))
    out = np.full(len(c), np.nan)
    out[p] = tr[1 : p + 1].mean()
    for i in range(p + 1, len(c)):
        out[i] = (out[i - 1] * (p - 1) + tr[i]) / p
    return out


def _roc(c: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    out[p:] = (c[p:] / c[:-p] - 1) * 100
    return out


def _mom(c: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    out[p:] = c[p:] - c[:-p]
    return out


def _willr(h: np.ndarray, low: np.ndarray, c: np.ndarray, p: int) -> np.ndarray:
    hh = pd.Series(h).rolling(p).max()
    ll = pd.Series(low).rolling(p).min()
    return (-100 * (hh - pd.Series(c)) / (hh - ll)).to_numpy()


def _obv(c: np.ndarray, v: np.ndarray) -> np.ndarray:
    out = np.empty(len(c))
    out[0] = v[0]
    for i in range(1, len(c)):
        step = v[i] if c[i] > c[i - 1] else (-v[i] if c[i] < c[i - 1] else 0.0)
        out[i] = out[i - 1] + step
    return out


def _zscore(c: np.ndarray, p: int) -> np.ndarray:
    s = pd.Series(c)
    return ((s - s.rolling(p).mean()) / s.rolling(p).std(ddof=0)).to_numpy()


# ── Tests ────────────────────────────────────────────────────────────────────
def _compute(iid: str, params: dict) -> pd.DataFrame:
    return compute_indicator(MARKET, SYMBOL, TF, iid, params)


def test_sma_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("sma", {"timeperiod": 5})["sma"], _sma(c, 5))


def test_ema_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("ema", {"timeperiod": 10})["ema"], _ema(c, 10))


def test_wma_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("wma", {"timeperiod": 5})["wma"], _wma(c, 5))


def test_rsi_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("rsi", {"timeperiod": 14})["rsi"], _rsi(c, 14))


def test_atr_reference(seeded: pd.DataFrame) -> None:
    h, low, c = (seeded[k].to_numpy() for k in ("high", "low", "close"))
    _assert_matches(_compute("atr", {"timeperiod": 14})["atr"], _atr(h, low, c, 14))


def test_roc_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("roc", {"timeperiod": 10})["roc"], _roc(c, 10))


def test_mom_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("mom", {"timeperiod": 10})["mom"], _mom(c, 10))


def test_willr_reference(seeded: pd.DataFrame) -> None:
    h, low, c = (seeded[k].to_numpy() for k in ("high", "low", "close"))
    _assert_matches(_compute("willr", {"timeperiod": 14})["willr"], _willr(h, low, c, 14))


def test_obv_reference(seeded: pd.DataFrame) -> None:
    c, v = seeded["close"].to_numpy(), seeded["volume"].to_numpy()
    _assert_matches(_compute("obv", {})["obv"], _obv(c, v))


def test_stddev_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("stddev", {"timeperiod": 5})["stddev"], _stddev(c, 5))


def test_bbands_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    res = _compute("bbands", {"timeperiod": 20, "nbdevup": 2.0, "nbdevdn": 2.0, "matype": 0})
    _assert_matches(res["middleband"], _sma(c, 20))
    _assert_matches(res["upperband"], _sma(c, 20) + 2.0 * _stddev(c, 20))
    _assert_matches(res["lowerband"], _sma(c, 20) - 2.0 * _stddev(c, 20))


def test_custom_zscore_reference(seeded: pd.DataFrame) -> None:
    c = seeded["close"].to_numpy()
    _assert_matches(_compute("zscore", {"length": 20})["zscore"], _zscore(c, 20))
