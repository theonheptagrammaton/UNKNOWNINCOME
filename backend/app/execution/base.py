"""Execution adapter interface (doc §9.3).

One interface, two implementations: :class:`~app.execution.paper.PaperAdapter`
(Phase 5) and ``BinanceAdapter`` (Phase 7). The bot is written against this
Protocol and never knows which mode it is in (doc §9.1) — paper and live results
land in the same tables, differing only by ``mode``.

The bot never touches an adapter directly; every order goes through the risk wall
(:class:`~app.execution.risk.RiskLayer`, doc §9.4), which is the sole caller of
``place_order``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class OrderRequest:
    """A market order the risk layer has already approved and sized."""

    symbol: str
    side: str  # "buy" | "sell"
    qty: float  # base-asset quantity (> 0); leverage is already baked into sizing
    reduce_only: bool = False
    order_type: str = "market"  # "market" | "limit" (limit entry path, §26.3)
    # Reference price for the fill simulator (paper) — the current bar/tick price.
    reference_price: float | None = None
    leverage: float = 1.0
    client_id: str | None = None
    # Per-genome cost overrides for the paper fill sim (fall back to adapter defaults).
    commission_bps: float | None = None
    slippage_bps: float | None = None
    # Limit-entry path (doc §26.3, default OFF/opt-in): rest at ``limit_price`` and fall
    # back to a market order after ``timeout_s`` seconds if it hasn't filled.
    limit_price: float | None = None
    timeout_s: float | None = None


@dataclass
class Fill:
    """The realized fill of a market order."""

    price: float  # fill price incl. slippage
    qty: float
    commission: float  # positive cost
    slippage_cost: float  # informational (already embedded in ``price``)
    realized_pnl: float = 0.0  # realized on the closed portion, if any


@dataclass
class OrderResult:
    """Outcome of ``place_order`` — filled (with a Fill) or rejected (with a reason)."""

    accepted: bool
    order_id: str | None
    status: str  # "filled" | "rejected"
    fill: Fill | None = None
    reason: str | None = None


@dataclass
class Position:
    """A net position in one symbol (one-way mode, doc §9.4)."""

    symbol: str
    side: str  # "long" | "short"
    qty: float
    entry_price: float
    leverage: float = 1.0
    mark_price: float | None = None


@dataclass
class Balance:
    """Account balance snapshot."""

    equity: float
    cash: float
    unrealized_pnl: float


class ExecutionAdapter(Protocol):
    """place / cancel / positions / balance — the whole surface the bot needs."""

    mode: str

    def place_order(self, order: OrderRequest) -> OrderResult: ...

    def cancel_order(self, order_id: str) -> bool: ...

    def cancel_all(self) -> int: ...

    def get_positions(self) -> list[Position]: ...

    def get_balance(self) -> Balance: ...
