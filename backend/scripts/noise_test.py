"""Noise test (Faz 9, doc §23.6) — the phase's single most important criterion.

Generate a **random walk** whose volatility and lag-1 autocorrelation match a real
series, run the **full discovery pipeline** (including the Aşama 5.5 deflation gate)
over it, and assert the result is **zero candidates**. If even one candidate survives,
the pipeline is manufacturing champions from noise — the *pipeline* is broken, not the
gate; do not loosen the gate to make this pass (§23.6, rule #15).

    python -m scripts.noise_test                       # BTCUSDT 1h stats if present, else defaults
    python -m scripts.noise_test --symbol ETHUSDT --tf 4h --bars 4000 --seed 7
    python -m scripts.noise_test --broad               # wider candidate set (slower, more honest)

The random walk has, by construction, **no edge**: any "strategy" that looks good on it
is pure overfitting. A correct pipeline returns nothing. The generator matches the real
series' return σ and AR(1) φ so the noise is *realistic* noise, not a soft target.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.config import settings
from app.data.duckdb_query import query_ohlcv
from app.data.timeframes import tf_to_ms


@dataclass
class SeriesStats:
    sigma: float  # per-bar log-return std
    phi: float  # lag-1 autocorrelation of log returns
    base_price: float
    source: str  # "real:<symbol>" or "default"


# Defaults used when no real series is available — a plausible crypto 1h profile.
_DEFAULT_SIGMA = 0.01
_DEFAULT_PHI = 0.0
_DEFAULT_BASE = 100.0


def measure_stats(market: str, symbol: str, tf: str) -> SeriesStats:
    """Measure σ and AR(1) φ of a real series' log returns (defaults if absent)."""
    df = query_ohlcv(market, symbol, tf)
    if df.empty or len(df) < 50:
        return SeriesStats(_DEFAULT_SIGMA, _DEFAULT_PHI, _DEFAULT_BASE, "default")
    close = df["close"].to_numpy(dtype="float64")
    close = close[close > 0]
    logret = np.diff(np.log(close))
    logret = logret[np.isfinite(logret)]
    if logret.size < 10:
        return SeriesStats(_DEFAULT_SIGMA, _DEFAULT_PHI, _DEFAULT_BASE, "default")
    sigma = float(logret.std(ddof=1))
    # lag-1 autocorrelation
    if logret.size > 1 and sigma > 0:
        phi = float(np.corrcoef(logret[:-1], logret[1:])[0, 1])
    else:
        phi = 0.0
    phi = float(np.clip(phi, -0.95, 0.95))
    return SeriesStats(sigma, phi, float(close[0]), f"real:{symbol}")


def generate_random_walk(
    stats: SeriesStats, n_bars: int, tf: str, seed: int
) -> pd.DataFrame:
    """AR(1) random walk with the measured σ and φ — extended OHLCV (doc §23.6, rule #15).

    Also emits the Faz 11 taker-flow columns as **pure noise** (random aggressive-buy
    share and trade count) so ``flow_imbalance`` is genuinely exercised on the random
    walk — a correct pipeline must still find no edge in them (rule #15).
    """
    rng = np.random.default_rng(seed)
    # Stationary AR(1): var(r) = σ²  ⇒  innovation std = σ·√(1−φ²).
    innov_std = stats.sigma * np.sqrt(max(1e-9, 1.0 - stats.phi**2))
    r = np.empty(n_bars)
    r[0] = rng.normal(0.0, stats.sigma)
    for t in range(1, n_bars):
        r[t] = stats.phi * r[t - 1] + rng.normal(0.0, innov_std)
    close = stats.base_price * np.exp(np.cumsum(r))

    step = tf_to_ms(tf)
    start = 1_600_000_000_000  # fixed UTC anchor → reproducible (rule #6)
    rows: list[list[float]] = []
    for i in range(n_bars):
        c = float(close[i])
        o = c * (1.0 + float(rng.normal(0.0, stats.sigma * 0.2)))
        span = abs(float(rng.normal(0.0, stats.sigma))) * c
        h = max(o, c) + span
        low = max(1e-9, min(o, c) - span)
        v = float(rng.random()) * 1000 + 100
        taker_buy = v * float(rng.uniform(0.3, 0.7))  # noise aggressive-buy share
        num_trades = float(rng.integers(20, 600))
        rows.append([start + i * step, o, h, low, c, v, taker_buy, num_trades])
    return pd.DataFrame(
        rows,
        columns=[
            "ts", "open", "high", "low", "close", "volume",
            "taker_buy_base_volume", "number_of_trades",
        ],
    )


# The four Faz 11 primitives plus the volatility exits a valid combo needs — the
# candidate set for the alpha noise run (§25.5: new data is not gate-exempt).
ALPHA_SCAN_IDS = (
    "flow_imbalance", "liq_cascade",       # momentum → trigger
    "oi_divergence", "funding_extreme",    # volume / statistic → filter
    "atr", "natr", "bbands",               # volatility → exit
)


def write_alpha_inputs(
    market: str, symbol: str, tf: str, n_bars: int, seed: int
) -> None:
    """Write pure-noise OI, funding and liquidation streams for a symbol (§25.5).

    So ``oi_divergence``, ``funding_extreme`` and ``liq_cascade`` are exercised on the
    random walk too. Everything is noise by construction — a correct pipeline returns
    zero candidates regardless.
    """
    from app.data.parquet_store import (
        LIQUIDATION_COLUMNS,
        OPEN_INTEREST_COLUMNS,
        write_funding,
        write_liquidation_bars,
        write_open_interest,
    )
    from app.data.timeframes import FUNDING_INTERVAL_MS

    rng = np.random.default_rng(seed)
    step = tf_to_ms(tf)
    start = 1_600_000_000_000
    ts = np.array([start + i * step for i in range(n_bars)], dtype="int64")

    oi = 1_000_000.0 + np.cumsum(rng.standard_normal(n_bars)) * 5_000.0
    write_open_interest(
        market, symbol,
        pd.DataFrame(
            {"ts": ts, "open_interest": np.abs(oi) + 1.0, "open_interest_value": np.nan},
            columns=OPEN_INTEREST_COLUMNS,
        ),
    )

    f_ts = np.arange(ts[0], ts[-1] + 1, FUNDING_INTERVAL_MS, dtype="int64")
    write_funding(
        market, symbol,
        pd.DataFrame({"ts": f_ts, "funding_rate": rng.normal(0.0, 3e-4, len(f_ts))}),
    )

    # Liquidation bursts scattered as noise on ~10% of bars.
    hit = rng.random(n_bars) < 0.1
    write_liquidation_bars(
        market, symbol,
        pd.DataFrame(
            {
                "ts": ts,
                "liq_buy_notional": np.where(hit, rng.uniform(0, 5e5, n_bars), 0.0),
                "liq_sell_notional": np.where(hit, rng.uniform(0, 5e5, n_bars), 0.0),
            },
            columns=LIQUIDATION_COLUMNS,
        ),
    )


def _alpha_scan_config(symbols: list[str], tf: str, seed: int):
    """A small-budget scan whose candidates are the four Faz 11 primitives (§25.5)."""
    from app.discovery.config import (
        CandidateSelection,
        FinalistConfig,
        ScanConfig,
        WFOConfig,
    )

    return ScanConfig(
        symbols=symbols,
        timeframes=[tf],
        seed=seed,
        fast_mode=False,  # keep our explicit candidate ids (fast_mode overrides them)
        candidate=CandidateSelection(mode="ids", ids=list(ALPHA_SCAN_IDS)),
        combo_pool_per_role=3,
        top_n_combos=6,
        optuna_trials=8,
        monte_carlo_runs=100,
        wfo=WFOConfig(train_days=20, test_days=10, step_days=10),
        finalist=FinalistConfig(enabled=True, top_k=3),
    )


def run_noise_scan(
    symbols: list[str], tf: str, bars: int, seed: int, broad: bool, alpha: bool = False
) -> int:
    """Write random-walk parquet to an isolated store, run the full pipeline, count candidates."""
    from app.data.parquet_store import write_ohlcv
    from app.discovery.config import ScanConfig
    from app.discovery.pipeline import run_scan

    market = settings.market
    label = "Faz 11 alpha primitives" if alpha else "Faz 9"
    print(f"{label} — noise test · {len(symbols)} symbol(s) × {tf} · {bars} bars · seed {seed}")
    stats = measure_stats(market, symbols[0], tf)
    print(
        f"  matched stats [{stats.source}]: σ={stats.sigma:.5f}  φ={stats.phi:+.3f}  "
        f"base={stats.base_price:.2f}"
    )

    real_data_dir = settings.data_dir
    with tempfile.TemporaryDirectory(prefix="noise_test_") as tmp:
        settings.data_dir = tmp  # isolate: pipeline reads the synthetic store only
        try:
            for si, symbol in enumerate(symbols):
                frame = generate_random_walk(stats, bars, tf, seed + si)
                write_ohlcv(market, symbol, tf, frame)
                if alpha:
                    write_alpha_inputs(market, symbol, tf, bars, seed + si)

            if alpha:
                config = _alpha_scan_config(symbols, tf, seed)
            else:
                config = ScanConfig(
                    symbols=symbols,
                    timeframes=[tf],
                    fast_mode=not broad,  # broad = wider candidate set, slower, more honest
                    seed=seed,
                )
            result = run_scan(config, symbols)
        finally:
            settings.data_dir = real_data_dir

    survivors = [e for e in result.leaderboard if e.get("survived")]
    print(
        f"  pipeline: {result.combos_tried} combos tried, "
        f"{len(result.leaderboard)} finalists, {len(survivors)} candidate(s) after gate"
    )
    if survivors:
        print("\n  ✗ FAIL — noise produced candidates (§23.6). Fix the PIPELINE, not the gate:")
        for e in survivors[:10]:
            print(
                f"    {e['combo']['trigger']}+{e['combo']['filter']}+{e['combo']['exit']}"
                f"@{e['symbol']}:{e['tf']}  DSR={e.get('dsr')}  PBO={e.get('pbo')}"
            )
        return 1

    # Show why the closest finalists were rejected — evidence the gate engaged.
    print("\n  ✓ PASS — zero candidates from noise.")
    gated = [e for e in result.leaderboard if e.get("gate_reasons")]
    for e in gated[:5]:
        print(
            f"    rejected {e['combo']['trigger']}+{e['combo']['filter']}+{e['combo']['exit']}"
            f": {' · '.join(e['gate_reasons'])}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Faz 9 noise test (doc §23.6)")
    parser.add_argument("--symbol", default="BTCUSDT", help="reference symbol for stats")
    parser.add_argument("--symbols", nargs="*", help="explicit synthetic universe")
    parser.add_argument("--tf", default="1h")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--broad", action="store_true", help="wider candidate set (slower)")
    parser.add_argument(
        "--alpha", action="store_true",
        help="run the Faz 11 alpha primitives over noise (incl. OI/funding/liquidations)",
    )
    args = parser.parse_args()

    symbols = args.symbols or [args.symbol, "NOISE2USDT", "NOISE3USDT"]
    return run_noise_scan(symbols, args.tf, args.bars, args.seed, args.broad, alpha=args.alpha)


if __name__ == "__main__":
    sys.exit(main())
