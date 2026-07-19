"""Finalist cross-validation: agreement is silent, disagreement alarms (§6.1)."""

from __future__ import annotations

from pathlib import Path

from app.backtest.config import (
    CostConfig,
    IndicatorSpec,
    RiskExitConfig,
    RuleClause,
    Rules,
    RunConfig,
)
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.discovery.evaluate import run_eval
from app.discovery.finalist import FinalistResult, compare, get_finalist_engine
from app.discovery.finalist.lean_second import LeanSecondEngine
from fakes import make_wave_ohlcv

MARKET = "binance_usdm"
SYMBOL = "BTCUSDT"
TF = "1h"

_TOL = {"net_return": 0.25, "num_trades": 0.20, "sharpe": 0.35}


def _fr(net: float, trades: int, sharpe: float) -> FinalistResult:
    return FinalistResult(net, trades, sharpe, 10_000 * (1 + net), "lean_second")


def test_agreeing_engines_raise_no_alarm() -> None:
    primary = {"net_return": 0.10, "num_trades": 40, "sharpe": 1.20}
    assert compare(primary, _fr(0.11, 41, 1.25), _TOL, "combo-x") == []


def test_disagreeing_engines_raise_alarm() -> None:
    primary = {"net_return": 0.10, "num_trades": 40, "sharpe": 1.20}
    alarms = compare(primary, _fr(0.90, 5, -0.5), _TOL, "combo-x")
    assert len(alarms) >= 1
    metrics = {a.metric for a in alarms}
    assert "net_return" in metrics and "num_trades" in metrics
    assert all(a.combo_key == "combo-x" for a in alarms)
    assert all(a.rel_diff > a.tolerance for a in alarms)


def test_fallback_engine_when_backtesting_py_absent() -> None:
    # backtesting.py lives in the optional [finalist] extra; core/CI runs the fallback.
    engine = get_finalist_engine()
    assert engine.name == "lean_second"


def _ema_cross_config() -> RunConfig:
    return RunConfig(
        market=MARKET, symbol=SYMBOL, tf=TF, direction="both",
        indicators=[
            IndicatorSpec(key="ef", id="ema", params={"timeperiod": 9}),
            IndicatorSpec(key="es", id="ema", params={"timeperiod": 21}),
        ],
        rules=Rules(
            long_entry=[RuleClause(primitive="line_cross",
                                   args={"a": "ef", "b": "es", "direction": "up"})],
            long_exit=[RuleClause(primitive="line_cross",
                                  args={"a": "ef", "b": "es", "direction": "down"})],
            short_entry=[RuleClause(primitive="line_cross",
                                    args={"a": "ef", "b": "es", "direction": "down"})],
            short_exit=[RuleClause(primitive="line_cross",
                                   args={"a": "ef", "b": "es", "direction": "up"})],
        ),
        costs=CostConfig(funding_enabled=False),
        risk_exit=RiskExitConfig(atr_stop_mult=2.0, atr_target_mult=3.0),
    )


def test_second_engine_agrees_with_primary_on_real_run(data_dir: Path) -> None:
    """The lean second opinion faithfully reproduces the primary engine (no false alarm)."""
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(800, TF, seed=11)))
    config = _ema_cross_config()

    primary = run_eval(config).metrics
    finalist = LeanSecondEngine().verify(config)

    assert finalist.num_trades > 5  # a meaningful sample to compare
    assert compare(primary, finalist, _TOL, "ema-cross") == []
