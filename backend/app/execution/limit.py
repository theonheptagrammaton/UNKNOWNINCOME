"""Limit-entry order path (doc §26.3) — opt-in, default OFF, separately reported.

Taker fees hurt (≈4 bps/side, 8 bps round-trip); a resting **maker** limit can flip that
to a rebate. So for entries we optionally post a limit order and, if it hasn't filled
within ``T`` seconds, fall back to a market (taker) order.

**The bias warning is the whole reason this is OFF by default (doc §26.3):** an unfilled
limit is usually the case where price ran *away from you* — exactly the trades you
wanted. Modelling that adverse selection faithfully is hard, so limit entries are opt-in
and carry a separate report tag; nothing here is on the default path.

This module is a small resolver (pure) + a router (holds resting orders and drives one
adapter). The router reuses the adapter's existing per-order cost overrides — a maker
fill posts at the limit price with zero slippage and the maker fee; a fallback posts a
plain market order — so no adapter change is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.execution.base import OrderRequest, OrderResult

MAKER_FEE_BPS_DEFAULT = 2.0  # Binance USDT-M maker ≈ 0.02%/side (vs 0.04% taker)


class LimitAction(StrEnum):
    REST = "rest"  # not marketable yet, still within the timeout window
    FILL_MAKER = "fill_maker"  # price reached the limit → maker fill
    FALLBACK_MARKET = "fallback_market"  # timed out unfilled → market (taker) fallback


def resolve_limit(
    side: str,
    limit_price: float,
    created_ts: int,
    timeout_ms: int,
    now_ts: int,
    current_price: float | None,
) -> LimitAction:
    """Decide a resting limit's fate from elapsed time + current price (pure).

    A buy limit is marketable once price trades at/below it; a sell limit at/above it.
    Marketability is checked *before* the timeout so a same-instant reachable limit
    fills as maker rather than falling back.
    """
    if current_price is not None and current_price > 0:
        reached = (
            (side == "buy" and current_price <= limit_price)
            or (side == "sell" and current_price >= limit_price)
        )
        if reached:
            return LimitAction.FILL_MAKER
    if now_ts - created_ts >= timeout_ms:
        return LimitAction.FALLBACK_MARKET
    return LimitAction.REST


@dataclass
class RestingLimit:
    """A limit order posted and waiting (keyed by ``client_id`` in the router)."""

    req: OrderRequest
    created_ts: int
    timeout_ms: int


class LimitOrderRouter:
    """Posts limit entries, then fills-as-maker or falls back to market on timeout.

    Drives exactly one adapter (paper or live). The bot polls it every tick with the
    latest price so a resting limit either fills as maker or times out into a market
    order — the acceptance-critical ``T`` seconds → market fallback path.
    """

    def __init__(self, adapter: object, *, maker_fee_bps: float = MAKER_FEE_BPS_DEFAULT) -> None:
        self._adapter = adapter
        self._maker_fee_bps = maker_fee_bps
        self._resting: dict[str, RestingLimit] = {}

    @property
    def resting(self) -> dict[str, RestingLimit]:
        return self._resting

    def submit(
        self, req: OrderRequest, now_ts: int, current_price: float | None
    ) -> OrderResult | None:
        """Post a limit order. Returns a Fill if immediately marketable, else ``None``.

        ``None`` means the order is now resting; the bot must ``poll`` it on later ticks.
        Requires ``req.order_type == "limit"`` with ``limit_price`` and ``timeout_s`` set.
        """
        if req.order_type != "limit" or req.limit_price is None or req.timeout_s is None:
            raise ValueError("submit() needs a limit order with limit_price and timeout_s")
        timeout_ms = int(req.timeout_s * 1000)
        action = resolve_limit(
            req.side, req.limit_price, now_ts, timeout_ms, now_ts, current_price
        )
        if action is LimitAction.FILL_MAKER:
            return self._fill_maker(req)
        key = req.client_id or f"limit-{len(self._resting)}-{now_ts}"
        self._resting[key] = RestingLimit(req=req, created_ts=now_ts, timeout_ms=timeout_ms)
        return None

    def poll(
        self, now_ts: int, price_by_symbol: dict[str, float]
    ) -> list[tuple[str, str, OrderResult]]:
        """Resolve every resting limit against the current prices.

        Returns ``(client_key, outcome, OrderResult)`` for each order that filled or fell
        back this tick — ``outcome`` is ``"maker"`` or ``"market_fallback"`` so the bot
        can tag it separately in the report (doc §26.3).
        """
        out: list[tuple[str, str, OrderResult]] = []
        for key, rl in list(self._resting.items()):
            price = price_by_symbol.get(rl.req.symbol)
            action = resolve_limit(
                rl.req.side, rl.req.limit_price, rl.created_ts, rl.timeout_ms, now_ts, price
            )
            if action is LimitAction.FILL_MAKER:
                del self._resting[key]
                out.append((key, "maker", self._fill_maker(rl.req)))
            elif action is LimitAction.FALLBACK_MARKET:
                del self._resting[key]
                out.append((key, "market_fallback", self._fallback_market(rl.req, price)))
        return out

    # ── fills ────────────────────────────────────────────────────────────────
    def _fill_maker(self, req: OrderRequest) -> OrderResult:
        """Fill at the limit price with zero slippage and the maker fee."""
        return self._adapter.place_order(
            OrderRequest(
                symbol=req.symbol, side=req.side, qty=req.qty,
                reduce_only=req.reduce_only, order_type="limit",
                reference_price=req.limit_price, leverage=req.leverage,
                client_id=req.client_id, commission_bps=self._maker_fee_bps, slippage_bps=0.0,
            )
        )

    def _fallback_market(self, req: OrderRequest, price: float | None) -> OrderResult:
        """Time-out fallback: a plain market order at the current price (taker fee)."""
        return self._adapter.place_order(
            OrderRequest(
                symbol=req.symbol, side=req.side, qty=req.qty,
                reduce_only=req.reduce_only, order_type="market",
                reference_price=price or req.reference_price or req.limit_price,
                leverage=req.leverage, client_id=req.client_id,
                commission_bps=req.commission_bps, slippage_bps=req.slippage_bps,
            )
        )
