"""Reality check (Faz 8, doc §22): re-run the Phase 1–7 acceptance on REAL data.

One command that measures — against whatever is actually in the Parquet store and the
database — the acceptance criteria that only mean something with real market data, and
prints a table. It is deliberately honest: a check that cannot run (no data, no DB)
reports **SKIP**/**ERROR**, never a fake pass (rule #13: synthetic numbers close no box).

    python -m scripts.reality_check                       # data + logic checks
    python -m scripts.reality_check --symbol BTCUSDT --tf 1h
    python -m scripts.reality_check --with-scan           # + real 10×4 scan timing

The headline real numbers (24-month gaps=0, real 10×4 scan time, testnet round trip,
72 h soak) are produced on the server; this script is the operator's one-shot verifier.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass

# Pure-logic acceptance tests (data-independent guarantees) grouped by phase. Re-running
# them here proves the Phase 5–7 kill-switch/gate/leak/risk criteria still hold.
LOGIC_SUITE = {
    "Faz 5 kill switch + risk wall": [
        "tests/test_bot_killswitch.py", "tests/test_execution_risk.py",
    ],
    "Faz 6 unapproved never trades": ["tests/test_strategy_reoptimize.py"],
    "Faz 7 gate + key vault + leak": [
        "tests/test_promotion_gate.py", "tests/test_secrets.py",
    ],
}


@dataclass
class Row:
    phase: str
    criterion: str
    real_value: str
    verdict: str  # PASS | FAIL | SKIP | ERROR


def _fmt_table(rows: list[Row]) -> str:
    w_phase = max((len(r.phase) for r in rows), default=5)
    w_crit = max((len(r.criterion) for r in rows), default=9)
    w_val = max((len(r.real_value) for r in rows), default=10)
    lines = [
        f"{'phase':<{w_phase}}  {'criterion':<{w_crit}}  {'real value':<{w_val}}  verdict",
        f"{'─' * w_phase}  {'─' * w_crit}  {'─' * w_val}  ───────",
    ]
    for r in rows:
        lines.append(
            f"{r.phase:<{w_phase}}  {r.criterion:<{w_crit}}  {r.real_value:<{w_val}}  {r.verdict}"
        )
    return "\n".join(lines)


async def _check_data_status(rows: list[Row]) -> None:
    """Faz 1: gaps=0 and total_missing=0 across every stored series."""
    try:
        from sqlalchemy import select

        from app.core.db import SessionLocal, init_models
        from app.data.gaps import count_missing
        from app.models.market import CandleSyncState

        await init_models()
        async with SessionLocal() as session:
            series = (await session.execute(select(CandleSyncState))).scalars().all()
    except Exception as exc:  # noqa: BLE001
        rows.append(Row("Faz 1", "data/status gaps=0", f"DB error: {exc}"[:40], "ERROR"))
        return
    if not series:
        rows.append(Row("Faz 1", "data/status gaps=0", "no series in DB", "SKIP"))
        return
    total_gaps = sum(len(s.gaps or []) for s in series)
    total_missing = sum(count_missing(s.gaps or [], s.tf) for s in series)
    verdict = "PASS" if total_gaps == 0 and total_missing == 0 else "FAIL"
    rows.append(Row(
        "Faz 1", "data/status gaps=0",
        f"{len(series)} series, gaps={total_gaps}, missing={total_missing}", verdict,
    ))


async def _check_duckdb_speed(rows: list[Row], symbol: str, tf: str) -> None:
    """Faz 1: a typical DuckDB range query returns in < 1 s."""
    try:
        from app.core.config import settings
        from app.data.duckdb_query import count_ohlcv, query_ohlcv

        n = count_ohlcv(settings.market, symbol, tf)
        if n < 2:
            rows.append(Row("Faz 1", "DuckDB query <1s", f"no data {symbol}/{tf}", "SKIP"))
            return
        t0 = time.perf_counter()
        df = query_ohlcv(settings.market, symbol, tf)
        elapsed = time.perf_counter() - t0
        verdict = "PASS" if elapsed < 1.0 else "FAIL"
        rows.append(Row("Faz 1", "DuckDB query <1s", f"{len(df)} rows in {elapsed:.3f}s", verdict))
    except Exception as exc:  # noqa: BLE001
        rows.append(Row("Faz 1", "DuckDB query <1s", str(exc)[:40], "ERROR"))


def _check_indicators(rows: list[Row], symbol: str, tf: str) -> None:
    """Faz 2: core indicators compute on the real series without error."""
    try:
        from app.core.config import settings
        from app.indicators.compute import compute_indicator

        core = ["sma", "ema", "rsi", "atr", "macd", "bbands"]
        ok = 0
        for ind in core:
            frame = compute_indicator(settings.market, symbol, tf, ind)
            if len(frame) > 0:
                ok += 1
        verdict = "PASS" if ok == len(core) else "FAIL"
        rows.append(Row("Faz 2", "indicators compute", f"{ok}/{len(core)} on {symbol}", verdict))
    except Exception as exc:  # noqa: BLE001
        rows.append(Row("Faz 2", "indicators compute", str(exc)[:40], "ERROR"))


def _check_backtest_repro(rows: list[Row], symbol: str, tf: str) -> None:
    """Faz 3: same config+seed → bit-for-bit identical metrics (rule #6)."""
    try:
        from app.backtest.config import (
            CapitalConfig,
            IndicatorSpec,
            RuleClause,
            Rules,
            RunConfig,
            config_hash,
        )
        from app.backtest.runner import run_backtest

        cfg = RunConfig(
            symbol=symbol, tf=tf, direction="long",
            indicators=[
                IndicatorSpec(key="ema_fast", id="ema", params={"timeperiod": 9}),
                IndicatorSpec(key="ema_slow", id="ema", params={"timeperiod": 21}),
            ],
            rules=Rules(long_entry=[RuleClause(primitive="line_cross",
                args={"a": "ema_fast", "b": "ema_slow", "direction": "up"})]),
            capital=CapitalConfig(sizing="fixed", size_pct=1.0),
        )
        a = run_backtest(cfg)
        b = run_backtest(cfg)
        same = (
            config_hash(cfg) == config_hash(cfg)
            and a["metrics"]["net_return"] == b["metrics"]["net_return"]
            and a["metrics"]["num_trades"] == b["metrics"]["num_trades"]
        )
        rows.append(Row(
            "Faz 3", "backtest reproducible",
            f"{a['metrics']['num_trades']} trades, identical" if same else "DIVERGED",
            "PASS" if same else "FAIL",
        ))
    except Exception as exc:  # noqa: BLE001
        rows.append(Row("Faz 3", "backtest reproducible", str(exc)[:40], "ERROR"))


async def _check_scan_time(rows: list[Row], enabled: bool) -> None:
    """Faz 4: real 10×4 scan time (opt-in — this is the heavy operator measurement)."""
    if not enabled:
        rows.append(Row("Faz 4", "10×4 scan <2h", "operator step (--with-scan)", "SKIP"))
        return
    try:
        from app.core.db import SessionLocal, init_models
        from app.data.universe import latest_universe_symbols
        from app.discovery.config import ScanConfig
        from app.discovery.pipeline import run_scan

        await init_models()
        async with SessionLocal() as session:
            symbols = (await latest_universe_symbols(session, "binance_usdm"))[:10]
        if not symbols:
            rows.append(Row("Faz 4", "10×4 scan <2h", "no universe", "SKIP"))
            return
        config = ScanConfig(symbols=symbols, timeframes=["15m", "1h", "4h", "1d"])
        t0 = time.perf_counter()
        result = run_scan(config, symbols)
        elapsed = time.perf_counter() - t0
        over = " (EXCEEDS 2h)" if elapsed > 7200 else ""
        rows.append(Row(
            "Faz 4", "10×4 scan <2h",
            f"{len(symbols)}×4 in {elapsed / 60:.1f}min, {result.combos_tried} combos{over}",
            "PASS" if elapsed <= 7200 else "OVER",
        ))
    except Exception as exc:  # noqa: BLE001
        rows.append(Row("Faz 4", "10×4 scan <2h", str(exc)[:50], "ERROR"))


def _check_logic_suite(rows: list[Row]) -> None:
    """Faz 5–7: re-run the pure-logic acceptance tests (guarantees, not data)."""
    for label, files in LOGIC_SUITE.items():
        phase = label.split(" ", 1)[0] + " " + label.split(" ", 1)[1].split(" ")[0]
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *files],
                capture_output=True, text=True, timeout=300,
            )
            passed = proc.returncode == 0
            tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "?"
            rows.append(Row(phase, label.split(" ", 2)[2], tail[:40], "PASS" if passed else "FAIL"))
        except Exception as exc:  # noqa: BLE001
            rows.append(Row(phase, label, str(exc)[:40], "ERROR"))


async def _run(symbol: str, tf: str, with_scan: bool) -> int:
    rows: list[Row] = []
    await _check_data_status(rows)
    await _check_duckdb_speed(rows, symbol, tf)
    _check_indicators(rows, symbol, tf)
    _check_backtest_repro(rows, symbol, tf)
    await _check_scan_time(rows, with_scan)
    _check_logic_suite(rows)

    print("\nFaz 8 — Reality Check (real data)\n")
    print(_fmt_table(rows))
    fails = [r for r in rows if r.verdict in ("FAIL", "OVER", "ERROR")]
    skips = [r for r in rows if r.verdict == "SKIP"]
    print(
        f"\n{sum(r.verdict == 'PASS' for r in rows)} pass · "
        f"{len(fails)} needs-attention · {len(skips)} skipped (operator/no-data)"
    )
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Faz 8 reality check")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--tf", default="1h")
    parser.add_argument("--with-scan", action="store_true", help="run the real 10×4 scan timing")
    args = parser.parse_args()
    return asyncio.run(_run(args.symbol, args.tf, args.with_scan))


if __name__ == "__main__":
    sys.exit(main())
