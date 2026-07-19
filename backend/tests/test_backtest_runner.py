"""End-to-end runner: config hashing, EMA9×EMA21 vs an independent simulator,
and bit-for-bit reproducibility (KABUL: reference match · same config+seed).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.backtest.config import (
    CapitalConfig,
    CostConfig,
    IndicatorSpec,
    RuleClause,
    Rules,
    RunConfig,
    config_hash,
)
from app.backtest.runner import NoDataError, run_backtest
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.indicators.compute import compute_indicator
from app.indicators.signals import line_cross
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
SYMBOL = "BTCUSDT"
TF = "1h"

COMMISSION_BPS = 4.0
SLIPPAGE_BPS = 5.0


def _seed(n: int = 400) -> None:
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(n, TF, seed=7)))


def _ema_cross_config(direction: str = "long") -> RunConfig:
    return RunConfig(
        market=MARKET, symbol=SYMBOL, tf=TF, direction=direction,  # type: ignore[arg-type]
        indicators=[
            IndicatorSpec(key="ema_fast", id="ema", params={"timeperiod": 9}),
            IndicatorSpec(key="ema_slow", id="ema", params={"timeperiod": 21}),
        ],
        rules=Rules(
            long_entry=[
                RuleClause(primitive="line_cross",
                           args={"a": "ema_fast", "b": "ema_slow", "direction": "up"})
            ],
            long_exit=[
                RuleClause(primitive="line_cross",
                           args={"a": "ema_fast", "b": "ema_slow", "direction": "down"})
            ],
        ),
        costs=CostConfig(commission_bps=COMMISSION_BPS, slippage_model="fixed_bps",
                         slippage_bps=SLIPPAGE_BPS, funding_enabled=False),
        capital=CapitalConfig(initial_cash=10_000.0, size_pct=1.0, leverage=1.0),
        seed=42,
    )


# ── Config hash (rule #6) ────────────────────────────────────────────────────
def test_config_hash_is_stable_and_seed_sensitive() -> None:
    c1 = _ema_cross_config()
    c2 = _ema_cross_config()
    assert config_hash(c1) == config_hash(c2)  # identical config ⇒ identical hash

    c3 = _ema_cross_config()
    c3.seed = 43
    assert config_hash(c3) != config_hash(c1)  # seed participates in the hash


# ── KABUL 1: reference strategy matches an independent computation ────────────
def _independent_long_only(
    ohlcv, entry: np.ndarray, exit_: np.ndarray, cash: float
) -> tuple[float, int]:
    """A from-scratch long-only simulator: close-signal → next-open fill + costs."""
    open_ = ohlcv["open"].to_numpy(dtype="float64")
    close = ohlcv["close"].to_numpy(dtype="float64")
    n = len(open_)
    comm = COMMISSION_BPS / 1e4
    slip = SLIPPAGE_BPS / 1e4
    pos, qty, entry_fill, trades = 0, 0.0, 0.0, 0
    for i in range(1, n):
        s = i - 1
        op = open_[i]
        if pos == 1 and exit_[s]:
            fill = op * (1 - slip)
            cash += qty * (fill - entry_fill) - comm * qty * fill
            pos, trades = 0, trades + 1
        if pos == 0 and entry[s]:
            fill = op * (1 + slip)
            qty = cash / fill
            cash -= comm * qty * fill
            entry_fill, pos = fill, 1
    if pos == 1:  # mark out at final close, no exit cost
        cash += qty * (close[-1] - entry_fill)
        trades += 1
    return cash, trades


def test_ema_cross_matches_independent_simulator(data_dir: Path) -> None:
    _seed(400)
    config = _ema_cross_config("long")

    # Independent path: production indicators + primitives, from-scratch engine.
    from app.data.duckdb_query import query_ohlcv

    bars = query_ohlcv(MARKET, SYMBOL, TF)
    ema9 = compute_indicator(MARKET, SYMBOL, TF, "ema", {"timeperiod": 9})["ema"]
    ema21 = compute_indicator(MARKET, SYMBOL, TF, "ema", {"timeperiod": 21})["ema"]
    entry = line_cross(ema9, ema21, "up").to_numpy(dtype="bool")
    exit_ = line_cross(ema9, ema21, "down").to_numpy(dtype="bool")
    expected_equity, expected_trades = _independent_long_only(bars, entry, exit_, 10_000.0)

    out = run_backtest(config)
    assert out["metrics"]["num_trades"] == expected_trades
    assert expected_trades >= 1, "reference series should produce EMA crosses"
    assert out["metrics"]["final_equity"] == pytest.approx(expected_equity, rel=1e-9)


# ── KABUL 3: same config + seed ⇒ bit-for-bit identical ──────────────────────
def test_same_config_seed_bit_for_bit(data_dir: Path) -> None:
    _seed(300)
    config = _ema_cross_config("both")
    a = run_backtest(config)
    b = run_backtest(config)
    dump = lambda x: json.dumps(x, sort_keys=True)  # noqa: E731
    assert dump(a["metrics"]) == dump(b["metrics"])
    assert dump(a["report"]) == dump(b["report"])


# ── Lookahead at the pipeline level (report shape + no-data guard) ────────────
def test_report_shape(data_dir: Path) -> None:
    _seed(300)
    out = run_backtest(_ema_cross_config("long"))
    report = out["report"]
    assert report["bars"] == 300
    assert len(report["candles"]) == 300
    assert len(report["equity"]) == 300
    assert len(report["drawdown"]) == 300
    # Two markers (entry+exit) per trade.
    assert len(report["markers"]) == 2 * out["metrics"]["num_trades"]
    assert report["cost_breakdown"]["funding_on"] is False


def test_no_data_raises(data_dir: Path) -> None:
    with pytest.raises(NoDataError):
        run_backtest(_ema_cross_config("long"))
