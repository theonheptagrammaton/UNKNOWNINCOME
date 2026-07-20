"""Paper fill simulator (doc §9.1) — the first :class:`ExecutionAdapter`.

Fills market orders at the reference price plus a slippage model, charges the §6.2
commission, accrues perpetual funding on open positions, and keeps net one-way
positions (doc §9.4). Cash accounting mirrors the backtest engine exactly
(commission both sides, realized gross on close, funding signed) so a paper run and
its originating backtest agree — that equivalence is the reason paper trades the
same genome object a backtest validated.

In-memory and deterministic; the bot persists every fill to the shared
orders/trades/equity tables and rehydrates open positions on restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.execution.base import Balance, Fill, OrderRequest, OrderResult, Position


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


@dataclass
class _NetPosition:
    side: int  # +1 long / −1 short
    qty: float  # > 0
    entry: float  # average entry (incl. entry slippage)
    leverage: float


class PaperAdapter:
    """Deterministic in-memory fill simulator for ``mode=paper``."""

    mode = "paper"

    def __init__(
        self,
        initial_cash: float,
        commission_bps: float = 4.0,
        slippage_bps: float = 5.0,
    ) -> None:
        self._cash = float(initial_cash)
        self._commission = commission_bps / 1e4
        self._slippage = slippage_bps / 1e4
        self._positions: dict[str, _NetPosition] = {}
        self._mark: dict[str, float] = {}
        self._order_seq = 0
        self.realized_pnl = 0.0
        self.total_funding = 0.0

    # ── ExecutionAdapter surface ─────────────────────────────────────────────
    def place_order(self, order: OrderRequest) -> OrderResult:
        """Fill a market order at ref ± slippage; nets into the symbol's position."""
        ref = order.reference_price
        if ref is None or ref <= 0 or order.qty <= 0:
            return OrderResult(
                accepted=False, order_id=None, status="rejected",
                reason="paper: missing/invalid reference price or qty",
            )
        self._order_seq += 1
        order_id = f"paper-{self._order_seq}"
        is_buy = order.side == "buy"
        slip_rate = self._slippage if order.slippage_bps is None else order.slippage_bps / 1e4
        comm_rate = self._commission if order.commission_bps is None else order.commission_bps / 1e4
        slip = ref * slip_rate
        fill = ref + slip if is_buy else ref - slip
        signed = order.qty if is_buy else -order.qty

        commission = comm_rate * order.qty * fill
        self._cash -= commission
        realized = self._apply_fill(order.symbol, signed, fill, order.leverage)
        self._mark[order.symbol] = fill
        return OrderResult(
            accepted=True,
            order_id=order_id,
            status="filled",
            fill=Fill(
                price=fill,
                qty=order.qty,
                commission=commission,
                slippage_cost=slip * order.qty,
                realized_pnl=realized,
            ),
        )

    def cancel_order(self, order_id: str) -> bool:
        """Market orders fill on submission, so there is nothing resting to cancel."""
        return False

    def cancel_all(self) -> int:
        """No resting orders in the paper sim; kill switch closes the entry path."""
        return 0

    def get_positions(self) -> list[Position]:
        return [
            Position(
                symbol=sym,
                side="long" if p.side > 0 else "short",
                qty=p.qty,
                entry_price=p.entry,
                leverage=p.leverage,
                mark_price=self._mark.get(sym, p.entry),
            )
            for sym, p in self._positions.items()
        ]

    def get_balance(self) -> Balance:
        unrealized = self._unrealized()
        return Balance(
            equity=self._cash + unrealized,
            cash=self._cash,
            unrealized_pnl=unrealized,
        )

    # ── Paper-specific helpers the bot drives ────────────────────────────────
    def mark(self, symbol: str, price: float) -> None:
        """Update the last price used for mark-to-market equity."""
        if price > 0:
            self._mark[symbol] = price

    def accrue_funding(self, symbol: str, funding_rate: float) -> float:
        """Apply one funding settlement on an open position (long pays when +)."""
        pos = self._positions.get(symbol)
        if pos is None or funding_rate == 0:
            return 0.0
        pay = -pos.side * pos.qty * pos.entry * funding_rate
        self._cash += pay
        self.total_funding += pay
        return pay

    def has_position(self, symbol: str) -> bool:
        return symbol in self._positions

    def restore_position(
        self, symbol: str, side: str, qty: float, entry: float, leverage: float
    ) -> None:
        """Rehydrate an open position on bot restart (from the trades table)."""
        self._positions[symbol] = _NetPosition(
            side=1 if side == "long" else -1, qty=qty, entry=entry, leverage=leverage
        )
        self._mark[symbol] = entry

    def set_cash(self, cash: float) -> None:
        self._cash = float(cash)

    # ── internals ────────────────────────────────────────────────────────────
    def _unrealized(self) -> float:
        total = 0.0
        for sym, p in self._positions.items():
            mark = self._mark.get(sym, p.entry)
            total += p.side * p.qty * (mark - p.entry)
        return total

    def _apply_fill(self, symbol: str, signed_qty: float, fill: float, leverage: float) -> float:
        """Net ``signed_qty`` into the position; realize pnl on any closed portion."""
        pos = self._positions.get(symbol)
        if pos is None:
            self._positions[symbol] = _NetPosition(
                side=_sign(signed_qty), qty=abs(signed_qty), entry=fill, leverage=leverage
            )
            return 0.0

        current = pos.side * pos.qty
        new = current + signed_qty
        realized = 0.0

        if current * new < 0 or new == 0:
            # Fully closed the existing position (and possibly reversed).
            realized = pos.side * pos.qty * (fill - pos.entry)
            if new == 0:
                del self._positions[symbol]
            else:
                self._positions[symbol] = _NetPosition(
                    side=_sign(new), qty=abs(new), entry=fill, leverage=leverage
                )
        elif abs(new) < abs(current):
            # Partial reduce on the same side.
            realized = pos.side * abs(signed_qty) * (fill - pos.entry)
            pos.qty = abs(new)
        else:
            # Adding to the same side → weighted-average entry.
            pos.entry = (pos.entry * pos.qty + fill * abs(signed_qty)) / abs(new)
            pos.qty = abs(new)
            pos.leverage = leverage

        self._cash += realized
        self.realized_pnl += realized
        return realized
