"""Bulk smoke test (KABUL #1): every registry indicator computes error-free."""

from __future__ import annotations

from pathlib import Path

from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.indicators.compute import compute_indicator
from app.indicators.registry import get_registry
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
SYMBOL = "BTCUSDT"
TF = "1h"
N = 400


def _seed_parquet(data_dir: Path) -> None:
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(N, TF)))


def test_all_indicators_compute_on_sample_symbol(data_dir: Path) -> None:
    _seed_parquet(data_dir)
    registry = get_registry()
    failures: list[tuple[str, str]] = []
    for iid, d in registry.items():
        try:
            res = compute_indicator(MARKET, SYMBOL, TF, iid, use_cache=False)
            assert list(res.columns) == ["ts"] + d.outputs, (
                f"{iid}: columns {list(res.columns)} != {['ts'] + d.outputs}"
            )
            assert len(res) == N, f"{iid}: got {len(res)} rows, expected {N}"
        except Exception as exc:  # noqa: BLE001 - collect all failures
            failures.append((iid, f"{type(exc).__name__}: {exc}"))
    assert not failures, f"{len(failures)} indicators failed: {failures[:10]}"
    assert len(registry) >= 200
