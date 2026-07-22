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
from app.bot.mode import effective_mode, execution_mode, get_global_mode, live_enabled, should_trade
from app.bot.notifier import NullNotifier
from app.bot.signals import LatestSignal, evaluate_latest
from app.core.clock import Clock, now_ms
from app.core.config import settings
from app.core.settings_store import KEY_REGIME_LOCK, get_setting
from app.data.duckdb_query import query_funding, query_ohlcv
from app.execution.paper import PaperAdapter
from app.execution.risk import RiskLayer, RiskLimits, TradeIntent
from app.execution.slippage_model import adverse_slippage_bps
from app.models.risk import RiskEvent
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import EquitySnapshot, Order, Signal, SlippageObservation, Trade
from app.portfolio.limits import PortfolioLimits
from app.portfolio.netting import Leg, attribute_pnl
from app.strategy.genome import genome_config
from app.strategy.health import evaluate_degradation
from app.strategy.regen import pause_for_degradation
from app.strategy.regime import classify_regime, regime_matches

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
        reopt_enqueue: Callable[[str], Awaitable[None]] | None = None,
        monitor_degradation: bool | None = None,
    ) -> None:
        self._sf = session_factory
        self._notifier = notifier or NullNotifier()
        self._clock = clock
        self._killswitch = killswitch or KillSwitch()
        self._tick_seconds = tick_seconds or settings.bot_tick_seconds
        self._kill_poll = kill_poll_seconds or settings.bot_killswitch_poll_seconds
        cash = initial_cash if initial_cash is not None else settings.bot_paper_initial_cash
        self._limits = limits or RiskLimits()
        # Portfolio-level limits (doc §24.5) — injected into every wall so they run
        # before strategy limits. Structural caps are the doc defaults; config may
        # only tighten (see core/config.py).
        self._portfolio_limits = PortfolioLimits(
            daily_loss_pct=settings.portfolio_daily_loss_pct,
            max_dd_pct=settings.portfolio_max_dd_pct,
            max_symbol_exposure_pct=settings.portfolio_max_symbol_exposure_pct,
            gross_leverage_cap=settings.portfolio_gross_leverage_cap,
            direction_concentration_pct=settings.portfolio_direction_concentration_pct,
        )
        self._adapter = PaperAdapter(cash)
        self._risk = RiskLayer(
            self._adapter, self._limits, mode="paper", clock=clock,
            portfolio=self._portfolio_limits,
        )
        # Live wall (Phase 7, doc §9.2–9.5) — built lazily and only when the config
        # master switch is on, keys are stored and the promotion gate opens. Until
        # then it stays None and every effective-live strategy executes on paper.
        self._live_adapter: object | None = None
        self._live_risk: RiskLayer | None = None
        self._live_checked_ts = 0  # throttle the (async, DB-hitting) readiness check
        self._processed: dict[str, int] = {}  # key → last bar ts acted on
        self._bands: dict[str, tuple[float | None, float | None, str]] = {}  # stop,target,side
        self._last_funding_ts: dict[str, int] = {}
        self._kill_handled = False
        self._rehydrated = False
        # Self-improvement wiring (Phase 6, §8.5). Degradation monitoring runs when a
        # trade closes; when a strategy degrades the engine pauses it and (best-effort)
        # queues a re-optimization via ``reopt_enqueue`` (the worker wires arq; tests
        # leave it None so no Redis is touched).
        self._reopt_enqueue = reopt_enqueue
        self._monitor_degradation = (
            settings.reopt_enabled if monitor_degradation is None else monitor_degradation
        )
        self._regime_cache: dict[tuple[str, str, str], tuple[int, object]] = {}

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
        self._limits = limits
        self._risk.limits = limits
        if self._live_risk is not None:
            self._live_risk.limits = limits

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

        await self._ensure_live_wall(session, global_mode, ts)

        for strat, version, config, mode in await self._load_active(session, global_mode):
            report.evaluated += 1
            try:
                await self._evaluate(session, strat, version, config, ts, report, mode)
            except Exception as exc:  # pragma: no cover - per-strategy resilience
                logger.warning("strategy %s tick failed: %s", strat.id, exc)
                report.notes.append(f"{strat.id}:{type(exc).__name__}")

        bal = self._adapter.get_balance()
        report.equity = bal.equity
        session.add(
            EquitySnapshot(ts=ts, mode="paper", equity=bal.equity, exposure=self._exposure())
        )
        # A parallel live snapshot feeds the live-vs-paper tracking error (§Faz-7).
        if self._live_adapter is not None:
            try:
                live_bal = self._live_adapter.get_balance()
                session.add(EquitySnapshot(
                    ts=ts, mode="live", equity=live_bal.equity, exposure=self._exposure("live")
                ))
            except Exception as exc:  # pragma: no cover - venue read best-effort
                logger.warning("live equity snapshot skipped: %s", type(exc).__name__)
        return report

    # ── live wall lifecycle (Phase 7, doc §9.2–9.5) ──────────────────────────
    async def _ensure_live_wall(self, session: AsyncSession, global_mode: str, ts: int) -> None:
        """Build the live wall iff config on + keys stored + gate open; else tear down.

        Rechecked at most once per minute (the readiness check hits the DB). The gate
        (§9.5) is enforced here independently of the switch layers — the engine will
        not construct a path to the venue on its own until every condition holds.
        """
        if not live_enabled():
            self._live_adapter = self._live_risk = None
            return
        if self._live_risk is not None and ts - self._live_checked_ts < 60_000:
            return
        self._live_checked_ts = ts
        try:
            from app.bot.promotion import evaluate_global_gate
            from app.core.secrets import load_api_keys
            from app.execution.binance import BinanceFuturesAdapter

            gate = await evaluate_global_gate(session)
            keys = await load_api_keys(session)
            if not gate.passed or keys is None:
                if self._live_risk is not None:
                    logger.info("live wall stood down: %s", "; ".join(gate.failures) or "no keys")
                self._live_adapter = self._live_risk = None
                return
            if self._live_risk is not None:
                return  # already built and still eligible
            adapter = BinanceFuturesAdapter(
                keys.api_key, keys.api_secret,
                testnet=keys.testnet or not settings.live_use_mainnet,
                leverage_default=self._limits.leverage_default,
            )
            self._live_adapter = adapter
            self._live_risk = RiskLayer(
                adapter, self._limits, mode="live", clock=self._clock,
                portfolio=self._portfolio_limits,
            )
            await self._reconcile_live(session, adapter)
            logger.info("live wall ARMED (testnet=%s)", getattr(adapter, "testnet", "?"))
        except Exception as exc:  # pragma: no cover - never let live setup crash the tick
            logger.warning("live wall setup failed: %s", type(exc).__name__)
            self._live_adapter = self._live_risk = None

    async def _reconcile_live(self, session: AsyncSession, adapter: object) -> None:
        """Emir-durum mutabakatı (doc §9.2): reconcile venue positions with local state.

        Seeds the adapter's realized-PnL mirror from open live trades, and logs any
        position the venue holds that we have no open trade for (and vice versa).
        """
        open_trades = (
            await session.execute(
                select(Trade).where(Trade.mode == "live", Trade.status == "open")
            )
        ).scalars().all()
        local = {t.symbol: t for t in open_trades}
        for t in open_trades:
            restore = getattr(adapter, "restore_mirror", None)
            if callable(restore):
                restore(t.symbol, t.side, t.qty, t.entry_price)
        try:
            venue = {p.symbol: p for p in adapter.get_positions()}
        except Exception as exc:  # pragma: no cover - venue read best-effort
            logger.warning("live reconciliation read failed: %s", type(exc).__name__)
            return
        for sym in set(local) | set(venue):
            if sym not in venue:
                session.add(RiskEvent(
                    ts=self._clock(), type="reconcile", mode="live", symbol=sym,
                    detail={"issue": "local_open_no_venue_position"},
                ))
            elif sym not in local:
                session.add(RiskEvent(
                    ts=self._clock(), type="reconcile", mode="live", symbol=sym,
                    detail={"issue": "venue_position_no_local_trade",
                            "qty": venue[sym].qty, "side": venue[sym].side},
                ))
        self._seed_live_risk(open_trades)

    def _seed_live_risk(self, open_trades: list[Trade]) -> None:
        """Seed the live wall's drawdown peak from the last live equity, if any."""
        if self._live_risk is None:
            return
        try:
            eq = self._live_adapter.get_balance().equity
            self._live_risk.seed_state(peak_equity=eq)
        except Exception:  # pragma: no cover - best-effort seed
            pass

    async def _load_active(
        self, session: AsyncSession, global_mode: str
    ) -> list[tuple[Strategy, StrategyVersion, RunConfig, str]]:
        """Tradeable strategies + the mode each executes in (``paper``/``live``).

        Effective mode is min(global, strategy) (§9.6); the *execution* mode degrades
        live→paper unless the live wall is armed (config + keys + gate, §9.5). Filters
        out ``pending_approval`` versions (unapproved genomes never trade, §8.5) and
        applies the regime gate (§8.4) when a lock is configured.
        """
        strategies = (await session.execute(select(Strategy))).scalars().all()
        lock_mode = await self._regime_lock(session)
        out: list[tuple[Strategy, StrategyVersion, RunConfig, str]] = []
        for strat in strategies:
            eff = effective_mode(global_mode, strat.mode)
            if not should_trade(eff) or strat.active_version_id is None:
                continue
            exec_mode = execution_mode(eff)
            if exec_mode == "live" and self._live_risk is None:
                exec_mode = "paper"  # gate/keys not ready → run this strategy on paper
            if exec_mode == "off":
                continue
            version = await session.get(StrategyVersion, strat.active_version_id)
            if version is None or version.status in ("retired", "pending_approval"):
                continue
            try:
                config = genome_config(version.genome)
            except Exception as exc:  # pragma: no cover - bad genome guard
                logger.warning("strategy %s has an invalid genome: %s", strat.id, exc)
                continue
            if not self._regime_eligible(version, config, lock_mode):
                continue
            out.append((strat, version, config, exec_mode))
        return out

    def _route(self, mode: str) -> tuple[RiskLayer, object]:
        """The (risk wall, adapter) pair for an execution mode."""
        if mode == "live" and self._live_risk is not None:
            return self._live_risk, self._live_adapter
        return self._risk, self._adapter

    async def _regime_lock(self, session: AsyncSession) -> str:
        """The active regime-lock mode (doc §8.4): off | auto | an explicit regime."""
        setting = await get_setting(session, KEY_REGIME_LOCK)
        return (setting or {}).get("mode", settings.regime_lock_default)

    def _regime_eligible(
        self, version: StrategyVersion, config: RunConfig, lock_mode: str
    ) -> bool:
        """Whether a strategy may run under the current regime lock (doc §8.4)."""
        if lock_mode == "off" or version.regime is None:
            return True  # gating off, or unlabelled ⇒ always eligible
        if lock_mode == "auto":
            return regime_matches(version.regime, self._current_regime(config))
        return regime_matches(version.regime, lock_mode)  # manual lock

    def _current_regime(self, config: RunConfig) -> object | None:
        """Current market regime for a symbol/tf (cached per last-closed bar)."""
        key = (config.market, config.symbol, config.tf)
        try:
            ohlcv = query_ohlcv(config.market, config.symbol, config.tf).reset_index(drop=True)
        except Exception:  # pragma: no cover - no data ⇒ no gating signal
            return None
        if len(ohlcv) < 2:
            return None
        last_ts = int(ohlcv["ts"].iloc[-1])
        cached = self._regime_cache.get(key)
        if cached and cached[0] == last_ts:
            return cached[1]
        label = classify_regime(
            ohlcv,
            adx_period=settings.regime_adx_period,
            adx_trend_threshold=settings.regime_adx_trend_threshold,
            atr_period=settings.regime_atr_period,
            atr_high_pct=settings.regime_atr_high_pct,
        )
        self._regime_cache[key] = (last_ts, label)
        return label

    # ── per-strategy evaluation ──────────────────────────────────────────────
    async def _evaluate(
        self,
        session: AsyncSession,
        strat: Strategy,
        version: StrategyVersion,
        config: RunConfig,
        ts: int,
        report: TickReport,
        mode: str = "paper",
    ) -> None:
        risk, adapter = self._route(mode)
        ohlcv = query_ohlcv(config.market, config.symbol, config.tf).reset_index(drop=True)
        if len(ohlcv) < 2:
            return
        key = f"{version.id}:{config.symbol}"
        last_bar_ts = int(ohlcv["ts"].iloc[-1])
        close = float(ohlcv["close"].iloc[-1])
        marker = getattr(adapter, "mark", None)
        if callable(marker):  # paper marks to last close; the venue marks itself
            marker(config.symbol, close)

        # Act once per closed bar (signal at close → fill next tick, rule #1).
        if self._processed.get(key) == last_bar_ts:
            return
        self._processed[key] = last_bar_ts

        frames = _indicator_frames(config, ohlcv)
        sig = evaluate_latest(config, ohlcv, frames)
        if sig is None:
            return
        if mode == "paper":  # live funding is settled by the venue, not simulated
            await self._accrue_funding(session, config, ts)

        open_trade = await self._open_trade(session, strat.id, config.symbol, mode)
        action, reason = self._decide(config, sig, ohlcv, key, open_trade)
        if action is None:
            return

        report.signals += 1
        atr = self._atr_at(ohlcv, config)
        bar_volume = float(ohlcv["volume"].iloc[-1]) if "volume" in ohlcv else None
        intent = TradeIntent(
            strategy_version_id=version.id,
            symbol=config.symbol,
            action=action,
            reference_price=close,
            ts=ts,
            atr=atr,
            stop_distance=self._stop_distance(config, atr),
            leverage=config.capital.leverage or risk.limits.leverage_default,
            # Market order fills at the current price, so the reference *is* the last
            # price → the deviation guard only trips on a genuinely stale reference.
            last_price=close,
            # Signal-bar base volume for the capacity/participation gate (doc §26.2).
            bar_volume=bar_volume,
            commission_bps=config.costs.commission_bps,
            slippage_bps=(
                config.costs.slippage_bps if config.costs.slippage_model == "fixed_bps" else None
            ),
            # Per-genome sizing → the risk wall sizes exactly like the backtest (§8.1).
            sizing=config.capital.sizing,
            per_trade_pct=config.capital.per_trade_pct,
            size_pct=config.capital.size_pct,
        )
        decision, result = risk.submit(intent)

        # Persist the risk events regardless of outcome (decision-log evidence).
        for ev in decision.events:
            session.add(RiskEvent(
                ts=ev["ts"], type=ev["type"], mode=mode, symbol=ev["symbol"],
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
            mode=mode,
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
                mode=mode, signal_id=signal.id, strategy_version_id=version.id,
                symbol=config.symbol, side=intent.side, qty=decision.qty,
                status="rejected", detail={"reason": decision.reason},
            ))
            await self._notifier.notify(
                f"⛔ {config.symbol} {action} rejected by risk: {decision.reason} ({mode})"
            )
            return

        report.orders += 1
        fill = result.fill
        session.add(Order(
            mode=mode, signal_id=signal.id, strategy_version_id=version.id,
            symbol=config.symbol, side=intent.side, qty=fill.qty, price=fill.price,
            status="filled", detail={"commission": fill.commission, "slippage": fill.slippage_cost},
        ))
        self._record_slippage(session, version, config, intent, fill, mode)
        await self._apply_fill(
            session, strat, version, config, action, intent, fill, open_trade, mode, risk
        )

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
        mode: str = "paper",
        risk: RiskLayer | None = None,
    ) -> None:
        """Update the trades table + risk feedback + notifications after a fill."""
        risk = risk or self._risk
        key = f"{version.id}:{config.symbol}"
        if action.startswith("open_"):
            trade = Trade(
                mode=mode, strategy_version_id=version.id, strategy_id=strat.id,
                symbol=config.symbol, side=intent.position_side, qty=fill.qty,
                leverage=intent.leverage, entry_price=fill.price, entry_ts=intent.ts,
                fees=fill.commission, status="open",
            )
            session.add(trade)
            self._set_band(config, intent, key)
            await self._notifier.notify(
                f"✅ {config.symbol} {intent.position_side} @ {fill.price:.4f} "
                f"×{fill.qty:.4f} ({mode})"
            )
        else:  # close
            if open_trade is not None:
                open_trade.exit_price = fill.price
                open_trade.exit_ts = intent.ts
                open_trade.fees += fill.commission
                open_trade.pnl = fill.realized_pnl - open_trade.fees + open_trade.funding
                open_trade.status = "closed"
                await self._attribute_shared(session, open_trade, config.symbol, mode)
                risk.register_trade_result(open_trade.pnl, intent.ts)
                await self._notifier.notify(
                    f"💵 {config.symbol} closed @ {fill.price:.4f} "
                    f"pnl {open_trade.pnl:+.2f} ({mode})"
                )
                # Degradation monitoring keys off the paper record (§8.5); the live
                # twin's paper strategy keeps that signal, so only monitor on paper.
                if self._monitor_degradation and mode == "paper":
                    await self._maybe_degrade(session, strat, version, config)
            self._bands.pop(key, None)

    async def _attribute_shared(
        self, session: AsyncSession, closing: Trade, symbol: str, mode: str
    ) -> None:
        """Proportional PnL attribution when >1 strategy shares a symbol (doc §24.4).

        The exchange holds one netted position per symbol; when this leg closes and
        other strategies still hold the same symbol, record how this realized PnL maps
        across the co-holders (``trades.attribution``). A single-strategy symbol leaves
        ``attribution`` None — its own row already carries the full PnL.
        """
        if closing.pnl is None:
            return
        coholders = (
            await session.execute(
                select(Trade).where(
                    Trade.symbol == symbol, Trade.mode == mode,
                    Trade.status == "open", Trade.id != closing.id,
                    Trade.strategy_id != closing.strategy_id,
                )
            )
        ).scalars().all()
        if not coholders:
            return
        legs = [
            Leg(
                strategy_id=t.strategy_id or t.id, symbol=symbol, side=t.side,
                notional=abs(t.qty) * t.entry_price,
            )
            for t in (closing, *coholders)
        ]
        closing.attribution = {
            sid: round(v, 6) for sid, v in attribute_pnl(closing.pnl, legs).items()
        }

    async def _maybe_degrade(
        self,
        session: AsyncSession,
        strat: Strategy,
        version: StrategyVersion,
        config: RunConfig,
    ) -> None:
        """After a close, check §8.5 triggers; if degraded, pause + queue re-opt."""
        if strat.mode == "off":
            return
        verdict = await evaluate_degradation(
            session, strat.id, wfo_report=version.wfo_report,
            initial_cash=config.capital.initial_cash,
        )
        if not verdict.degraded:
            return
        reason = "degrade:" + ",".join(verdict.triggers)
        await pause_for_degradation(
            session, strat, verdict, reason=reason, notifier=self._notifier
        )
        if self._reopt_enqueue is not None:
            try:
                await self._reopt_enqueue(strat.id)
            except Exception as exc:  # pragma: no cover - queue best-effort
                logger.warning("reopt enqueue failed for %s: %s", strat.id, exc)

    # ── kill switch ──────────────────────────────────────────────────────────
    async def _handle_kill(self, session: AsyncSession, ts: int) -> None:
        """React to an engaged kill switch: cancel, halt entry path, record once."""
        if self._kill_handled:
            return
        self._kill_handled = True
        self._risk.cancel_all()
        # The kill switch cancels the venue's resting orders too (doc §9.4).
        if self._live_risk is not None:
            try:
                self._live_risk.cancel_all()
            except Exception as exc:  # pragma: no cover - venue best-effort
                logger.warning("live cancel_all on kill failed: %s", type(exc).__name__)
        session.add(RiskEvent(ts=ts, type="killswitch", mode="paper", detail={"engaged": True}))
        await self._notifier.notify("🛑 KILL SWITCH engaged — new orders halted")
        await session.commit()

    async def _trigger_kill(self, session: AsyncSession, ts: int, reason: str) -> None:
        """Engage the kill switch from inside the bot (max drawdown breach)."""
        from app.bot import killswitch as ks

        await ks.engage(session, actor="system", reason=reason)
        await self._handle_kill(session, ts)

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _open_trade(
        self, session: AsyncSession, strategy_id: str, symbol: str, mode: str = "paper"
    ) -> Trade | None:
        return (
            await session.execute(
                select(Trade)
                .where(Trade.strategy_id == strategy_id, Trade.symbol == symbol,
                       Trade.mode == mode, Trade.status == "open")
                .order_by(Trade.entry_ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def _record_slippage(
        self,
        session: AsyncSession,
        version: StrategyVersion,
        config: RunConfig,
        intent: TradeIntent,
        fill: object,
        mode: str,
    ) -> None:
        """Record expected-vs-realized fill price for the learned model (doc §26.1).

        Every fill is logged; only ``mode == "live"`` rows teach the model when it is
        rebuilt (a paper fill is simulated — feeding it back would teach the model its
        own guess, rule #13). Paper rows are still stored so the operator can inspect them.
        """
        expected = intent.reference_price
        if expected is None or expected <= 0 or fill.price <= 0:
            return
        session.add(SlippageObservation(
            ts=intent.ts, mode=mode, symbol=config.symbol, tf=config.tf, side=intent.side,
            expected_price=expected, fill_price=fill.price,
            order_notional=fill.qty * fill.price, atr=intent.atr or 0.0,
            slippage_bps=adverse_slippage_bps(expected, fill.price, intent.side),
            strategy_version_id=version.id,
        ))

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
        """Effective stop distance = the exit's stop, else the ATR-sizing default.

        Identical to the backtest engine's ``eff_stop_mult`` so the sizing basis and
        the exit band agree between backtest and live (one stop, not two).
        """
        if atr is None:
            return None
        mult: float | None = None
        if config.risk_exit.atr_stop_mult is not None:
            mult = config.risk_exit.atr_stop_mult
        elif config.capital.sizing == "atr":
            mult = config.capital.default_stop_atr_mult
        return mult * atr if mult else None

    def _set_band(self, config: RunConfig, intent: TradeIntent, key: str) -> None:
        atr = intent.atr
        entry = intent.reference_price
        side = intent.position_side
        sign = 1 if side == "long" else -1
        re = config.risk_exit
        # The stop band uses the SAME effective distance that sized the position
        # (intent.stop_distance), so the exit and the sizing stop are one and the same.
        stop = entry - sign * intent.stop_distance if intent.stop_distance else None
        target = (
            (entry + sign * re.atr_target_mult * atr)
            if (re.enabled and re.atr_target_mult and atr) else None
        )
        if stop is None and target is None:
            self._bands.pop(key, None)
            return
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

    def _exposure(self, mode: str = "paper") -> float:
        adapter = self._live_adapter if mode == "live" else self._adapter
        if adapter is None:
            return 0.0
        try:
            positions = adapter.get_positions()
        except Exception:  # pragma: no cover - venue read best-effort
            return 0.0
        return sum(p.qty * (p.mark_price or p.entry_price) for p in positions)

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
