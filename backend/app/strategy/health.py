"""Degradation triggers — live/paper strategy monitoring (doc §8.5).

Two triggers, straight from §8.5, decide when a running strategy has decayed enough
to be pulled and re-optimized:

1. **Rolling Profit Factor < 1.0** over the last N closed trades (default 30). Below
   1.0 the strategy is losing money on a rolling basis.
2. **Realized drawdown breaks the 95% Monte-Carlo lower band.** The strategy's
   validation report (§6.5) carries ``monte_carlo.p95_max_drawdown`` — the 95th
   percentile of the shuffled-trade drawdown distribution. If the *live* equity
   curve draws down deeper than that band, its behaviour is outside what the
   backtest expected and the edge is suspect.

Either trigger ⇒ the orchestrator (:mod:`app.strategy.regen`) auto-pauses the
strategy, queues a re-optimization and notifies the operator. The detector itself is
pure of side effects: it reads trades + the report and returns a typed verdict, so it
is deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.trading import Trade


@dataclass
class DegradeConfig:
    """§8.5 thresholds (defaults from ``settings``; tests override)."""

    rolling_window: int = 30  # last-N closed trades considered
    min_trades: int = 30  # need this many before the PF trigger can fire
    min_profit_factor: float = 1.0
    mc_drawdown_enabled: bool = True

    @classmethod
    def from_settings(cls) -> DegradeConfig:
        return cls(
            rolling_window=settings.degrade_rolling_window,
            min_trades=settings.degrade_min_trades,
            min_profit_factor=settings.degrade_min_profit_factor,
            mc_drawdown_enabled=settings.degrade_mc_drawdown_enabled,
        )


@dataclass
class DegradeVerdict:
    """The outcome of a degradation check for one strategy."""

    degraded: bool
    triggers: list[str] = field(default_factory=list)  # "rolling_pf" | "mc_drawdown"
    num_trades: int = 0
    rolling_pf: float | None = None
    realized_max_drawdown: float | None = None
    mc_p95_drawdown: float | None = None

    def as_dict(self) -> dict:
        return {
            "degraded": self.degraded,
            "triggers": self.triggers,
            "num_trades": self.num_trades,
            "rolling_pf": self.rolling_pf,
            "realized_max_drawdown": self.realized_max_drawdown,
            "mc_p95_drawdown": self.mc_p95_drawdown,
        }


def mc_p95_drawdown(wfo_report: dict | None) -> float | None:
    """Pull the 95% Monte-Carlo max-drawdown band out of a validation report."""
    if not isinstance(wfo_report, dict):
        return None
    mc = wfo_report.get("monte_carlo")
    if not isinstance(mc, dict):
        return None
    value = mc.get("p95_max_drawdown")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def profit_factor(pnls: list[float]) -> float | None:
    """PF = gross gains / gross losses. ``None`` when there are no losses to divide."""
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses <= 0:
        return None  # no losing trades ⇒ PF undefined (never a degradation)
    return gains / losses


def realized_max_drawdown(pnls_chronological: list[float], initial_cash: float) -> float:
    """Peak-to-trough drawdown fraction of the equity built from realized PnL.

    Same shape as the Monte-Carlo band it is compared against (a drawdown fraction),
    so the two are directly comparable.
    """
    equity = initial_cash
    peak = initial_cash
    max_dd = 0.0
    for pnl in pnls_chronological:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


async def _closed_trades(session: AsyncSession, strategy_id: str, limit: int) -> list[Trade]:
    """The last ``limit`` closed paper trades, newest first."""
    return list(
        (
            await session.execute(
                select(Trade)
                .where(
                    Trade.strategy_id == strategy_id,
                    Trade.mode == "paper",
                    Trade.status == "closed",
                )
                .order_by(Trade.exit_ts.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


async def evaluate_degradation(
    session: AsyncSession,
    strategy_id: str,
    *,
    wfo_report: dict | None,
    initial_cash: float,
    config: DegradeConfig | None = None,
) -> DegradeVerdict:
    """Decide whether a strategy has degraded per §8.5 (pure read; no side effects)."""
    cfg = config or DegradeConfig.from_settings()
    trades = await _closed_trades(session, strategy_id, cfg.rolling_window)
    pnls = [t.pnl for t in trades if t.pnl is not None]  # newest-first
    num = len(pnls)

    verdict = DegradeVerdict(degraded=False, num_trades=num)
    if num == 0:
        return verdict

    verdict.rolling_pf = profit_factor(pnls)
    verdict.mc_p95_drawdown = mc_p95_drawdown(wfo_report)
    # Drawdown wants chronological order (oldest → newest).
    verdict.realized_max_drawdown = realized_max_drawdown(list(reversed(pnls)), initial_cash)

    triggers: list[str] = []
    if (
        num >= cfg.min_trades
        and verdict.rolling_pf is not None
        and verdict.rolling_pf < cfg.min_profit_factor
    ):
        triggers.append("rolling_pf")
    if (
        cfg.mc_drawdown_enabled
        and verdict.mc_p95_drawdown is not None
        and verdict.mc_p95_drawdown > 0.0
        and verdict.realized_max_drawdown > verdict.mc_p95_drawdown
    ):
        triggers.append("mc_drawdown")

    verdict.triggers = triggers
    verdict.degraded = bool(triggers)
    return verdict
