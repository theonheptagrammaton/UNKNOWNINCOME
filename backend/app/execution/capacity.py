"""Capacity & participation (doc §26.2) — don't scale what you can't fill.

``participation = order_size / bar_volume``. Above the **1%** cap you are pushing your
own price and the backtest — which fills at the bar price regardless — is lying to you.
So the risk wall rejects any order over the cap (→ ``risk_event``), and every strategy
card shows how much capital it can carry before it would hit that cap.

All pure functions over base-asset quantities (the same unit for the order and the bar
volume, so the ratio is unitless), unit-tested; the risk wall and the API call in.
"""

from __future__ import annotations

import statistics

PARTICIPATION_CAP_PCT_DEFAULT = 1.0  # doc §26.2: 1% of bar volume


def participation(order_qty: float, bar_volume: float) -> float | None:
    """Fraction of the signal bar's volume this order consumes (``None`` if unknown).

    ``None`` when the bar volume is missing/non-positive — the caller must decide
    whether to gate (we do *not* silently treat "no volume data" as "0% participation").
    """
    if bar_volume is None or bar_volume <= 0 or order_qty <= 0:
        return None
    return order_qty / bar_volume


def exceeds_cap(
    order_qty: float, bar_volume: float, cap_pct: float = PARTICIPATION_CAP_PCT_DEFAULT
) -> bool:
    """Whether the order's participation is over the cap (unknown volume ⇒ allowed)."""
    p = participation(order_qty, bar_volume)
    return p is not None and p > cap_pct / 100.0


def capacity_usd(
    equity: float,
    order_qty: float,
    bar_volume: float,
    price: float,
    cap_pct: float = PARTICIPATION_CAP_PCT_DEFAULT,
) -> float | None:
    """Max equity carriable before the order would breach the participation cap.

    Position size scales ~linearly with equity, so participation scales with equity too:
    at the cap, ``equity_max = equity × cap / current_participation``. Returns quote
    (USD) capital; ``None`` when participation can't be measured.
    """
    p = participation(order_qty, bar_volume)
    if p is None or equity <= 0 or price <= 0:
        return None
    return equity * (cap_pct / 100.0) / p


def capacity_from_samples(
    equity: float,
    samples: list[tuple[float, float]],  # (order_qty, bar_volume) per recent trade
    cap_pct: float = PARTICIPATION_CAP_PCT_DEFAULT,
) -> float | None:
    """Capacity estimate from a strategy's recent fills (median participation).

    Uses the median participation across ``samples`` so one thin bar doesn't dominate
    the estimate; ``None`` when no sample has usable volume.
    """
    parts = [
        p for q, v in samples if (p := participation(q, v)) is not None and p > 0
    ]
    if not parts or equity <= 0:
        return None
    med = statistics.median(parts)
    return equity * (cap_pct / 100.0) / med
