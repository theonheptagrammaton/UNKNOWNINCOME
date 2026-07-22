"""Timeframe constants and bar-timing helpers.

All timestamps are bar *open* times in UTC milliseconds (doc §4.4).
"""

from __future__ import annotations

TF_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

# Binance USDT-M funding is charged every 8h.
FUNDING_TF = "funding"
FUNDING_INTERVAL_MS = 28_800_000

# Open-interest is polled every 5 min and stored on a 5-min grid (Faz 11 §25.3),
# so gap scanning reuses the same discipline as OHLCV.
OI_TF = "oi_5m"
OI_INTERVAL_MS = 300_000


def tf_to_ms(tf: str) -> int:
    """Milliseconds per bar for a timeframe (or the funding / OI poll interval)."""
    if tf == FUNDING_TF:
        return FUNDING_INTERVAL_MS
    if tf == OI_TF:
        return OI_INTERVAL_MS
    try:
        return TF_MS[tf]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {tf!r}") from exc


def last_closed_open_ts(now_ms: int, tf: str) -> int:
    """Open timestamp of the most recent *fully closed* bar at/-before now.

    A bar opening at ``t`` closes at ``t + step``; the currently forming bar is
    never included, so the last closed bar's open is ``floor(now/step)*step - step``.
    """
    step = tf_to_ms(tf)
    return (now_ms // step) * step - step
