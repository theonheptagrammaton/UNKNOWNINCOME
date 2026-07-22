"""Shared alpha-input bridge for the Faz 11 custom primitives.

Underscore-prefixed so the plugin loader skips it (it is a helper, not an indicator).
It reads the ``(market, symbol, tf)`` context that :func:`app.indicators.compute.
compute_indicator` stamps onto the OHLCV frame's ``attrs`` and fetches the extra data
streams (OI, funding, liquidations) through the lookahead-safe accessors in
:mod:`app.data.alpha`. Primitives prefer explicit ``df`` columns when present (so unit
tests need no stores) and fall back to these fetches on the production compute path.
"""

from __future__ import annotations

import pandas as pd

from app.data.timeframes import tf_to_ms


def context(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """Return ``(market, symbol, tf)`` stamped by the compute engine, or None."""
    attrs = getattr(df, "attrs", {}) or {}
    market, symbol, tf = attrs.get("market"), attrs.get("symbol"), attrs.get("tf")
    if market and symbol and tf:
        return str(market), str(symbol), str(tf)
    return None


def open_interest(df: pd.DataFrame) -> pd.Series | None:
    """Bar-aligned open-interest series for ``df``, or None if unavailable."""
    if "open_interest" in df.columns:
        return df["open_interest"].astype("float64").reset_index(drop=True)
    ctx = context(df)
    if ctx is None:
        return None
    from app.data.alpha import open_interest_aligned

    market, symbol, _tf = ctx
    return open_interest_aligned(market, symbol, df["ts"])


def funding_native(df: pd.DataFrame) -> pd.DataFrame | None:
    """Native (sparse) funding series ``[ts, funding_rate]``, or None if unavailable."""
    ctx = context(df)
    if ctx is None:
        return None
    from app.data.alpha import funding_history

    market, symbol, _tf = ctx
    hist = funding_history(market, symbol)
    return hist if not hist.empty else None


def liq_notional(df: pd.DataFrame) -> tuple[pd.Series, pd.Series] | None:
    """Bar-aligned ``(buy, sell)`` liquidation notional for ``df``, or None."""
    if "liq_buy_notional" in df.columns and "liq_sell_notional" in df.columns:
        return (
            df["liq_buy_notional"].astype("float64").reset_index(drop=True),
            df["liq_sell_notional"].astype("float64").reset_index(drop=True),
        )
    ctx = context(df)
    if ctx is None:
        return None
    from app.data.alpha import liq_notional_aligned

    market, symbol, tf = ctx
    return liq_notional_aligned(market, symbol, df["ts"], tf_to_ms(tf))
