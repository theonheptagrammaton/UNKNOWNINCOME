"""Run Faz 8's three reference strategies through the Faz 9 deflation gate (§23.6).

The last §23.6 acceptance bullet: the three calibration-bar strategies (EMA9×21 cross,
RSI(14) oversold reversal, Donchian(20) breakout) are pushed through the Aşama 5.5 gate
and their verdicts printed — **and if they fail, the failure is written down**, not
hidden. This is honest by design: §22.3 already predicts these lose to buy & hold after
costs, so the gate should reject them (on "OOS return ≤ B&H" at least, usually on DSR
too). An engine that passed them would be lying.

Real data is the operator step (rule #13: synthetic numbers close no criterion). Without
a real Parquet store this prints **SKIP** per symbol — never a fake pass.

    python -m scripts.reference_gate --symbols BTCUSDT ETHUSDT --tf 1h
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
from scripts.reference_strategies import REFERENCES, build_config

from app.backtest.config import CostConfig
from app.data.duckdb_query import query_ohlcv
from app.discovery.evaluate import MIN_BARS, run_eval
from app.research.deflation import pbo_cscv
from app.research.gate import GateInputs, evaluate_gate, sharpe_moments

_PBO_SPLITS = 8  # a 3-strategy cohort over an OOS window: fewer splits than the pipeline
_OOS_FRACTION = 0.30  # last 30% of the series is the honest out-of-sample slice


def _bar_returns(equity: list[float]) -> np.ndarray:
    eq = np.asarray(equity, dtype="float64")
    if eq.size < 2:
        return np.zeros(0)
    prev = eq[:-1]
    r = np.where(prev != 0, eq[1:] / np.where(prev == 0, np.nan, prev) - 1.0, 0.0)
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


def _run_symbol(symbol: str, tf: str, costs: CostConfig) -> None:
    df = query_ohlcv("binance_usdm", symbol, tf)
    print(f"\n══ {symbol} · {tf} ═══════════════════════════════════════════")
    if df.empty or len(df) < MIN_BARS * 3:
        n = 0 if df.empty else len(df)
        print(f"  SKIP: no real data ({n} bars) — operator step (rule #13)")
        return

    ts = df["ts"].to_numpy(dtype="int64")
    split_ts = int(ts[int(len(ts) * (1.0 - _OOS_FRACTION))])
    close = df["close"].to_numpy(dtype="float64")
    oos_mask = ts >= split_ts
    bh_oos = float(close[oos_mask][-1] / close[oos_mask][0] - 1.0) if oos_mask.sum() >= 2 else 0.0

    # Evaluate every reference on the OOS window; collect trade + bar returns.
    evals: dict[str, dict] = {}
    for name in REFERENCES:
        cfg = build_config(name, symbol, tf, split_ts, None, costs=costs)
        try:
            ev = run_eval(cfg)
        except Exception as exc:  # NoDataError etc.
            evals[name] = {"error": str(exc)}
            continue
        trade_rets = np.array([t.return_pct for t in ev.result.trades], dtype="float64")
        evals[name] = {
            "trade_rets": trade_rets,
            "bar_rets": _bar_returns(ev.result.equity),
            "net_return": float(ev.metrics.get("net_return") or 0.0),
        }

    # PBO cohort across the three references (shared OOS bar axis).
    series = [e["bar_rets"] for e in evals.values() if "bar_rets" in e and e["bar_rets"].size]
    pbo: float | None = None
    if len(series) >= 2:
        width = min(s.size for s in series)
        if width >= _PBO_SPLITS:
            try:
                pbo = pbo_cscv(np.column_stack([s[:width] for s in series]), n_splits=_PBO_SPLITS)
            except ValueError:
                pbo = None

    srs = [sharpe_moments(e["trade_rets"])[0] for e in evals.values() if "trade_rets" in e]
    var_sr = float(np.var(srs, ddof=1)) if len(srs) >= 2 and np.var(srs) > 0 else 1.0

    print(f"  OOS from {split_ts} · buy&hold(OOS)={bh_oos * 100:+.2f}% · cohort PBO="
          f"{'n/a' if pbo is None else f'{pbo:.3f}'}")
    print(f"  {'strategy':<20}{'DSR':>8}{'trades':>8}{'net':>10}{'vsB&H':>10}  verdict")
    print("  " + "─" * 70)
    for name in REFERENCES:
        e = evals[name]
        if "error" in e:
            print(f"  {name:<20}  {e['error']}")
            continue
        sr, skew, kurt, T = sharpe_moments(e["trade_rets"])
        # N = 3 references form the trial family for this calibration run.
        result = evaluate_gate(GateInputs(
            sr=sr, skew=skew, kurtosis=kurt, oos_trades=T,
            n_trials=len(REFERENCES), var_sr=var_sr, pbo=pbo,
            oos_net_return=e["net_return"], bh_return=bh_oos,
        ))
        verdict = "PASS" if result.passed else "REJECT: " + "; ".join(result.reasons)
        print(f"  {name:<20}{result.dsr:>8.3f}{T:>8}{e['net_return'] * 100:>9.2f}%"
              f"{(e['net_return'] - bh_oos) * 100:>9.2f}%  {verdict}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Faz 9 — reference strategies through the gate")
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--tf", default="1h")
    args = parser.parse_args()

    print("Faz 9 — three reference strategies vs the deflation gate (§23.6)")
    print("Expectation (§22.3): all three should be REJECTED — losing to B&H is the baseline.")
    costs = CostConfig()  # all costs ON (rule #2)
    for symbol in args.symbols:
        _run_symbol(symbol, args.tf, costs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
