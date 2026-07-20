"""The paper trading bot engine (doc §9.1, §9.4, §9.6, §10.2).

One deterministic cycle is :meth:`BotEngine.tick`; :meth:`BotEngine.run` is a
supervised, kill-switch-aware loop that ticks forever (the 72h soak). Each tick:

1. Honour the kill switch first — if engaged, cancel orders, close the entry path,
   record it and stop (checked again every ``kill_poll`` seconds so any of the four
   channels halts the bot in < 2 s).
2. Read the global mode; for every strategy whose effective mode ≥ paper (doc §9.6),
   load its **active** version's genome (so an edited genome hot-reloads with no
   restart), evaluate the just-closed bar and, on a signal, route the intent through
   the risk wall (:class:`RiskLayer`) to the :class:`PaperAdapter`.
3. Persist the signal (with its non-negotiable ``reason`` + ``indicator_snapshot``),
   the order, the trade and any ``risk_events`` — paper rows, same tables as live.
4. Snapshot equity for the curve.

The engine holds a :class:`RiskLayer`, never the adapter, so no order can bypass the
wall (proved by an architecture test).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backtest.config import RunConfig
from app.backtest.engine import _atr
from app.backtest.runner import _indicator_frames
from app.bot.killswitch import KillSwitch
from app.bot.mode import effective_mode, get_global_mode, should_trade
from app.bot.notifier import NullNotifier
from app.bot.signals import LatestSignal, evaluate_latest
from app.core.clock import Clock, now_ms
from app.core.config import settings
from app.data.duckdb_query import query_funding, query_ohlcv
from app.execution.paper import PaperAdapter
from app.execution.risk import RiskLayer, RiskLimits, TradeIntent
from app.models.risk import RiskEvent
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import EquitySnapshot, Order, Signal, Trade
from app.strategy.genome import genome_config

logger = logging.getLogger(__name__)


@dataclass
class TickReport:
    """What one tick did — handy for tests and the run log."""

    ts: int
    global_mode: str
    evaluated: int = 0
    signals: int = 0
    orders: int = 0
    rejected: int = 0
    killed: bool = False
    equity: float | None = None
    notes: list[str] = field(default_factory=list)


class BotEngine:
    """Owns the paper adapter behind the risk wall and drives the trading loop."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        notifier: object | None = None,
        clock: Clock = now_ms,
        killswitch: KillSwitch | None = None,
        limits: RiskLimits | None = None,
        tick_seconds: float | None = None,
        kill_poll_seconds: float | None = None,
        initial_cash: float | None = None,
    ) -> None:
        self._sf = session_factory
        self._notifier = notifier or NullNotifier()
        self._clock = clock
        self._killswitch = killswitch or KillSwitch()
        self._tick_seconds = tick_seconds or settings.bot_tick_seconds
        self._kill_poll = kill_poll_seconds or settings.bot_killswitch_poll_seconds
        cash = initial_cash if initial_cash is not None else settings.bot_paper_initial_cash
        self._adapter = PaperAdapter(cash)
        self._risk = RiskLayer(self._adapter, limits or RiskLimits(), mode="paper", clock=clock)
        self._processed: dict[str, int] = {}  # key → last bar ts acted on
        self._bands: dict[str, tuple[float | None, float | None, str]] = {}  # stop,target,side
        self._last_funding_ts: dict[str, int] = {}
        self._kill_handled = False
        self._rehydrated = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def rehydrate(self, session: AsyncSession) -> None:
        """Restore adapter positions + cash + risk peak so limits survive a restart."""
        trades = (
            await session.execute(
                select(Trade).where(Trade.mode == "paper", Trade.status == "open")
            )
        ).scalars().all()
        for t in trades:
            self._adapter.restore_position(t.symbol, t.side, t.qty, t.entry_price, t.leverage)
        last_eq = (
            await session.execute(
                select(EquitySnapshot)
                .where(EquitySnapshot.mode == "paper")
                .order_by(EquitySnapshot.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_eq is not None:
            # Positions are restored at entry (0 unrealized), so cash == equity here.
            self._adapter.set_cash(last_eq.equity)
            peak = max(last_eq.equity, self._adapter.get_balance().equity)
            self._risk.seed_state(peak_equity=peak)
        self._rehydrated = True

    def reload_limits(self, limits: RiskLimits) -> None:
        self._risk.limits = limits

    # ── one cycle ────────────────────────────────────────────────────────────
    async def tick(self, session: AsyncSession | None = None) -> TickReport:
        """Run exactly one cycle. Opens its own session unless one is supplied."""
        if session is None:
            async with self._sf() as own:
                report = await self._tick(own)
                await own.commit()
                return report
        report = await self._tick(session)
        return report

    async def _tick(self, session: AsyncSession) -> TickReport:
        ts = self._clock()
        if self._killswitch.is_engaged():
            await self._handle_kill(session, ts)
            return TickReport(ts=ts, global_mode="off", killed=True)
        self._kill_handled = False  # re-armed once the switch clears

        global_mode = await get_global_mode(session)
        report = TickReport(ts=ts, global_mode=global_mode)

        for strat, version, config in await self._load_active(session, global_mode):
            report.evaluated += 1
            try:
                await self._evaluate(session, strat, version, config, ts, report)
            except Exception as exc:  # pragma: no cover - per-strategy resilience
                logger.warning("strategy %s tick failed: %s", strat.id, exc)
                report.notes.append(f"{strat.id}:{type(exc).__name__}")

        bal = self._adapter.get_balance()
        report.equity = bal.equity
        session.add(
            EquitySnapshot(ts=ts, mode="paper", equity=bal.equity, exposure=self._exposure())
        )
        return report

    async def _load_active(
        self, session: AsyncSession, global_mode: str
    ) -> list[tuple[Strategy, StrategyVersion, RunConfig]]:
        """Strategies whose effective mode ≥ paper, with their active genome (hot-reload)."""
        strategies = (await session.execute(select(Strategy))).scalars().all()
        out: list[tuple[Strategy, StrategyVersion, RunConfig]] = []
        for strat in strategies:
            eff = effective_mode(global_mode, strat.mode)
            if not should_trade(eff) or strat.active_version_id is None:
                continue
            version = await session.get(StrategyVersion, strat.active_version_id)
            if version is None or version.status == "retired":
                continue
            try:
                config = genome_config(version.genome)
            except Exception as exc:  # pragma: no cover - bad genome guard
                logger.warning("strategy %s has an invalid genome: %s", strat.id, exc)
                continue
            out.append((strat, version, config))
        return out

    # ── per-strategy evaluation ──────────────────────────────────────────────
    async def _evaluate(
        self,
        session: AsyncSession,
        strat: Strategy,
        version: StrategyVersion,
        config: RunConfig,
        ts: int,
        report: TickReport,
    ) -> None:
        ohlcv = query_ohlcv(config.market, config.symbol, config.tf).reset_index(drop=True)
        if len(ohlcv) < 2:
            return
        key = f"{version.id}:{config.symbol}"
        last_bar_ts = int(ohlcv["ts"].iloc[-1])
        close = float(ohlcv["close"].iloc[-1])
        self._adapter.mark(config.symbol, close)

        # Act once per closed bar (signal at close → fill next tick, rule #1).
        if self._processed.get(key) == last_bar_ts:
            return
        self._processed[key] = last_bar_ts

        frames = _indicator_frames(config, ohlcv)
        sig = evaluate_latest(config, ohlcv, frames)
        if sig is None:
            return
        await self._accrue_funding(session, config, ts)

        open_trade = await self._open_trade(session, strat.id, config.symbol)
        action, reason = self._decide(config, sig, ohlcv, key, open_trade)
        if action is None:
            return

        report.signals += 1
        atr = self._atr_at(ohlcv, config)
        intent = TradeIntent(
            strategy_version_id=version.id,
            symbol=config.symbol,
            action=action,
            reference_price=close,
            ts=ts,
            atr=atr,
            stop_distance=self._stop_distance(config, atr),
            leverage=config.capital.leverage or self._risk.limits.leverage_default,
            # Market order fills at the current price, so the reference *is* the last
            # price → the deviation guard only trips on a genuinely stale reference.
            last_price=close,
            commission_bps=config.costs.commission_bps,
            slippage_bps=(
                config.costs.slippage_bps if config.costs.slippage_model == "fixed_bps" else None
            ),
        )
        decision, result = self._risk.submit(intent)

        # Persist the risk events regardless of outcome (decision-log evidence).
        for ev in decision.events:
            session.add(RiskEvent(
                ts=ev["ts"], type=ev["type"], mode="paper", symbol=ev["symbol"],
                strategy_version_id=ev["strategy_version_id"], detail=ev["detail"],
            ))
        if decision.kill:
            await self._trigger_kill(session, ts, "max total drawdown")

        signal = Signal(
            strategy_version_id=version.id,
            strategy_id=strat.id,
            ts=sig.ts,
            symbol=config.symbol,
            tf=config.tf,
            mode="paper",
            action=action,
            reason=reason,
            indicator_snapshot=sig.snapshot,
            outcome="filled" if (decision.approved and result and result.accepted) else "rejected",
            outcome_detail=None if decision.approved else {"reason": decision.reason,
                                                            "events": decision.events},
        )
        session.add(signal)
        await session.flush()

        if not decision.approved or result is None or not result.accepted:
            report.rejected += 1
            session.add(Order(
                mode="paper", signal_id=signal.id, strategy_version_id=version.id,
                symbol=config.symbol, side=intent.side, qty=decision.qty,
                status="rejected", detail={"reason": decision.reason},
            ))
            await self._notifier.notify(
                f"⛔ {config.symbol} {action} rejected by risk: {decision.reason}"
            )
            return

        report.orders += 1
        fill = result.fill
        session.add(Order(
            mode="paper", signal_id=signal.id, strategy_version_id=version.id,
            symbol=config.symbol, side=intent.side, qty=fill.qty, price=fill.price,
            status="filled", detail={"commission": fill.commission, "slippage": fill.slippage_cost},
        ))
        await self._apply_fill(session, strat, version, config, action, intent, fill, open_trade)

    def _decide(
        self,
        config: RunConfig,
        sig: LatestSignal,
        ohlcv: pd.DataFrame,
        key: str,
        open_trade: Trade | None,
    ) -> tuple[str | None, dict]:
        """Choose the action for this bar and assemble a non-empty reason."""
        close = float(ohlcv["close"].iloc[-1])
        if open_trade is None:
            if sig.long_entry:
                return "open_long", {"long_entry": sig.reason.get("long_entry", [])}
            if sig.short_entry:
                return "open_short", {"short_entry": sig.reason.get("short_entry", [])}
            return None, {}

        side = open_trade.side
        band = self._bands.get(key)
        risk_hit, hit_kind = self._band_hit(band, side, close)
        if side == "long" and (sig.long_exit or sig.short_entry or risk_hit):
            reason = {"long_exit": sig.reason.get("long_exit", [])}
            if sig.short_entry:
                reason["short_entry"] = sig.reason.get("short_entry", [])
            if risk_hit:
                reason["risk_exit"] = _risk_reason(hit_kind, band)
            return "close_long", _nonempty(reason, hit_kind, band)
        if side == "short" and (sig.short_exit or sig.long_entry or risk_hit):
            reason = {"short_exit": sig.reason.get("short_exit", [])}
            if sig.long_entry:
                reason["long_entry"] = sig.reason.get("long_entry", [])
            if risk_hit:
                reason["risk_exit"] = _risk_reason(hit_kind, band)
            return "close_short", _nonempty(reason, hit_kind, band)
        return None, {}

    async def _apply_fill(
        self,
        session: AsyncSession,
        strat: Strategy,
        version: StrategyVersion,
        config: RunConfig,
        action: str,
        intent: TradeIntent,
        fill: object,
        open_trade: Trade | None,
    ) -> None:
        """Update the trades table + risk feedback + notifications after a fill."""
        key = f"{version.id}:{config.symbol}"
        if action.startswith("open_"):
            trade = Trade(
                mode="paper", strategy_version_id=version.id, strategy_id=strat.id,
                symbol=config.symbol, side=intent.position_side, qty=fill.qty,
                leverage=intent.leverage, entry_price=fill.price, entry_ts=intent.ts,
                fees=fill.commission, status="open",
            )
            session.add(trade)
            self._set_band(config, intent, key)
            await self._notifier.notify(
                f"✅ {config.symbol} {intent.position_side} @ {fill.price:.4f} "
                f"×{fill.qty:.4f} (paper)"
            )
        else:  # close
            if open_trade is not None:
                open_trade.exit_price = fill.price
                open_trade.exit_ts = intent.ts
                open_trade.fees += fill.commission
                open_trade.pnl = fill.realized_pnl - open_trade.fees + open_trade.funding
                open_trade.status = "closed"
                self._risk.register_trade_result(open_trade.pnl, intent.ts)
                await self._notifier.notify(
                    f"💵 {config.symbol} closed @ {fill.price:.4f} "
                    f"pnl {open_trade.pnl:+.2f} (paper)"
                )
            self._bands.pop(key, None)

    # ── kill switch ──────────────────────────────────────────────────────────
    async def _handle_kill(self, session: AsyncSession, ts: int) -> None:
        """React to an engaged kill switch: cancel, halt entry path, record once."""
        if self._kill_handled:
            return
        self._kill_handled = True
        self._risk.cancel_all()
        session.add(RiskEvent(ts=ts, type="killswitch", mode="paper", detail={"engaged": True}))
        await self._notifier.notify("🛑 KILL SWITCH engaged — new orders halted (paper)")
        await session.commit()

    async def _trigger_kill(self, session: AsyncSession, ts: int, reason: str) -> None:
        """Engage the kill switch from inside the bot (max drawdown breach)."""
        from app.bot import killswitch as ks

        await ks.engage(session, actor="system", reason=reason)
        await self._handle_kill(session, ts)

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _open_trade(
        self, session: AsyncSession, strategy_id: str, symbol: str
    ) -> Trade | None:
        return (
            await session.execute(
                select(Trade)
                .where(Trade.strategy_id == strategy_id, Trade.symbol == symbol,
                       Trade.mode == "paper", Trade.status == "open")
                .order_by(Trade.entry_ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def _atr_at(self, ohlcv: pd.DataFrame, config: RunConfig) -> float | None:
        length = config.risk_exit.atr_length or config.costs.atr_length
        atr = _atr(
            ohlcv["high"].to_numpy("float64"),
            ohlcv["low"].to_numpy("float64"),
            ohlcv["close"].to_numpy("float64"),
            length,
        )
        val = float(atr[-1])
        return val if val == val else None  # NaN guard

    def _stop_distance(self, config: RunConfig, atr: float | None) -> float | None:
        if config.risk_exit.atr_stop_mult and atr:
            return config.risk_exit.atr_stop_mult * atr
        return None

    def _set_band(self, config: RunConfig, intent: TradeIntent, key: str) -> None:
        atr = intent.atr
        if not (config.risk_exit.enabled and atr):
            self._bands.pop(key, None)
            return
        side = intent.position_side
        entry = intent.reference_price
        sign = 1 if side == "long" else -1
        re = config.risk_exit
        stop = (entry - sign * re.atr_stop_mult * atr) if re.atr_stop_mult else None
        target = (entry + sign * re.atr_target_mult * atr) if re.atr_target_mult else None
        self._bands[key] = (stop, target, side)

    @staticmethod
    def _band_hit(
        band: tuple[float | None, float | None, str] | None, side: str, close: float
    ) -> tuple[bool, str]:
        if band is None:
            return False, ""
        stop, target, _ = band
        if side == "long":
            if stop is not None and close <= stop:
                return True, "atr_stop"
            if target is not None and close >= target:
                return True, "atr_target"
        else:
            if stop is not None and close >= stop:
                return True, "atr_stop"
            if target is not None and close <= target:
                return True, "atr_target"
        return False, ""

    async def _accrue_funding(self, session: AsyncSession, config: RunConfig, now_ts: int) -> None:
        """Apply new perpetual funding settlements on the open position (best effort)."""
        if not config.costs.funding_enabled or not self._adapter.has_position(config.symbol):
            return
        fund = query_funding(config.market, config.symbol)
        if fund is None or fund.empty:
            return
        last = self._last_funding_ts.get(config.symbol, 0)
        due = fund[(fund["ts"] > last) & (fund["ts"] <= now_ts)]
        if due.empty:
            return
        trade = await self._open_trade_any(session, config.symbol)
        for _, row in due.iterrows():
            pay = self._adapter.accrue_funding(config.symbol, float(row["funding_rate"]))
            if trade is not None:
                trade.funding += pay
        self._last_funding_ts[config.symbol] = int(due["ts"].max())

    async def _open_trade_any(self, session: AsyncSession, symbol: str) -> Trade | None:
        return (
            await session.execute(
                select(Trade)
                .where(Trade.symbol == symbol, Trade.mode == "paper", Trade.status == "open")
                .order_by(Trade.entry_ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def _exposure(self) -> float:
        return sum(p.qty * (p.mark_price or p.entry_price) for p in self._adapter.get_positions())

    # ── the loop ─────────────────────────────────────────────────────────────
    async def run(
        self,
        *,
        stop: Callable[[], bool],
        sleep: Callable[[float], Awaitable[None]],
        max_ticks: int | None = None,
    ) -> int:
        """Kill-aware loop: poll the switch every ``kill_poll``, tick every ``tick_seconds``.

        Returns the number of ticks executed. ``max_ticks`` bounds test runs; in
        production it is ``None`` (run forever, doc §15 Faz-5 72h soak).
        """
        ticks = 0
        last_tick = 0.0
        elapsed = 0.0
        while not stop() and (max_ticks is None or ticks < max_ticks):
            if self._killswitch.is_engaged():
                async with self._sf() as session:
                    await self._handle_kill(session, self._clock())
                await sleep(self._kill_poll)
                elapsed += self._kill_poll
                continue
            if elapsed - last_tick >= self._tick_seconds or ticks == 0:
                try:
                    await self.tick()
                except Exception as exc:  # pragma: no cover - loop resilience
                    logger.warning("bot tick failed: %s", exc)
                last_tick = elapsed
                ticks += 1
            await sleep(self._kill_poll)
            elapsed += self._kill_poll
        return ticks


def _risk_reason(hit_kind: str, band: tuple | None) -> list[dict]:
    """Reason record for an ATR stop/target exit (band = (stop, target, side))."""
    level = None if band is None else (band[0] if hit_kind == "atr_stop" else band[1])
    return [{"primitive": hit_kind, "args": {"level": level}}]


def _nonempty(reason: dict, hit_kind: str, band: tuple | None) -> dict:
    """Guarantee a non-empty reason (pazarlıksız): fall back to the risk-exit hit."""
    pruned = {k: v for k, v in reason.items() if v}
    if pruned:
        return pruned
    if hit_kind and band is not None:
        return {"risk_exit": _risk_reason(hit_kind, band)}
    return {"exit": [{"primitive": "signal", "args": {}}]}
