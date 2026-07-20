"""Paper → Live promotion gate (doc §9.5) — numeric, not a feeling.

The gate is the reason the live order path is *closed by default*. A switch cannot
reach ``live`` — global or per-strategy — until a paper track record clears every
threshold (config, defaults from §9.5): ≥ ``min_days`` days, ≥ ``min_trades`` closed
paper trades, Profit Factor ≥ ``min_profit_factor``, and realized MaxDD ≤
``max_drawdown_pct``. On top of that the live *infrastructure* must be ready
(``live_trading_enabled`` + encrypted keys stored), so a passing record alone never
opens a path to an unconfigured venue.

Enforcement is layered and identical everywhere (:func:`assert_can_go_live`): the API
(`POST /bot/mode`, `POST /strategies/{id}/mode`), the mode module and the Telegram
`/mode live` handler all call it, and the bot engine independently refuses to build a
live wall unless the gate passes. Any single layer would do; having all of them is the
point — "her katmanda reddedilir" is the Phase-7 acceptance, proved by a test.

Pure reads, no side effects: it returns a typed verdict the caller persists/renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.settings_store import KEY_API_KEYS, KEY_PROMOTION_GATE, get_setting
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.strategy.health import profit_factor, realized_max_drawdown

# §9.5 defaults (also mirrored in api/bot.py for the settings panel).
DEFAULT_GATE = {
    "min_days": 30,
    "min_trades": 30,
    "min_profit_factor": 1.3,
    "max_drawdown_pct": 10.0,
}

_DAY_MS = 86_400_000


class GateNotMet(Exception):
    """Raised when a switch is asked to go LIVE before the gate opens (doc §9.5)."""

    def __init__(self, result: GateResult) -> None:
        self.result = result
        super().__init__("; ".join(result.failures) or "promotion gate not met")


@dataclass
class GateResult:
    """Verdict + the metrics behind it + the specific failures (for UI + audit)."""

    passed: bool
    scope: str  # global | strategy
    strategy_id: str | None = None
    failures: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "scope": self.scope,
            "strategy_id": self.strategy_id,
            "failures": self.failures,
            "metrics": self.metrics,
        }


async def load_gate(session: AsyncSession) -> dict:
    """The configured thresholds (falls back to the §9.5 defaults)."""
    return await get_setting(session, KEY_PROMOTION_GATE) or dict(DEFAULT_GATE)


async def infra_ready(session: AsyncSession) -> tuple[bool, list[str]]:
    """Live plumbing check: master switch on + encrypted keys stored."""
    reasons: list[str] = []
    if not settings.live_trading_enabled:
        reasons.append("live trading disabled (LIVE_TRADING_ENABLED=false)")
    keys = await get_setting(session, KEY_API_KEYS)
    if not keys or "api_key_enc" not in keys:
        reasons.append("no exchange API keys configured")
    return (not reasons, reasons)


async def _initial_cash(session: AsyncSession, strategy_id: str | None) -> float:
    """Initial cash for the drawdown baseline (strategy genome, else paper default)."""
    if strategy_id is not None:
        strat = await session.get(Strategy, strategy_id)
        if strat and strat.active_version_id:
            version = await session.get(StrategyVersion, strat.active_version_id)
            if version:
                cap = (version.genome or {}).get("config", {}).get("capital", {})
                cash = cap.get("initial_cash")
                if cash:
                    return float(cash)
    return float(settings.bot_paper_initial_cash)


async def _paper_trades(session: AsyncSession, strategy_id: str | None) -> list[Trade]:
    """Closed paper trades (one strategy, or the whole desk), oldest → newest."""
    stmt = select(Trade).where(Trade.mode == "paper", Trade.status == "closed")
    if strategy_id is not None:
        stmt = stmt.where(Trade.strategy_id == strategy_id)
    stmt = stmt.order_by(Trade.entry_ts.asc())
    return list((await session.execute(stmt)).scalars().all())


def _evaluate(gate: dict, trades: list[Trade], initial_cash: float) -> tuple[list[str], dict]:
    """Score a paper record against the gate; return (failures, metrics)."""
    pnls = [t.pnl for t in trades if t.pnl is not None]
    num_trades = len(pnls)
    days = 0.0
    if trades:
        first_ts = min(t.entry_ts for t in trades)
        days = max(0.0, (now_ms() - first_ts) / _DAY_MS)
    pf = profit_factor(pnls)
    max_dd_pct = realized_max_drawdown(pnls, initial_cash) * 100.0

    metrics = {
        "num_trades": num_trades,
        "days": round(days, 2),
        "profit_factor": None if pf is None else round(pf, 4),
        "max_drawdown_pct": round(max_dd_pct, 4),
    }

    failures: list[str] = []
    if num_trades < gate["min_trades"]:
        failures.append(f"trades {num_trades} < {gate['min_trades']}")
    if days < gate["min_days"]:
        failures.append(f"days {days:.1f} < {gate['min_days']}")
    # PF undefined (no losing trades) is not a failure — there is no risk to divide by.
    if pf is not None and pf < gate["min_profit_factor"]:
        failures.append(f"profit factor {pf:.2f} < {gate['min_profit_factor']}")
    if max_dd_pct > gate["max_drawdown_pct"]:
        failures.append(f"max drawdown {max_dd_pct:.1f}% > {gate['max_drawdown_pct']}%")
    return failures, metrics


async def evaluate_strategy_gate(session: AsyncSession, strategy_id: str) -> GateResult:
    """The §9.5 gate for one strategy's paper record (infra checked too)."""
    gate = await load_gate(session)
    trades = await _paper_trades(session, strategy_id)
    cash = await _initial_cash(session, strategy_id)
    failures, metrics = _evaluate(gate, trades, cash)
    ready, infra_reasons = await infra_ready(session)
    failures += infra_reasons
    metrics["infra_ready"] = ready
    return GateResult(
        passed=not failures, scope="strategy", strategy_id=strategy_id,
        failures=failures, metrics=metrics,
    )


async def evaluate_global_gate(session: AsyncSession) -> GateResult:
    """Global → LIVE: infra ready AND at least one strategy passes its own gate."""
    gate = await load_gate(session)
    ready, infra_reasons = await infra_ready(session)
    strategies = (await session.execute(select(Strategy))).scalars().all()
    per_strategy: list[dict] = []
    any_pass = False
    for strat in strategies:
        trades = await _paper_trades(session, strat.id)
        cash = await _initial_cash(session, strat.id)
        failures, metrics = _evaluate(gate, trades, cash)
        passed = not failures
        any_pass = any_pass or passed
        per_strategy.append({"strategy_id": strat.id, "passed": passed, "metrics": metrics})

    failures = list(infra_reasons)
    if not any_pass:
        failures.append("no strategy has passed the promotion gate yet")
    return GateResult(
        passed=(ready and any_pass), scope="global", strategy_id=None,
        failures=failures, metrics={"infra_ready": ready, "strategies": per_strategy},
    )


async def evaluate_gate(
    session: AsyncSession, scope: str, strategy_id: str | None
) -> GateResult:
    """Dispatch to the global or per-strategy gate."""
    if scope == "strategy" and strategy_id:
        return await evaluate_strategy_gate(session, strategy_id)
    return await evaluate_global_gate(session)


async def assert_can_go_live(
    session: AsyncSession, scope: str, strategy_id: str | None
) -> GateResult:
    """Raise :class:`GateNotMet` unless the gate opens for this switch (doc §9.5)."""
    result = await evaluate_gate(session, scope, strategy_id)
    if not result.passed:
        raise GateNotMet(result)
    return result
