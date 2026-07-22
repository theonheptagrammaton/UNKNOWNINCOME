"""The noise test as CI (Faz 9, doc §23.6) — the phase's key acceptance criterion.

A random walk has no edge by construction. The full discovery pipeline — single scan →
correlation → combination → Optuna → WFO → **Aşama 5.5 deflation gate** — must return
**zero candidates** over it. One survivor means the pipeline manufactures champions from
noise; the phase does not close (§23.6, rule #15). This runs the *real* generator from
``scripts.noise_test`` so the shipped operator tool and the CI guard cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from scripts.noise_test import (
    SeriesStats,
    _alpha_scan_config,
    generate_random_walk,
    write_alpha_inputs,
)

from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.discovery.config import ScanConfig
from app.discovery.pipeline import run_scan

MARKET = "binance_usdm"
TF = "1h"
SYMBOLS = ["NOISE1USDT", "NOISE2USDT", "NOISE3USDT"]


def _seed_random_walks(seed: int = 42, bars: int = 1500) -> None:
    """Write realistic-noise random walks (matched σ, AR(1) φ) to the isolated store."""
    stats = SeriesStats(sigma=0.012, phi=0.02, base_price=100.0, source="default")
    for i, symbol in enumerate(SYMBOLS):
        frame = generate_random_walk(stats, bars, TF, seed + i)
        rows = [[float(x) for x in r] for r in frame.to_numpy()]
        write_ohlcv(MARKET, symbol, TF, ohlcv_rows_to_frame(rows))


def test_noise_yields_zero_candidates(data_dir: Path) -> None:
    """KABUL (§23.6): the discovery pipeline finds no candidate in a random walk."""
    _seed_random_walks()
    config = ScanConfig(symbols=SYMBOLS, timeframes=[TF], fast_mode=True, seed=42)
    result = run_scan(config, SYMBOLS)

    survivors = [e for e in result.leaderboard if e.get("survived")]
    assert survivors == [], (
        "noise produced candidates — fix the PIPELINE, not the gate (§23.6): "
        + ", ".join(
            f"{e['combo']['trigger']}+{e['combo']['filter']}+{e['combo']['exit']}"
            f"(DSR={e.get('dsr')},PBO={e.get('pbo')})"
            for e in survivors
        )
    )
    # Every finalist carries the gate verdict, and at least one was actively rejected —
    # evidence the gate ran rather than the pipeline simply finding nothing.
    assert result.leaderboard, "expected finalists to exist (and be rejected)"
    assert all("gate_passed" in e for e in result.leaderboard)
    assert any(e.get("gate_reasons") for e in result.leaderboard)


def test_alpha_primitives_over_noise_yield_zero_candidates(data_dir: Path) -> None:
    """KABUL (§25.5, rule #15): the four Faz 11 primitives find no edge in noise.

    New data is **not** gate-exempt. We seed the random walk *plus* pure-noise taker
    flow, open interest, funding and liquidations, then run a scan whose candidate set
    is the four alpha primitives (+ volatility exits). A correct pipeline returns zero
    candidates and the gate must have actively rejected the primitive-built combos.
    """
    symbols = SYMBOLS[:2]
    for i, symbol in enumerate(symbols):
        frame = generate_random_walk(
            SeriesStats(sigma=0.012, phi=0.02, base_price=100.0, source="default"),
            1500, TF, 42 + i,
        )
        write_ohlcv(MARKET, symbol, TF, frame)
        write_alpha_inputs(MARKET, symbol, TF, 1500, 42 + i)

    config = _alpha_scan_config(symbols, TF, seed=42)
    result = run_scan(config, symbols)

    survivors = [e for e in result.leaderboard if e.get("survived")]
    assert survivors == [], (
        "alpha primitives produced candidates from noise — fix the PIPELINE, not the "
        "gate (§25.5): "
        + ", ".join(
            f"{e['combo']['trigger']}+{e['combo']['filter']}+{e['combo']['exit']}"
            for e in survivors
        )
    )
    # The primitives really were combined and gated (not silently absent).
    combo_ids = {
        role_id
        for e in result.leaderboard
        for role_id in (e["combo"]["trigger"], e["combo"]["filter"], e["combo"]["exit"])
    }
    assert combo_ids & {"flow_imbalance", "liq_cascade", "oi_divergence", "funding_extreme"}
    assert any(e.get("gate_reasons") for e in result.leaderboard)


def test_noise_gate_fields_present_on_every_row(data_dir: Path) -> None:
    """Each leaderboard row exposes DSR · PBO · trials_total · B&H diff (§23.6 UI bullet)."""
    _seed_random_walks(seed=7)
    config = ScanConfig(symbols=SYMBOLS, timeframes=[TF], fast_mode=True, seed=7)
    result = run_scan(config, SYMBOLS)
    for e in result.leaderboard:
        assert e["dsr"] is not None
        assert e["trials_total"] is not None and e["trials_total"] >= result.combos_tried
        assert "pbo" in e and "bh_excess" in e
        assert e["raw_sharpe"] is not None or e["oos_trades"] == 0
