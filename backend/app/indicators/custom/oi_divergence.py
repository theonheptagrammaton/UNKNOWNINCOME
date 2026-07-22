"""Price–open-interest divergence (Faz 11 §25.3).

The same price move means different things depending on open interest: *price ↑ + OI ↑*
is fresh money entering, *price ↑ + OI ↓* is shorts covering (a weaker, self-exhausting
move). This primitive fires when the current bar's price change and OI change match a
configured ``(price_dir, oi_dir)`` pattern — a positioning **filter**, not a trigger.

Lookahead-safe: only 1-bar changes (bar ``t`` vs ``t−1``) and a backward-as-of OI join
are used, so a future bar can never alter a past value (kural #1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators.custom import _alpha

INDICATOR = {
    "id": "oi_divergence",
    "name": "Price–OI Divergence",
    "category": "volume",  # → filter role (roles.ROLE_BY_CATEGORY)
    "inputs": ["close", "open_interest"],
    "params": {
        "price_dir": {"default": 1, "choices": [-1, 1], "kind": "categorical"},
        "oi_dir": {"default": 1, "choices": [-1, 1], "kind": "categorical"},
    },
    "outputs": ["oi_divergence"],
    "signal_templates": ["slope", "regime"],
}


def compute(df: pd.DataFrame, price_dir: float = 1.0, oi_dir: float = 1.0) -> pd.Series:
    """Signed activation where price and OI move in the configured directions.

    Output is ``price_dir`` where both this bar's price change and OI change match the
    requested signs, else 0 — so a rising activation reads as the configured setup
    strengthening. Absent OI data → all zeros (no signal).
    """
    close = df["close"].astype("float64").reset_index(drop=True)
    oi = _alpha.open_interest(df)
    if oi is None:
        return pd.Series(0.0, index=range(len(close)), name="oi_divergence")
    oi = oi.reset_index(drop=True)

    pd_sign = 1.0 if float(price_dir) >= 0 else -1.0
    od_sign = 1.0 if float(oi_dir) >= 0 else -1.0
    price_chg = np.sign(close.diff())
    oi_chg = np.sign(oi.diff())
    match = (price_chg == pd_sign) & (oi_chg == od_sign)
    return (match.astype("float64") * pd_sign).fillna(0.0).rename("oi_divergence")
