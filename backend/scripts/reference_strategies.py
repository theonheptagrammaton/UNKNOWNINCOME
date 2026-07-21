"""Reference-strategy calibration bar (Faz 8, doc §22.1-5).

Three well-known, dead-simple strategies — **EMA9×21 cross**, **RSI(14) oversold
reversal**, **Donchian(20) breakout** — run on real data with *all costs on*
(commission + slippage + funding) and printed next to **buy & hold**.

This is the engine's calibration bar, not a search for alpha. We *expect* all three
to lose to buy & hold after costs (v2 §22.3): simple TA losing net of fees is the
literature's baseline, and an engine that makes them win is an engine that lies.
The numbers are printed exactly as they come out — no beautifying (v2 §22.3).

    python -m scripts.reference_strategies --symbols BTCUSDT ETHUSDT --tf 1h
    python -m scripts.reference_strategies              # default symbol set, 1h

Sizing is deliberately fixed full-deployment (``size_pct=1.0``, ``leverage=1.0``)
so the strategy return is on the same footing as buy & hold; the ATR-risk sizing the
live wall uses is proven elsewhere (test_sizing.py) and is not what this bar measures.
"""

from __future__ import annotations

import argparse
import math

import numpy as np

from app.backtest.config import (
    CapitalConfig,
    CostConfig,
    IndicatorSpec,
    RuleClause,
    Rules,
    RunConfig,
)
from app.backtest.runner import NoDataError, run_backtest
from app.data.duckdb_query import query_ohlcv
from app.data.timeframes import tf_to_ms

_MS_PER_YEAR = 365.25 * 24 * 60 * 60 * 1000.0

# The three reference strategies. Each returns entry/exit rules over the named
# indicators. All are long-only here (the calibration bar, not a directional bet).
REFERENCES = ("ema_cross", "rsi_reversal", "donchian_breakout")


def _fixed_capital() -> CapitalConfig:
    """Full-deployment, no leverage — comparable to buy & hold."""
    return CapitalConfig(initial_cash=10_000.0, sizing="fixed", size_pct=1.0, leverage=1.0)


def build_config(
    name: str, symbol: str, tf: str, start: int | None, end: int | None, *, costs: CostConfig
) -> RunConfig:
    """Build the :class:`RunConfig` for one reference strategy."""
    base = dict(
        market="binance_usdm", symbol=symbol, tf=tf, start_ts=start, end_ts=end,
        direction="long", costs=costs, capital=_fixed_capital(), seed=42,
    )
    if name == "ema_cross":
        return RunConfig(
            **base,  # type: ignore[arg-type]
            indicators=[
                IndicatorSpec(key="ema_fast", id="ema", params={"timeperiod": 9}),
                IndicatorSpec(key="ema_slow", id="ema", params={"timeperiod": 21}),
            ],
            rules=Rules(
                long_entry=[RuleClause(primitive="line_cross",
                    args={"a": "ema_fast", "b": "ema_slow", "direction": "up"})],
                long_exit=[RuleClause(primitive="line_cross",
                    args={"a": "ema_fast", "b": "ema_slow", "direction": "down"})],
            ),
        )
    if name == "rsi_reversal":
        # Enter when RSI recovers up through 30 (oversold reversal); exit when it
        # returns to neutral (up through 50). A recognizable mean-reversion shape.
        return RunConfig(
            **base,  # type: ignore[arg-type]
            indicators=[IndicatorSpec(key="rsi", id="rsi", params={"timeperiod": 14})],
            rules=Rules(
                long_entry=[RuleClause(primitive="threshold_cross",
                    args={"x": "rsi", "level": 30, "direction": "up"})],
                long_exit=[RuleClause(primitive="threshold_cross",
                    args={"x": "rsi", "level": 50, "direction": "up"})],
            ),
        )
    if name == "donchian_breakout":
        # Turtle-style: enter when the high reaches the 20-bar upper channel (a new
        # N-bar high), exit when the low reaches the 20-bar lower channel. Both use
        # only data through the bar close, so it stays lookahead-safe (rule #1).
        return RunConfig(
            **base,  # type: ignore[arg-type]
            indicators=[IndicatorSpec(key="dc", id="donchian",
                params={"upper_length": 20, "lower_length": 20})],
            rules=Rules(
                long_entry=[RuleClause(primitive="band_touch", args={
                    "price": "high", "upper": "dc.dcu", "lower": "dc.dcl",
                    "mode": "touch_upper"})],
                long_exit=[RuleClause(primitive="band_touch", args={
                    "price": "low", "upper": "dc.dcu", "lower": "dc.dcl",
                    "mode": "touch_lower"})],
            ),
        )
    raise ValueError(f"unknown reference strategy: {name!r}")


def buy_hold(symbol: str, tf: str, start: int | None, end: int | None) -> dict:
    """Buy at the first close, hold to the last — same annualization as metrics."""
    ohlcv = query_ohlcv("binance_usdm", symbol, tf, start, end).reset_index(drop=True)
    if len(ohlcv) < 2:
        raise NoDataError(f"no data for {symbol}/{tf}")
    close = ohlcv["close"].to_numpy(dtype="float64")
    ts = ohlcv["ts"].to_numpy(dtype="int64")
    equity = 10_000.0 * close / close[0]
    net_return = float(equity[-1] / equity[0] - 1.0)
    rets = np.diff(equity) / equity[:-1]
    bars_per_year = _MS_PER_YEAR / tf_to_ms(tf)
    std = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    sharpe = float(rets.mean() / std * math.sqrt(bars_per_year)) if std > 0 else 0.0
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max(1.0 - equity / peak)) if len(equity) else 0.0
    return {
        "net_return": net_return, "sharpe": sharpe, "max_drawdown": max_dd,
        "num_trades": 1, "bars": len(close),
        "first_ts": int(ts[0]), "last_ts": int(ts[-1]),
    }


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def run_symbol(symbol: str, tf: str, start: int | None, end: int | None, costs: CostConfig) -> None:
    """Print one comparison table for a symbol: 3 references + buy & hold."""
    print(f"\n══ {symbol} · {tf} ═══════════════════════════════════════════════")
    try:
        bh = buy_hold(symbol, tf, start, end)
    except NoDataError as exc:
        print(f"  SKIP: {exc}")
        return

    from datetime import UTC, datetime

    d0 = datetime.fromtimestamp(bh["first_ts"] / 1000, UTC).date()
    d1 = datetime.fromtimestamp(bh["last_ts"] / 1000, UTC).date()
    costs_on = costs.funding_enabled and costs.commission_bps > 0
    print(f"  bars={bh['bars']}  range={d0}→{d1}  costs={'ON' if costs_on else 'OFF (⚠ red)'}")
    header = (
        f"  {'strategy':<20}{'return':>12}{'sharpe':>10}"
        f"{'maxDD':>10}{'trades':>9}{'vs B&H':>12}"
    )
    print(header)
    print("  " + "─" * (len(header) - 2))

    for name in REFERENCES:
        try:
            out = run_backtest(build_config(name, symbol, tf, start, end, costs=costs))
        except NoDataError as exc:
            print(f"  {name:<20}  {exc}")
            continue
        m = out["metrics"]
        vs = m["net_return"] - bh["net_return"]
        print(
            f"  {name:<20}{_fmt_pct(m['net_return']):>12}{m['sharpe']:>10.2f}"
            f"{_fmt_pct(m['max_drawdown']):>10}{m['num_trades']:>9}{_fmt_pct(vs):>12}"
        )
    print(
        f"  {'buy_hold':<20}{_fmt_pct(bh['net_return']):>12}{bh['sharpe']:>10.2f}"
        f"{_fmt_pct(bh['max_drawdown']):>10}{bh['num_trades']:>9}{'—':>12}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Faz 8 reference-strategy calibration bar")
    parser.add_argument(
        "--symbols", nargs="*",
        default=["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
    )
    parser.add_argument("--tf", default="1h")
    parser.add_argument("--start", type=int, default=None, help="start ts (UTC ms)")
    parser.add_argument("--end", type=int, default=None, help="end ts (UTC ms)")
    parser.add_argument(
        "--no-costs", action="store_true",
        help="disable all costs (rule #2: flags the run red — for diagnosis only)",
    )
    args = parser.parse_args()

    if args.no_costs:
        costs = CostConfig(commission_bps=0.0, slippage_bps=0.0, funding_enabled=False)
        print("⚠  COSTLESS RUN (rule #2) — results are red-flagged, not decision-grade")
    else:
        costs = CostConfig()  # commission + slippage + funding all ON (default)

    print("Faz 8 — reference strategies vs buy & hold (all costs ON unless flagged)")
    print("Expectation (v2 §22.3): all three should LOSE to buy & hold after costs.")
    for symbol in args.symbols:
        run_symbol(symbol, args.tf, args.start, args.end, costs)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
