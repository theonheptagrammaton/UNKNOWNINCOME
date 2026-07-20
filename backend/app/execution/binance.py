"""Binance USDT-M futures execution adapter (ccxt) — the live venue (doc §9.2–9.4).

Implements the same synchronous :class:`~app.execution.base.ExecutionAdapter` surface
as the paper sim, so the risk wall and bot are unchanged — only ``mode`` differs and
rows land in the same tables with ``mode="live"``. Pazarlıksız choices baked in:

* **Isolated margin + one-way** position mode (rule #11) are set per symbol before the
  first order and never changed to cross.
* **Leverage** is whatever the risk wall approved (it has already applied the 10x cap
  and the liquidation-buffer derating); the adapter just sets it on the venue.
* Every exchange call goes through :func:`call_resilient` (retry + circuit breaker), so
  a rate-limit or network blip is retried and a sustained outage fails fast instead of
  hammering the venue.
* Credentials are registered with the log-redaction filter the moment the adapter is
  built, so no key can reach a log line.

Testnet is the default target (``set_sandbox_mode``); mainnet is a second, deliberate
config switch. Positions and balance are read live from the exchange (the reconciliation
source of truth); a light local entry mirror exists only to attribute realized PnL on a
close, and is reseeded from the exchange on restart.
"""

from __future__ import annotations

import logging

import ccxt  # synchronous client — the execution surface is sync (see resilience.py)

from app.core.config import settings
from app.core.logging import register_secret
from app.data.adapters.binance_usdm import normalize_symbol
from app.execution.base import Balance, Fill, OrderRequest, OrderResult, Position
from app.execution.resilience import CircuitBreaker, call_resilient

logger = logging.getLogger(__name__)


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


class _Mirror:
    """Local average-entry mirror per symbol — only to attribute realized PnL."""

    __slots__ = ("side", "qty", "entry")

    def __init__(self, side: int, qty: float, entry: float) -> None:
        self.side = side  # +1 long / −1 short
        self.qty = qty
        self.entry = entry


class BinanceFuturesAdapter:
    """Live ccxt adapter for Binance USDT-M perpetuals (isolated, one-way)."""

    mode = "live"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        testnet: bool = True,
        leverage_default: float = 5.0,
        exchange: object | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        # Redact the credentials from every log line before anything can log them.
        register_secret(api_key, api_secret)
        self.testnet = testnet
        self._leverage_default = leverage_default
        self._ex = exchange or ccxt.binanceusdm(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
        )
        if exchange is None and testnet:
            self._ex.set_sandbox_mode(True)
        self._breaker = breaker or CircuitBreaker(
            threshold=settings.live_circuit_breaker_threshold,
            cooldown_seconds=settings.live_circuit_breaker_cooldown_seconds,
        )
        self._markets_loaded = False
        self._oneway_set = False
        self._symbol_leverage: dict[str, float] = {}  # ccxt symbol → leverage set
        self._mirror: dict[str, _Mirror] = {}  # normalized symbol → entry mirror

    # ── ExecutionAdapter surface ─────────────────────────────────────────────
    def place_order(self, order: OrderRequest) -> OrderResult:
        """Market order on the venue; isolated/one-way/leverage set first (rule #11)."""
        if order.qty <= 0:
            return OrderResult(False, None, "rejected", reason="live: non-positive qty")
        try:
            ccxt_symbol = self._ensure_symbol(order.symbol, order.leverage, order.reduce_only)
            amount = float(self._ex.amount_to_precision(ccxt_symbol, order.qty))
            if amount <= 0:
                return OrderResult(False, None, "rejected", reason="live: qty below min precision")
            params = {"reduceOnly": bool(order.reduce_only)}
            raw = self._call(
                lambda: self._ex.create_order(
                    ccxt_symbol, "market", order.side, amount, None, params
                ),
                label=f"create_order {order.symbol} {order.side}",
            )
        except Exception as exc:  # noqa: BLE001 - surface as a rejection, never crash the bot
            logger.warning("live order rejected for %s: %s", order.symbol, type(exc).__name__)
            return OrderResult(False, None, "rejected", reason=f"live: {type(exc).__name__}")

        fill = self._to_fill(order, raw)
        realized = self._apply_mirror(order.symbol, order.side, fill.qty, fill.price)
        fill.realized_pnl = realized
        logger.info(
            "live fill %s %s qty=%.6f @ %.6f lev=%.1f reduce_only=%s (testnet=%s)",
            order.symbol, order.side, fill.qty, fill.price, order.leverage,
            order.reduce_only, self.testnet,
        )
        return OrderResult(True, str(raw.get("id")), "filled", fill=fill)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel one resting order (market orders rarely rest; best-effort)."""
        try:
            self._call(lambda: self._ex.cancel_order(order_id), label="cancel_order")
            return True
        except Exception:  # noqa: BLE001 - already gone / unknown id
            return False

    def cancel_all(self) -> int:
        """Cancel every open order across symbols (kill-switch path, doc §9.4)."""
        try:
            open_orders = self._call(
                lambda: self._ex.fetch_open_orders(), label="fetch_open_orders"
            )
        except Exception:  # noqa: BLE001 - if we cannot read, we cannot cancel
            return 0
        cancelled = 0
        for o in open_orders:
            try:
                self._call(
                    lambda oid=o["id"], sym=o["symbol"]: self._ex.cancel_order(oid, sym),
                    label="cancel_order",
                )
                cancelled += 1
            except Exception:  # noqa: BLE001 - continue cancelling the rest
                continue
        return cancelled

    def get_positions(self) -> list[Position]:
        """Live open positions from the venue (reconciliation source of truth)."""
        try:
            raw = self._call(lambda: self._ex.fetch_positions(), label="fetch_positions")
        except Exception:  # noqa: BLE001 - no positions we can see ⇒ report none
            return []
        out: list[Position] = []
        for p in raw:
            contracts = float(p.get("contracts") or 0.0)
            if contracts == 0:
                continue
            out.append(
                Position(
                    symbol=normalize_symbol(p.get("symbol", "")),
                    side="long" if (p.get("side") == "long") else "short",
                    qty=abs(contracts),
                    entry_price=float(p.get("entryPrice") or 0.0),
                    leverage=float(p.get("leverage") or self._leverage_default),
                    mark_price=float(p.get("markPrice")) if p.get("markPrice") else None,
                )
            )
        return out

    def get_balance(self) -> Balance:
        """Account equity/cash/unrealized from the venue (USDT-M margin balance)."""
        raw = self._call(lambda: self._ex.fetch_balance(), label="fetch_balance")
        info = raw.get("info", {}) if isinstance(raw, dict) else {}
        equity = _f(info.get("totalMarginBalance"))
        cash = _f(info.get("totalWalletBalance"))
        unrealized = _f(info.get("totalUnrealizedProfit"))
        if equity is None:  # fall back to the unified structure
            usdt = raw.get(settings.universe_quote, {}) if isinstance(raw, dict) else {}
            cash = float(usdt.get("total") or 0.0)
            equity = cash
            unrealized = 0.0
        return Balance(equity=equity, cash=cash or 0.0, unrealized_pnl=unrealized or 0.0)

    # ── reconciliation helper (bot restart, doc §9.2 emir-durum mutabakatı) ───
    def restore_mirror(self, symbol: str, side: str, qty: float, entry: float) -> None:
        """Seed the realized-PnL mirror from a known open trade on restart."""
        self._mirror[symbol] = _Mirror(1 if side == "long" else -1, qty, entry)

    def close(self) -> None:
        """Sync ccxt keeps no session to close; provided for interface symmetry."""

    # ── internals ─────────────────────────────────────────────────────────────
    def _call(self, fn, *, label: str):
        return call_resilient(
            fn,
            breaker=self._breaker,
            max_retries=settings.live_max_retries,
            backoff_seconds=settings.live_retry_backoff_seconds,
            label=label,
        )

    def _load_markets(self) -> None:
        if not self._markets_loaded:
            self._call(lambda: self._ex.load_markets(), label="load_markets")
            self._markets_loaded = True

    def _to_ccxt_symbol(self, symbol: str) -> str:
        """``BTCUSDT`` → the ccxt unified symbol (``BTC/USDT:USDT``)."""
        self._load_markets()
        market = self._ex.markets_by_id.get(symbol)
        if market:
            m = market[0] if isinstance(market, list) else market
            return m["symbol"]
        quote = settings.universe_quote
        base = symbol[: -len(quote)] if symbol.endswith(quote) else symbol
        return f"{base}/{quote}:{quote}"

    def _ensure_symbol(self, symbol: str, leverage: float, reduce_only: bool) -> str:
        """Set one-way mode (account) + isolated margin + leverage before trading."""
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        if not self._oneway_set:
            self._safe_venue_config(
                lambda: self._ex.set_position_mode(False),  # hedged=False ⇒ one-way
                "set_position_mode(one-way)",
            )
            self._oneway_set = True
        if reduce_only:
            return ccxt_symbol  # closing: margin/leverage already set at open
        lev = max(1, int(round(leverage)))
        if self._symbol_leverage.get(ccxt_symbol) != lev:
            self._safe_venue_config(
                lambda: self._ex.set_margin_mode(settings.live_margin_mode, ccxt_symbol),
                f"set_margin_mode({settings.live_margin_mode}) {symbol}",
            )
            self._safe_venue_config(
                lambda: self._ex.set_leverage(lev, ccxt_symbol),
                f"set_leverage({lev}) {symbol}",
            )
            self._symbol_leverage[ccxt_symbol] = lev
        return ccxt_symbol

    def _safe_venue_config(self, fn, label: str) -> None:
        """Apply a venue config call; tolerate 'no need to change' (already set)."""
        try:
            self._call(fn, label=label)
            logger.info("live venue config: %s (testnet=%s)", label, self.testnet)
        except Exception as exc:  # noqa: BLE001 - idempotent config is allowed to no-op
            msg = str(exc).lower()
            if "no need to change" in msg or "-4059" in msg or "-4046" in msg:
                logger.info("live venue config already set: %s", label)
                return
            logger.warning("live venue config failed: %s (%s)", label, type(exc).__name__)
            raise

    def _to_fill(self, order: OrderRequest, raw: dict) -> Fill:
        """Parse a ccxt order response into a :class:`Fill` (best-effort reconcile)."""
        price = _f(raw.get("average")) or _f(raw.get("price")) or (order.reference_price or 0.0)
        qty = _f(raw.get("filled")) or order.qty
        commission = 0.0
        fee = raw.get("fee") or {}
        if fee.get("cost") is not None:
            commission = abs(float(fee["cost"]))
        for f in raw.get("fees", []) or []:
            if f.get("cost") is not None:
                commission += abs(float(f["cost"]))
        return Fill(price=float(price), qty=float(qty), commission=commission, slippage_cost=0.0)

    def _apply_mirror(self, symbol: str, side: str, qty: float, fill: float) -> float:
        """Net the fill into the local mirror; return realized PnL on any closed part."""
        signed = qty if side == "buy" else -qty
        pos = self._mirror.get(symbol)
        if pos is None:
            self._mirror[symbol] = _Mirror(_sign(signed), abs(signed), fill)
            return 0.0
        current = pos.side * pos.qty
        new = current + signed
        realized = 0.0
        if current * new < 0 or new == 0:  # closed (and maybe reversed)
            realized = pos.side * pos.qty * (fill - pos.entry)
            if new == 0:
                del self._mirror[symbol]
            else:
                self._mirror[symbol] = _Mirror(_sign(new), abs(new), fill)
        elif abs(new) < abs(current):  # partial reduce
            realized = pos.side * abs(signed) * (fill - pos.entry)
            pos.qty = abs(new)
        else:  # add to same side → weighted-average entry
            pos.entry = (pos.entry * pos.qty + fill * abs(signed)) / abs(new)
            pos.qty = abs(new)
        return realized


def _f(value: object) -> float | None:
    """Best-effort float parse (ccxt hands back strings in ``info``)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
