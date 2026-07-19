"""Fast-mode discovery pipeline: end-to-end completion + seed determinism (§7, §15)."""

from __future__ import annotations

from pathlib import Path

from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.discovery.config import ScanConfig
from app.discovery.pipeline import run_scan
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
TF = "1h"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def _seed(data_dir: Path) -> None:
    for i, symbol in enumerate(SYMBOLS):
        rows = make_wave_ohlcv(1000, TF, seed=100 + i, base_price=100.0 + 10 * i)
        write_ohlcv(MARKET, symbol, TF, ohlcv_rows_to_frame(rows))


def _ranking(result) -> list[tuple]:
    return [
        (e["combo"]["trigger"], e["combo"]["filter"], e["combo"]["exit"], e["symbol"], e["tf"])
        for e in result.leaderboard
    ]


def test_fast_mode_scan_completes_end_to_end(data_dir: Path) -> None:
    _seed(data_dir)
    config = ScanConfig(symbols=SYMBOLS, timeframes=[TF], fast_mode=True, seed=7)
    result = run_scan(config, SYMBOLS)

    assert result.leaderboard, "leaderboard should not be empty"
    assert result.combos_tried > 0
    assert result.universe == SYMBOLS[:2]  # fast mode trims the universe
    # Every stage ran and left its fingerprint on each entry.
    top = result.leaderboard[0]
    assert top["genome"]["indicators"], "combo genome carries its indicators"
    assert top["wfo_layers"], "walk-forward produced OOS layers"
    assert "p95_max_drawdown" in top["monte_carlo"]
    assert top["status"] in ("candidate", "finalist")
    assert top["rank"] == 1
    # Per-stage timings are logged for the <2h budget measurement.
    assert set(result.stage_timings) >= {
        "stage1_single_scan", "stage2_correlation", "stage3_combination",
        "stage4_5_optimize_wfo", "stage6_finalist",
    }


def test_same_seed_same_leaderboard_ranking(data_dir: Path) -> None:
    _seed(data_dir)
    config = ScanConfig(symbols=SYMBOLS, timeframes=[TF], fast_mode=True, seed=7)
    r1 = run_scan(config, SYMBOLS)
    r2 = run_scan(config, SYMBOLS)

    assert _ranking(r1) == _ranking(r2)  # KABUL: aynı seed → aynı sıralama
    assert [round(e["oos_score"], 9) for e in r1.leaderboard] == \
           [round(e["oos_score"], 9) for e in r2.leaderboard]
    assert r1.combos_tried == r2.combos_tried
