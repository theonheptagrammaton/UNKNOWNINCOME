"""Custom plugin loader: the zscore example loads and computes correctly."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.data.parquet_store import ohlcv_rows_to_frame, read_ohlcv, write_ohlcv
from app.indicators.compute import compute_indicator
from app.indicators.loader import load_custom_defs
from fakes import make_wave_ohlcv


def test_custom_defs_loaded() -> None:
    defs = {d.id: d for d in load_custom_defs()}
    assert "zscore" in defs
    d = defs["zscore"]
    assert d.source == "custom"
    assert d.category == "statistic"
    assert d.inputs == ["close"]
    assert d.outputs == ["zscore"]
    assert d.params["length"].default == 20.0


def test_custom_compute_matches_manual(data_dir: Path) -> None:
    write_ohlcv(
        "binance_usdm", "SOLUSDT", "1h", ohlcv_rows_to_frame(make_wave_ohlcv(90, "1h"))
    )
    close = read_ohlcv("binance_usdm", "SOLUSDT", "1h")["close"]
    res = compute_indicator("binance_usdm", "SOLUSDT", "1h", "zscore", {"length": 15})

    mean = close.rolling(15).mean()
    std = close.rolling(15).std(ddof=0)
    expected = ((close - mean) / std).to_numpy()

    got = res["zscore"].to_numpy()
    mask = np.isfinite(got) & np.isfinite(expected)
    assert mask.any()
    np.testing.assert_allclose(got[mask], expected[mask], atol=1e-9)
    # warmup NaNs align
    assert bool((pd.isna(got) == pd.isna(expected)).all())
