"""Taker flow imbalance — the free alpha column (Faz 11 §25.2).

Binance already ships ``taker_buy_base_volume`` in every kline; it was being thrown
away. The aggressive (market-order) side is the one *demanding* liquidity, so a bar
where takers bought most of the volume leans bullish::

    per-bar imbalance = (2·taker_buy − volume) / volume        # −1 … +1

We smooth it over ``window`` bars and let discovery treat it like any other momentum
trigger (slope of the smoothed imbalance). It is **not** exempt from the Faz 9 gate.

Lookahead-safe: the rolling mean at bar ``t`` uses only bars ``≤ t`` (kural #1).
"""

from __future__ import annotations

import pandas as pd

INDICATOR = {
    "id": "flow_imbalance",
    "name": "Taker Flow Imbalance",
    "category": "momentum",  # → trigger role (roles.ROLE_BY_CATEGORY)
    "inputs": ["taker_buy_base_volume", "volume"],
    "params": {
        "window": {"default": 20, "min": 2, "max": 200, "step": 1, "kind": "int"},
        "threshold": {"default": 0.0, "min": 0.0, "max": 0.8, "step": 0.05, "kind": "float"},
        "dir": {"default": 0, "choices": [-1, 0, 1], "kind": "categorical"},
    },
    "outputs": ["flow_imbalance"],
    "signal_templates": ["slope", "threshold_cross"],
}


def per_bar_imbalance(taker_buy: pd.Series, volume: pd.Series) -> pd.Series:
    """Signed per-bar taker imbalance in ``[-1, 1]`` (0 where volume or taker is absent)."""
    vol = volume.astype("float64")
    tb = taker_buy.astype("float64")
    fi = (2.0 * tb - vol) / vol
    return fi.where((vol > 0) & tb.notna(), 0.0)


def compute(
    df: pd.DataFrame, window: int = 20, threshold: float = 0.0, dir: float = 0.0
) -> pd.Series:
    """Window-smoothed taker imbalance; ``threshold`` zeroes weak bars, ``dir`` orients sign.

    ``dir``: +1 long-oriented (bullish = positive), −1 short-oriented (sign flipped),
    0 both (raw sign). All are numeric so the param sweeps like any categorical knob.
    """
    window = max(1, int(window))
    fi = per_bar_imbalance(df["taker_buy_base_volume"], df["volume"])
    smoothed = fi.rolling(window, min_periods=1).mean()
    thr = float(threshold)
    if thr > 0:
        smoothed = smoothed.where(smoothed.abs() >= thr, 0.0)
    if float(dir) < 0:
        smoothed = -smoothed
    return smoothed.astype("float64").rename("flow_imbalance")
