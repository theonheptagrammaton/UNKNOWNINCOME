"""The risk layer — the mandatory wall between the bot and every adapter (doc §9.4).

Pazarlıksız: *no order reaches an adapter except through here.* The bot holds a
:class:`RiskLayer`, never the adapter; the adapter is private to the layer and the
only method that calls ``place_order`` is :meth:`RiskLayer.submit`. An architecture
test proves the bot module never names ``place_order``; a runtime test proves a
breached limit both blocks the order and emits a ``risk_event``.

Every limit from §9.4 lives here: per-trade risk sizing (ATR default, decision #4),
max concurrent positions, daily-loss halt, total-drawdown kill, consecutive-loss
cooldown, price-deviation guard, the 10x/5x leverage ceiling, and the liquidation
buffer that auto-de-levers when the liquidation price would sit closer than 3×ATR
to entry (rule #11).

The layer is pure of I/O: it reads equity/positions from the adapter and returns
the ``risk_events`` to persist, so the bot owns all DB writes and the layer stays
trivially unit-testable and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel

from app.core.clock import Clock, now_ms
from app.execution.base import Balance, OrderRequest, OrderResult, Position
from app.execution.sizing import position_size


class RiskLimits(BaseModel):
    """All configurable risk limits (doc §9.4). Defaults are the doc's defaults."""

    per_trade_pct: float = 1.0  # equity risked per trade
    sizing: str = "atr"  # atr | fixed
    max_concurrent_positions: int = 5
    max_daily_loss_pct: float = 3.0  # → halt for the rest of the UTC day
    max_total_drawdown_pct: float = 15.0  # → kill switch
    consecutive_losses: int = 4  # → cooldown
    cooldown_hours: float = 12.0
    price_deviation_pct: float = 1.0  # reject if order price deviates > this
    leverage_cap: float = 10.0  # hard ceiling (rule #11)
    leverage_default: float = 5.0
    liq_buffer_atr_mult: float = 3.0  # liq price must be ≥ this×ATR from entry
    maintenance_margin_rate: float = 0.005  # ≈ Binance USDT-M for the liq estimate
    default_stop_atr_mult: float = 2.0  # stop distance when the genome gives none


@dataclass
class TradeIntent:
    """A sized-by-signal trading intent the bot hands to the wall."""

    strategy_version_id: str
    symbol: str
    action: str  # open_long | open_short | close_long | close_short
    reference_price: float
    ts: int
    atr: float | None = None  # ATR at the signal bar
    stop_distance: float | None = None  # explicit stop distance (overrides ATR mult)
    leverage: float = 5.0
    last_price: float | None = None  # for the price-deviation guard
    signal_id: str | None = None
    commission_bps: float | None = None  # per-genome cost overrides (paper sim)
    slippage_bps: float | None = None
    # Per-genome sizing (§8.1 risk block). None ⇒ fall back to the global RiskLimits,
    # so sizing matches the backtest that validated this genome (shared model).
    sizing: str | None = None  # "atr" | "fixed"
    per_trade_pct: float | None = None
    size_pct: float | None = None  # fixed-mode fraction

    @property
    def is_open(self) -> bool:
        return self.action.startswith("open_")

    @property
    def side(self) -> str:
        return "buy" if self.action in ("open_long", "close_short") else "sell"

    @property
    def position_side(self) -> str:
        return "long" if self.action in ("open_long", "close_long") else "short"


@dataclass
class RiskDecision:
    """Verdict + the sizing/leverage actually approved + events to persist."""

    approved: bool
    qty: float = 0.0
    leverage: float = 0.0
    reason: str | None = None
    events: list[dict] = field(default_factory=list)
    kill: bool = False  # request a kill switch (max total drawdown breached)


@dataclass
class _RiskState:
    peak_equity: float = 0.0
    day: str = ""  # UTC date of the daily anchor
    daily_start_equity: float = 0.0
    halted_day: str = ""  # date the daily-loss halt fired
    consecutive_losses: int = 0
    cooldown_until: int = 0  # ms


class RiskLayer:
    """Owns the adapter privately; the only sanctioned path to ``place_order``."""

    def __init__(
        self,
        adapter: object,
        limits: RiskLimits | None = None,
        *,
        mode: str = "paper",
        clock: Clock = now_ms,
    ) -> None:
        # Name-mangled so the bot cannot reach the adapter to bypass the wall.
        self.__adapter = adapter
        self.limits = limits or RiskLimits()
        self.mode = mode
        self._clock = clock
        self._state = _RiskState()

    # ── read-only pass-throughs the bot is allowed to use ────────────────────
    def balance(self) -> Balance:
        return self.__adapter.get_balance()

    def positions(self) -> list[Position]:
        return self.__adapter.get_positions()

    def mark(self, symbol: str, price: float) -> None:
        marker = getattr(self.__adapter, "mark", None)
        if callable(marker):
            marker(symbol, price)

    def accrue_funding(self, symbol: str, rate: float) -> float:
        accrue = getattr(self.__adapter, "accrue_funding", None)
        return accrue(symbol, rate) if callable(accrue) else 0.0

    def cancel_all(self) -> int:
        return self.__adapter.cancel_all()

    # ── the wall ─────────────────────────────────────────────────────────────
    def submit(self, intent: TradeIntent) -> tuple[RiskDecision, OrderResult | None]:
        """Evaluate every §9.4 limit; place the order only if approved."""
        decision = self.evaluate(intent)
        if not decision.approved:
            return decision, None
        result = self.__adapter.place_order(
            OrderRequest(
                symbol=intent.symbol,
                side=intent.side,
                qty=decision.qty,
                reduce_only=not intent.is_open,
                reference_price=intent.reference_price,
                leverage=decision.leverage,
                client_id=intent.signal_id,
                commission_bps=intent.commission_bps,
                slippage_bps=intent.slippage_bps,
            )
        )
        return decision, result

    def evaluate(self, intent: TradeIntent) -> RiskDecision:
        """Run the checks; closing/reducing intents skip the open-only gates."""
        events: list[dict] = []
        equity = self.__adapter.get_balance().equity
        self._roll_day(intent.ts, equity)
        self._state.peak_equity = max(self._state.peak_equity, equity)

        # Total drawdown → kill switch (checked for any intent; §9.4).
        if self._state.peak_equity > 0:
            dd = equity / self._state.peak_equity - 1.0
            if dd <= -self.limits.max_total_drawdown_pct / 100.0:
                events.append(_ev("max_drawdown", intent, {
                    "drawdown_pct": round(dd * 100, 4),
                    "limit_pct": self.limits.max_total_drawdown_pct,
                }))
                return RiskDecision(False, reason="max total drawdown", events=events, kill=True)

        # Closing/reducing an existing position is always allowed (it lowers risk).
        if not intent.is_open:
            return RiskDecision(True, qty=self._close_qty(intent), leverage=1.0, events=events)

        # ── open-only gates ──────────────────────────────────────────────────
        if self._state.halted_day == self._utc_date(intent.ts):
            events.append(_ev("daily_loss", intent, {"halted": True}))
            return RiskDecision(False, reason="halted for the day", events=events)

        # Daily loss → halt for the rest of the day.
        if self._state.daily_start_equity > 0:
            day_pnl = equity / self._state.daily_start_equity - 1.0
            if day_pnl <= -self.limits.max_daily_loss_pct / 100.0:
                self._state.halted_day = self._utc_date(intent.ts)
                events.append(_ev("daily_loss", intent, {
                    "day_pnl_pct": round(day_pnl * 100, 4),
                    "limit_pct": self.limits.max_daily_loss_pct,
                }))
                return RiskDecision(False, reason="daily loss limit", events=events)

        # Consecutive-loss cooldown.
        if intent.ts < self._state.cooldown_until:
            events.append(_ev("cooldown", intent, {
                "until_ts": self._state.cooldown_until,
                "consecutive_losses": self._state.consecutive_losses,
            }))
            return RiskDecision(False, reason="cooldown active", events=events)

        # Price-deviation guard.
        if intent.last_price and intent.last_price > 0:
            dev = abs(intent.reference_price - intent.last_price) / intent.last_price
            if dev > self.limits.price_deviation_pct / 100.0:
                events.append(_ev("price_guard", intent, {
                    "deviation_pct": round(dev * 100, 4),
                    "limit_pct": self.limits.price_deviation_pct,
                }))
                return RiskDecision(False, reason="price deviation", events=events)

        # Max concurrent positions (only counts *new* symbols).
        open_symbols = {p.symbol for p in self.__adapter.get_positions()}
        is_new_symbol = intent.symbol not in open_symbols
        if is_new_symbol and len(open_symbols) >= self.limits.max_concurrent_positions:
            events.append(_ev("max_positions", intent, {
                "open": len(open_symbols), "limit": self.limits.max_concurrent_positions,
            }))
            return RiskDecision(False, reason="max concurrent positions", events=events)

        # Leverage ceiling + liquidation buffer (auto de-lever, rule #11).
        leverage = min(max(intent.leverage, 1.0), self.limits.leverage_cap)
        if leverage < intent.leverage:
            events.append(_ev("leverage_cap", intent, {
                "requested": intent.leverage, "capped": leverage,
            }))
        leverage = self._apply_liq_buffer(intent, leverage, events)

        # Position sizing (ATR default, decision #4).
        qty = self._size(equity, intent, leverage)
        if qty <= 0:
            events.append(_ev("insufficient_equity", intent, {"equity": equity, "qty": qty}))
            return RiskDecision(False, reason="insufficient equity / zero size", events=events)

        return RiskDecision(True, qty=qty, leverage=leverage, events=events)

    # ── trade-result feedback (drives the cooldown) ──────────────────────────
    def register_trade_result(self, pnl: float, ts: int) -> None:
        """Update the consecutive-loss streak; arm the cooldown on the Nth loss."""
        if pnl < 0:
            self._state.consecutive_losses += 1
            if self._state.consecutive_losses >= self.limits.consecutive_losses:
                self._state.cooldown_until = ts + int(self.limits.cooldown_hours * 3600 * 1000)
                self._state.consecutive_losses = 0
        else:
            self._state.consecutive_losses = 0

    def seed_state(
        self,
        *,
        peak_equity: float | None = None,
        daily_start_equity: float | None = None,
        day: str | None = None,
        cooldown_until: int | None = None,
        consecutive_losses: int | None = None,
    ) -> None:
        """Rehydrate risk state on bot restart so limits survive a 72h run."""
        s = self._state
        if peak_equity is not None:
            s.peak_equity = peak_equity
        if daily_start_equity is not None:
            s.daily_start_equity = daily_start_equity
        if day is not None:
            s.day = day
        if cooldown_until is not None:
            s.cooldown_until = cooldown_until
        if consecutive_losses is not None:
            s.consecutive_losses = consecutive_losses

    # ── internals ────────────────────────────────────────────────────────────
    def _roll_day(self, ts: int, equity: float) -> None:
        date = self._utc_date(ts)
        if self._state.day != date:
            self._state.day = date
            self._state.daily_start_equity = equity
        if self._state.peak_equity == 0.0:
            self._state.peak_equity = equity

    @staticmethod
    def _utc_date(ts: int) -> str:
        return datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d")

    def _stop_distance(self, intent: TradeIntent) -> float | None:
        if intent.stop_distance and intent.stop_distance > 0:
            return intent.stop_distance
        if intent.atr and intent.atr > 0:
            return self.limits.default_stop_atr_mult * intent.atr
        return None

    def _size(self, equity: float, intent: TradeIntent, leverage: float) -> float:
        """Position size via the shared model (:mod:`app.execution.sizing`).

        The genome's sizing (carried on the intent) wins over the global limits, so a
        paper/live order is sized exactly like the backtest that validated the genome.
        """
        sizing = intent.sizing or self.limits.sizing
        per_trade = (
            intent.per_trade_pct if intent.per_trade_pct is not None
            else self.limits.per_trade_pct
        )
        return position_size(
            equity=equity,
            price=intent.reference_price,
            leverage=leverage,
            sizing=sizing,
            per_trade_pct=per_trade,
            stop_distance=self._stop_distance(intent),
            fixed_fraction=intent.size_pct if intent.size_pct is not None else 1.0,
        )

    def _close_qty(self, intent: TradeIntent) -> float:
        for p in self.__adapter.get_positions():
            if p.symbol == intent.symbol:
                return p.qty
        return 0.0

    def _apply_liq_buffer(
        self, intent: TradeIntent, leverage: float, events: list[dict]
    ) -> float:
        """Cap leverage so the liquidation price sits ≥ 3×ATR from entry (rule #11)."""
        atr = intent.atr
        price = intent.reference_price
        if not atr or atr <= 0 or price <= 0:
            return leverage  # cannot estimate without ATR → leave as capped
        # Isolated-margin liq distance ≈ entry × (1/lev − mm). Require ≥ k×ATR:
        #   1/lev ≥ k·ATR/entry + mm  ⇒  lev ≤ 1 / (k·ATR/entry + mm).
        k = self.limits.liq_buffer_atr_mult
        mm = self.limits.maintenance_margin_rate
        max_lev = 1.0 / (k * atr / price + mm)
        safe = max(1.0, min(leverage, max_lev))
        if safe < leverage - 1e-9:
            events.append(_ev("liq_buffer", intent, {
                "from_leverage": round(leverage, 4),
                "to_leverage": round(safe, 4),
                "atr": atr,
                "buffer_atr_mult": k,
            }))
        return safe


def _ev(event_type: str, intent: TradeIntent, detail: dict) -> dict:
    """Assemble a risk_event payload the bot will persist."""
    return {
        "type": event_type,
        "symbol": intent.symbol,
        "strategy_version_id": intent.strategy_version_id,
        "detail": detail,
        "ts": intent.ts,
    }
