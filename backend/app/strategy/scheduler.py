"""The weekly WFO re-optimization scheduler (doc §8.3 v1, §15/Faz 6).

The self-improvement loop's heartbeat: on a cadence (weekly in production, a
shortened interval in tests) it walks the *running* strategies and asks the producer
to refresh each one's parameters on the newest data. Every proposal lands in the
approval queue as a ``pending_approval`` version (never activated) — the terfi kapısı
stays human (doc §8.5, config can later make it fully automatic).

The cron body is factored into :func:`run_scheduled_reopt` so it is importable and
testable without arq — the acceptance criterion "zamanlayıcı çalışır (lokalde
kısaltılmış aralıkla test)".
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.notifier import Notifier
from app.models.strategy import Strategy, StrategyVersion
from app.strategy import regen

logger = logging.getLogger(__name__)

# Only versions in a live lifecycle stage are worth refreshing.
_RUNNABLE = ("candidate", "paper", "live")


async def _has_pending(session: AsyncSession, strategy_id: str) -> bool:
    """Whether a strategy already has a version awaiting approval (avoid duplicates)."""
    row = (
        await session.execute(
            select(StrategyVersion.id).where(
                StrategyVersion.strategy_id == strategy_id,
                StrategyVersion.status == "pending_approval",
            ).limit(1)
        )
    ).first()
    return row is not None


async def run_scheduled_reopt(
    session_factory: async_sessionmaker[AsyncSession],
    notifier: Notifier | None = None,
    *,
    generator_kind: str | None = None,
    reason: str = "scheduled",
) -> list[str]:
    """Re-optimize every running strategy; return the produced pending version ids.

    A strategy is skipped when it is switched Off, has no active version, its active
    version is not in a runnable stage, or it already has a pending proposal.
    """
    produced: list[str] = []
    async with session_factory() as session:
        strategies = (
            await session.execute(select(Strategy).where(Strategy.mode != "off"))
        ).scalars().all()
        for strat in strategies:
            if strat.active_version_id is None:
                continue
            version = await session.get(StrategyVersion, strat.active_version_id)
            if version is None or version.status not in _RUNNABLE:
                continue
            if await _has_pending(session, strat.id):
                continue
            try:
                new_version = await regen.regenerate(
                    session, strat.id, reason=reason,
                    generator_kind=generator_kind, notifier=notifier,
                )
            except Exception as exc:  # one bad strategy must not sink the whole run
                logger.warning("scheduled reopt failed for %s: %s", strat.id, exc)
                continue
            if new_version is not None:
                produced.append(new_version.id)
        await session.commit()
    logger.info("scheduled reopt produced %d pending version(s)", len(produced))
    return produced
