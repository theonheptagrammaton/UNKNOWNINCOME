"""Regeneration orchestration — producer → validator → human-approved terfi (doc §8.3–8.5).

This is the glue that turns a *reason to regenerate* (the weekly scheduler, or a
degradation trigger) into a **pending-approval** version, without ever letting the
new version trade before a human says so:

* :func:`regenerate` runs the configured producer (v1 = WFO re-opt), then stores the
  proposal as a new version with ``activate=False`` + status ``pending_approval`` —
  the active pointer is untouched, so the running (or paused) version keeps its place
  and the proposal waits in the approval queue.
* :func:`pause_for_degradation` implements the §8.5 reaction: auto-pause + audit +
  notify. The bot calls it then *queues* a re-opt job; the debug/test path calls
  :func:`degrade_and_regenerate` which pauses and regenerates synchronously.

Approval/rejection live in :mod:`app.strategy.service` (``approve_version`` /
``reject_version``) — the terfi kapısı a human drives from the UI or Telegram.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.notifier import Notifier
from app.core.config import settings
from app.models.strategy import Strategy, StrategyVersion
from app.strategy import reoptimize as _reoptimize  # noqa: F401  registers "wfo_reopt"
from app.strategy import service
from app.strategy.generator import GenerationRequest, get_generator
from app.strategy.health import DegradeVerdict

logger = logging.getLogger(__name__)


async def _notify(notifier: Notifier | None, text: str) -> None:
    if notifier is not None:
        try:
            await notifier.notify(text)
        except Exception as exc:  # pragma: no cover - notification must never break flow
            logger.warning("notify failed: %s", exc)


async def regenerate(
    session: AsyncSession,
    strategy_id: str,
    *,
    reason: str,
    generator_kind: str | None = None,
    seed: int = 42,
    trials: int | None = None,
    actor: str = "system",
    notifier: Notifier | None = None,
) -> StrategyVersion | None:
    """Run the producer + validator; store the proposal as a pending version (§8.3).

    Returns the new ``pending_approval`` version, or ``None`` when the producer found
    nothing viable (e.g. insufficient data). Never activates the new version — that is
    the human-approved terfi kapısı (:func:`app.strategy.service.approve_version`).
    """
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None or strategy.active_version_id is None:
        raise service.StrategyError(f"strategy {strategy_id!r} has no active version")
    active = await session.get(StrategyVersion, strategy.active_version_id)
    if active is None:
        raise service.StrategyError("active version missing")

    kind = generator_kind or settings.reopt_generator
    generator = get_generator(kind)
    request = GenerationRequest(
        strategy_id=strategy_id,
        genome=active.genome,
        parent_version_id=active.id,
        reason=reason,
        seed=seed,
        trials=trials,
    )
    result = generator.propose(request)
    if result is None:
        await _notify(
            notifier,
            f"ℹ️ {strategy.name}: re-optimization ({reason}) found no viable candidate.",
        )
        return None

    version = await service.add_version(
        session,
        strategy_id,
        result.genome,
        wfo_report=result.wfo_report,
        source={
            "kind": "reopt",
            "generator": kind,
            "reason": reason,
            "parent_version_id": active.id,
            "summary": result.summary,
        },
        status="pending_approval",
        actor=actor,
        activate=False,  # pazarlıksız: unapproved versions never trade (§8.5)
        regime=result.regime,
    )
    verdict = "✅ survived §6.5" if result.survived else "⚠️ did NOT survive §6.5"
    await _notify(
        notifier,
        f"🧬 {strategy.name}: new version v{version.version} awaiting approval "
        f"({reason}, {verdict}, OOS {result.summary.get('oos_score')}).",
    )
    return version


async def pause_for_degradation(
    session: AsyncSession,
    strategy: Strategy,
    verdict: DegradeVerdict,
    *,
    reason: str,
    actor: str = "system",
    notifier: Notifier | None = None,
) -> None:
    """React to a §8.5 degradation: auto-pause the strategy + audit + notify."""
    if strategy.mode != "off":
        await service.set_mode(session, strategy.id, "off", actor=actor)
    from app.core.audit import write_audit

    await write_audit(
        session, actor, "strategy.degrade",
        {"strategy_id": strategy.id, "reason": reason, **verdict.as_dict()},
    )
    triggers = ", ".join(verdict.triggers) or reason
    await _notify(
        notifier,
        f"📉 {strategy.name}: degradation detected ({triggers}) — paused, "
        f"re-optimization queued (PF={verdict.rolling_pf}, "
        f"maxDD={verdict.realized_max_drawdown}).",
    )


async def degrade_and_regenerate(
    session: AsyncSession,
    strategy_id: str,
    *,
    verdict: DegradeVerdict,
    reason: str,
    generator_kind: str | None = None,
    trials: int | None = None,
    actor: str = "system",
    notifier: Notifier | None = None,
) -> StrategyVersion | None:
    """Synchronous §8.5 end-to-end: pause + regenerate (used by the debug hook + tests)."""
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        raise service.StrategyError(f"unknown strategy: {strategy_id!r}")
    await pause_for_degradation(
        session, strategy, verdict, reason=reason, actor=actor, notifier=notifier
    )
    return await regenerate(
        session, strategy_id, reason=reason, generator_kind=generator_kind,
        trials=trials, actor=actor, notifier=notifier,
    )
