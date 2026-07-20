"""Position sizing + liquidation — the single model backtest and live share (doc §9.4, §16 #4).

The whole reason a backtest-profitable strategy can lose money live is that the two
sized positions differently. This module is the *one* place both the lean backtest
engine (:mod:`app.backtest.engine`) and the live/paper risk wall
(:class:`app.execution.risk.RiskLayer`) compute quantity, so they can never drift
again.

Sizing (doc §16 decision #4 default = **ATR-based risk**):

* ``"atr"`` — risk a fixed fraction of equity (``per_trade_pct``) measured to the
  stop: ``qty = (equity · per_trade_pct/100) / stop_distance``. This only makes
  sense *with* a stop, so an ATR-sized trade always carries one (the caller enforces
  the same stop as an actual exit — otherwise the "1% risk" is fiction).
* ``"fixed"`` — deploy ``fixed_fraction`` of equity as levered notional:
  ``qty = (equity · fixed_fraction · leverage) / price`` (the legacy Phase-3
  behaviour, kept for reproducibility).

Both are capped by available margin (``notional ≤ equity · leverage``).

Liquidation (isolated margin, rule #11): a levered position is force-closed when the
adverse move eats the margin down to the maintenance level. :func:`liquidation_price`
gives that price so the backtest can model the wipe-out instead of letting equity go
negative and "recover" — an impossibility that flatters leveraged backtests.
"""

from __future__ import annotations

from typing import Literal

Sizing = Literal["atr", "fixed"]


def margin_cap_qty(equity: float, price: float, leverage: float) -> float:
    """Largest qty whose notional stays within ``equity · leverage`` (0 if unpriced)."""
    if equity <= 0 or price <= 0 or leverage <= 0:
        return 0.0
    return (equity * leverage) / price


def position_size(
    *,
    equity: float,
    price: float,
    leverage: float,
    sizing: Sizing = "atr",
    per_trade_pct: float = 1.0,
    stop_distance: float | None = None,
    fixed_fraction: float = 1.0,
) -> float:
    """Base-asset quantity to open, shared by the engine and the risk wall.

    ``stop_distance`` is the absolute price distance to the protective stop; it is
    **required** for ``sizing="atr"`` (returns 0 when it is missing/≤0, so a caller
    never silently falls back to a huge fixed size during indicator warm-up).
    Everything is capped by :func:`margin_cap_qty`.
    """
    if equity <= 0 or price <= 0 or leverage <= 0:
        return 0.0
    cap = margin_cap_qty(equity, price, leverage)
    if sizing == "atr":
        if not stop_distance or stop_distance <= 0:
            return 0.0
        risk_amount = equity * per_trade_pct / 100.0
        return min(risk_amount / stop_distance, cap)
    # fixed
    qty = (equity * fixed_fraction * leverage) / price
    return min(qty, cap) if qty > 0 else 0.0


def liquidation_price(
    entry: float, side: int, leverage: float, maintenance_margin_rate: float = 0.005
) -> float | None:
    """Isolated-margin liquidation price for a ``side`` (+1 long / −1 short) position.

    Fee-agnostic estimate: the position is liquidated once the adverse move reaches
    ``1/leverage − mm`` of the entry (the point where equity hits the maintenance
    margin). Returns ``None`` when it cannot be estimated (leverage ≤ 1 puts it at
    ~0/∞ — effectively unreachable, so callers treat ``None`` as "no liquidation").
    """
    if entry <= 0 or leverage <= 1.0:
        return None
    frac = 1.0 / leverage - maintenance_margin_rate
    if frac <= 0:
        return None
    return entry * (1.0 - frac) if side > 0 else entry * (1.0 + frac)
