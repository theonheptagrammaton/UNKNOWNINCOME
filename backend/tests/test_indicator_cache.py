"""Cache behaviour (KABUL #3): first compute misses, second hits, new bars bust."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.indicators.compute as compute_mod
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.indicators.compute import cache_path, compute_indicator, params_hash
from app.indicators.registry import get_indicator
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
SYMBOL = "BTCUSDT"
TF = "1h"


def _seed(n: int) -> None:
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(n, TF)))


def test_miss_then_hit(data_dir: Path, caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    _seed(80)
    caplog.set_level("INFO", logger="app.indicators.compute")

    r1 = compute_indicator(MARKET, SYMBOL, TF, "rsi", {"timeperiod": 14})
    phash = params_hash(get_indicator("rsi"), {"timeperiod": 14})
    assert cache_path(MARKET, SYMBOL, TF, "rsi", phash).exists()
    assert any("cache MISS" in m for m in caplog.messages)

    caplog.clear()
    # Spy: the source dispatcher must NOT run on a cache hit.
    calls = {"n": 0}
    original = compute_mod.compute_raw

    def spy(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(compute_mod, "compute_raw", spy)

    r2 = compute_indicator(MARKET, SYMBOL, TF, "rsi", {"timeperiod": 14})
    assert calls["n"] == 0, "cache hit still recomputed"
    assert any("cache HIT" in m for m in caplog.messages)
    assert r1.equals(r2)


def test_different_params_are_separate_entries(data_dir: Path) -> None:
    _seed(80)
    compute_indicator(MARKET, SYMBOL, TF, "rsi", {"timeperiod": 14})
    compute_indicator(MARKET, SYMBOL, TF, "rsi", {"timeperiod": 21})
    h14 = params_hash(get_indicator("rsi"), {"timeperiod": 14})
    h21 = params_hash(get_indicator("rsi"), {"timeperiod": 21})
    assert h14 != h21
    assert cache_path(MARKET, SYMBOL, TF, "rsi", h14).exists()
    assert cache_path(MARKET, SYMBOL, TF, "rsi", h21).exists()


def test_new_bars_invalidate_cache(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _seed(80)
    compute_indicator(MARKET, SYMBOL, TF, "rsi", {"timeperiod": 14})  # warm cache

    _seed(100)  # append 20 fresh bars
    caplog.set_level("INFO", logger="app.indicators.compute")
    res = compute_indicator(MARKET, SYMBOL, TF, "rsi", {"timeperiod": 14})
    assert len(res) == 100
    assert any("cache MISS" in m for m in caplog.messages), "stale cache was served"
