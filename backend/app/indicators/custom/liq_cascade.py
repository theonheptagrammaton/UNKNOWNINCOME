"""Liquidation cascade (Faz 11 §25.3).

Forced liquidations are non-discretionary market orders: a wave of them is temporary,
mechanical price pressure. This primitive sums liquidation notional over a trailing
``window`` of bars and, once past ``usd_threshold``, exposes the **net** direction —
positive when shorts are being force-bought (upward squeeze), negative when longs are
being force-sold (downward flush).

The liquidation stream cannot be backfilled (collected live since Faz 8) and is read
here through the per-bar Parquet the aggregator writes, so the compute path stays
synchronous. Lookahead-safe: only a trailing rolling sum over closed bars (kural #1).
"""

from __future__ import annotations

import pandas as pd

from app.indicators.custom import _alpha

INDICATOR = {
    "id": "liq_cascade",
    "name": "Liquidation Cascade",
    "category": "momentum",  # → trigger role (roles.ROLE_BY_CATEGORY)
    "inputs": ["liq_buy_notional", "liq_sell_notional"],
    "params": {
        "window": {"default": 5, "min": 1, "max": 100, "step": 1, "kind": "int"},
        "usd_threshold": {"default": 0.0, "min": 0.0, "max": 1e7, "step": 1e6, "kind": "float"},
    },
    "outputs": ["liq_cascade"],
    "signal_templates": ["slope", "threshold_cross"],
}


def compute(df: pd.DataFrame, window: int = 5, usd_threshold: float = 0.0) -> pd.Series:
    """Net signed liquidation notional over a trailing ``window``, gated by ``usd_threshold``.

    ``+`` = shorts force-bought (up pressure), ``−`` = longs force-sold (down pressure).
    Below the total-notional threshold the bar reads 0. Absent liquidation data → zeros.
    """
    n = len(df)
    liq = _alpha.liq_notional(df)
    if liq is None:
        return pd.Series(0.0, index=range(n), name="liq_cascade")
    buy, sell = liq
    buy = buy.reset_index(drop=True)
    sell = sell.reset_index(drop=True)

    window = max(1, int(window))
    buy_sum = buy.rolling(window, min_periods=1).sum()
    sell_sum = sell.rolling(window, min_periods=1).sum()
    total = buy_sum + sell_sum
    net = buy_sum - sell_sum
    thr = float(usd_threshold)
    out = net.where(total >= thr, 0.0) if thr > 0 else net
    return out.astype("float64").fillna(0.0).rename("liq_cascade")
