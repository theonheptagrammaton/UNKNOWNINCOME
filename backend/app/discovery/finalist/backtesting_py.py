"""backtesting.py finalist adapter (doc §6.1) — best-effort, optional.

Imported only when the ``finalist`` extra is installed. It re-runs the genome's
precomputed signals through backtesting.py's event-driven engine (orders fill at
the next bar's open, matching rule #1). It is a *coarse* cross-check: backtesting.py
models commission but not perpetual funding or the ATR stop/target, so a divergence
alarm here flags "look closer", which is the intent. When the package is missing or
errors, :func:`crosscheck.get_finalist_engine` falls back to the lean second engine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest.config import RunConfig
from app.backtest.rules import build_signals, resolve_operands
from app.backtest.runner import _indicator_frames
from app.data.duckdb_query import query_ohlcv
from app.discovery.finalist.base import FinalistResult


class BacktestingPyEngine:
    """Finalist verification via the backtesting.py event-driven engine."""

    name = "backtesting_py"

    def verify(self, config: RunConfig) -> FinalistResult:
        from backtesting import Backtest, Strategy

        ohlcv = query_ohlcv(
            config.market, config.symbol, config.tf, config.start_ts, config.end_ts
        ).reset_index(drop=True)
        if len(ohlcv) < 2:
            return FinalistResult(0.0, 0, 0.0, config.capital.initial_cash, self.name)

        frames = _indicator_frames(config, ohlcv)
        ops = resolve_operands(ohlcv, frames)
        sig = build_signals(config.rules, ops, config.direction, len(ohlcv))
        le = sig["long_entry"].to_numpy(dtype="bool")
        lx = sig["long_exit"].to_numpy(dtype="bool")
        se = sig["short_entry"].to_numpy(dtype="bool")
        sx = sig["short_exit"].to_numpy(dtype="bool")

        df = pd.DataFrame(
            {
                "Open": ohlcv["open"].to_numpy(),
                "High": ohlcv["high"].to_numpy(),
                "Low": ohlcv["low"].to_numpy(),
                "Close": ohlcv["close"].to_numpy(),
                "Volume": ohlcv["volume"].to_numpy(),
            },
            index=pd.to_datetime(ohlcv["ts"].to_numpy(), unit="ms", utc=True),
        )

        class Genome(Strategy):
            def init(self) -> None:  # noqa: D401
                pass

            def next(self) -> None:
                i = len(self.data) - 1
                if not self.position:
                    if le[i]:
                        self.buy()
                    elif se[i]:
                        self.sell()
                elif self.position.is_long and (lx[i] or se[i]):
                    self.position.close()
                elif self.position.is_short and (sx[i] or le[i]):
                    self.position.close()

        commission = config.costs.commission_bps / 1e4
        bt = Backtest(
            df, Genome, cash=config.capital.initial_cash,
            commission=commission, trade_on_close=False, exclusive_orders=True,
        )
        stats = bt.run()

        def _num(v: object) -> float:
            try:
                f = float(v)
                return f if np.isfinite(f) else 0.0
            except (TypeError, ValueError):
                return 0.0

        return FinalistResult(
            net_return=_num(stats.get("Return [%]")) / 100.0,
            num_trades=int(_num(stats.get("# Trades"))),
            sharpe=_num(stats.get("Sharpe Ratio")),
            final_equity=_num(stats.get("Equity Final [$]")),
            engine=self.name,
        )
