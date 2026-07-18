"""Example custom indicator: rolling Z-Score of close (doc §5.1 plugin demo).

Z = (close - rolling_mean) / rolling_std, computed at bar close only — no future
bars are referenced, so it is lookahead-safe. Drop a file like this into
``indicators/custom/`` and it joins the registry automatically.
"""

from __future__ import annotations

import pandas as pd

INDICATOR = {
    "id": "zscore",
    "name": "Rolling Z-Score",
    "category": "statistic",
    "inputs": ["close"],
    "params": {"length": {"default": 20, "min": 5, "max": 200, "step": 1, "kind": "int"}},
    "outputs": ["zscore"],
    "signal_templates": ["threshold_cross", "slope"],
}


def compute(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Rolling z-score of the close series over ``length`` bars (population std)."""
    length = int(length)
    close = df["close"].astype("float64")
    mean = close.rolling(length).mean()
    std = close.rolling(length).std(ddof=0)
    z = (close - mean) / std
    return z.rename("zscore")
