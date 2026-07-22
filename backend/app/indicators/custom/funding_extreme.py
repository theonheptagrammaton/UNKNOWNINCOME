"""Funding-rate change extreme (Faz 11 §25.3).

Funding **level** is nearly always tiny and mean-reverting; what carries information is
the **change** and where that change sits in *its own* history. A funding change in the
top percentile of everything seen so far means positioning is stretching fast — a
crowded book. This primitive ranks Δfunding with an **expanding** percentile (only past
values) and flags the tail.

Because funding settles every 8h, the rank is computed on the native (sparse) funding
series and then joined onto the bar grid backward-as-of, so it is lookahead-safe and
cheap. As a positioning **filter**, the flagged state persists until the next settlement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators.custom import _alpha

INDICATOR = {
    "id": "funding_extreme",
    "name": "Funding Change Extreme",
    "category": "statistic",  # → filter role (roles.ROLE_BY_CATEGORY)
    "inputs": ["funding_rate"],
    "params": {
        "percentile": {"default": 0.9, "min": 0.5, "max": 0.99, "step": 0.01, "kind": "float"},
        "dir": {"default": 0, "choices": [-1, 0, 1], "kind": "categorical"},
    },
    "outputs": ["funding_extreme"],
    "signal_templates": ["slope", "regime"],
}


def _expanding_pct_rank(x: pd.Series) -> pd.Series:
    """Expanding percentile rank: fraction of finite values ``≤`` the current one.

    Uses only values at or before each index (no future leakage). NaN where the input
    is NaN. O(n²) but run on the sparse (8h) funding series, so it stays cheap.
    """
    vals = x.to_numpy(dtype="float64")
    out = np.full(vals.shape, np.nan)
    for i in range(len(vals)):
        v = vals[i]
        if not np.isfinite(v):
            continue
        window = vals[: i + 1]
        finite = window[np.isfinite(window)]
        if finite.size:
            out[i] = float(np.mean(finite <= v))
    return pd.Series(out, index=x.index)


def extreme_activation(funding_rate: pd.Series, percentile: float, dir: float) -> pd.Series:
    """Signed tail flag of Δfunding's expanding percentile rank.

    ``dir`` +1 → high tail only (+1), −1 → low tail only (−1), 0 → both (±1). Elsewhere 0.
    """
    fr = funding_rate.astype("float64").reset_index(drop=True)
    rank = _expanding_pct_rank(fr.diff())
    p = float(percentile)
    hi = rank >= p
    lo = rank <= (1.0 - p)
    d = float(dir)
    if d > 0:
        out = np.where(hi, 1.0, 0.0)
    elif d < 0:
        out = np.where(lo, -1.0, 0.0)
    else:
        out = np.where(hi, 1.0, np.where(lo, -1.0, 0.0))
    return pd.Series(out, index=fr.index)


def compute(df: pd.DataFrame, percentile: float = 0.9, dir: float = 0.0) -> pd.Series:
    """Funding-change extreme flag aligned to ``df``'s bars.

    A ``funding_rate`` column on ``df`` (used by tests / alt callers) is treated as the
    series to rank directly; otherwise the native funding history is fetched and the
    per-settlement flag is joined backward-as-of onto the bars.
    """
    n = len(df)
    if "funding_rate" in df.columns:
        act = extreme_activation(df["funding_rate"], percentile, dir)
        return act.reset_index(drop=True).rename("funding_extreme")

    native = _alpha.funding_native(df)
    if native is None:
        return pd.Series(0.0, index=range(n), name="funding_extreme")
    from app.data.alpha import align_backward

    act = extreme_activation(native["funding_rate"], percentile, dir)
    source = pd.DataFrame(
        {
            "ts": native["ts"].astype("int64").reset_index(drop=True),
            "act": act.reset_index(drop=True),
        }
    )
    aligned = align_backward(df["ts"], source, ["act"])
    return aligned["act"].fillna(0.0).astype("float64").rename("funding_extreme")
