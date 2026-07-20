"""Strategy lifecycle service (doc §8.1–8.2, §8.6, §9.6).

The single writer for strategies and their immutable versions. Every edit — from
the UI builder, the raw JSON editor or a plugin-driven save — funnels through
:func:`add_version`, which stamps a new monotonic version, links its parent and
repoints ``active_version_id`` so the change hot-reloads on the bot's next tick.

"Convert to strategy" (doc §10.1) is here too: a genome can be born from a backtest
run or a discovery leaderboard entry, carrying its provenance and WFO report.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.config import RunConfig
from app.core.audit import write_audit
from app.discovery.store import read_leaderboard
from app.models.backtest import BacktestRun
from app.models.discovery import DiscoveryScan
from app.models.strategy import MODE_ORDER, STATUSES, Strategy, StrategyVersion
from app.strategy.genome import genome_hash, normalize_genome


class StrategyError(ValueError):
    """Raised on invalid strategy operations (bad status, unknown id, …)."""


async def _next_version(session: AsyncSession, strategy_id: str) -> int:
    current = (
        await session.execute(
            select(func.max(StrategyVersion.version)).where(
                StrategyVersion.strategy_id == strategy_id
            )
        )
    ).scalar()
    return int(current or 0) + 1


async def add_version(
    session: AsyncSession,
    strategy_id: str,
    genome: dict,
    *,
    wfo_report: dict | None = None,
    source: dict | None = None,
    status: str = "candidate",
    actor: str = "api",
) -> StrategyVersion:
    """Append a new immutable version and repoint the strategy at it (hot-reload).

    The parent is the strategy's current active version; the strategy's name tracks
    the newest genome. Raises :class:`StrategyError` if the strategy is unknown.
    """
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        raise StrategyError(f"unknown strategy: {strategy_id!r}")
    norm = normalize_genome(genome)  # validates; raises GenomeError on bad payload

    version = StrategyVersion(
        strategy_id=strategy_id,
        version=await _next_version(session, strategy_id),
        genome=norm,
        genome_hash=genome_hash(norm),
        wfo_report=wfo_report,
        status=status if status in STATUSES else "candidate",
        parent_version_id=strategy.active_version_id,
        source=source,
    )
    session.add(version)
    await session.flush()  # assign version.id

    strategy.active_version_id = version.id
    strategy.name = norm["name"]
    await write_audit(
        session,
        actor,
        "strategy.version.add",
        {"strategy_id": strategy_id, "version": version.version, "hash": version.genome_hash},
    )
    return version


async def create_strategy(
    session: AsyncSession,
    genome: dict,
    *,
    created_from_run_id: str | None = None,
    wfo_report: dict | None = None,
    source: dict | None = None,
    actor: str = "api",
) -> tuple[Strategy, StrategyVersion]:
    """Create a new strategy lineage + its version 1 (status ``candidate``)."""
    norm = normalize_genome(genome)
    strategy = Strategy(
        name=norm["name"], created_from_run_id=created_from_run_id, mode="off"
    )
    session.add(strategy)
    await session.flush()  # assign strategy.id
    version = await add_version(
        session, strategy.id, norm, wfo_report=wfo_report, source=source, actor=actor
    )
    return strategy, version


async def create_from_backtest_run(
    session: AsyncSession, run_id: str, name: str | None = None, actor: str = "api"
) -> tuple[Strategy, StrategyVersion]:
    """Convert a backtest run's config into a candidate strategy (doc §10.1)."""
    run = await session.get(BacktestRun, run_id)
    if run is None:
        raise StrategyError(f"unknown backtest run: {run_id!r}")
    config = RunConfig.model_validate(run.config)
    label = name or f"{config.symbol}·{config.tf} (run {run_id[:8]})"
    genome = {"name": label, "config": run.config}
    return await create_strategy(
        session,
        genome,
        created_from_run_id=run_id,
        wfo_report={"metrics": run.metrics} if run.metrics else None,
        source={"kind": "run", "id": run_id},
        actor=actor,
    )


async def create_from_scan_entry(
    session: AsyncSession,
    scan_id: str,
    rank: int,
    name: str | None = None,
    actor: str = "api",
) -> tuple[Strategy, StrategyVersion]:
    """Convert a discovery leaderboard entry (1-based ``rank``) into a candidate."""
    scan = await session.get(DiscoveryScan, scan_id)
    if scan is None:
        raise StrategyError(f"unknown scan: {scan_id!r}")
    payload = read_leaderboard(scan.artifact_path)
    entries = (payload or {}).get("leaderboard", [])
    entry = next((e for e in entries if e.get("rank") == rank), None)
    if entry is None:
        raise StrategyError(f"scan {scan_id!r} has no entry at rank {rank}")
    combo = entry.get("combo", {})
    label = name or (
        f"{combo.get('trigger', '?')}×{combo.get('filter', '?')} "
        f"@{entry.get('symbol')}:{entry.get('tf')}"
    )
    genome = {"name": label, "config": entry["genome"]}
    wfo_report = {
        "oos_score": entry.get("oos_score"),
        "is_score": entry.get("is_score"),
        "metrics": entry.get("metrics"),
        "wfo_layers": entry.get("wfo_layers"),
        "monte_carlo": entry.get("monte_carlo"),
        "plateau_ok": entry.get("plateau_ok"),
    }
    return await create_strategy(
        session,
        genome,
        created_from_run_id=scan_id,
        wfo_report=wfo_report,
        source={"kind": "scan", "id": scan_id, "rank": rank},
        actor=actor,
    )


async def set_mode(
    session: AsyncSession, strategy_id: str, mode: str, actor: str = "api"
) -> Strategy:
    """Set a strategy's mode switch (off/paper/live); records an audit row (doc §9.6)."""
    if mode not in MODE_ORDER:
        raise StrategyError(f"invalid mode: {mode!r}")
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        raise StrategyError(f"unknown strategy: {strategy_id!r}")
    previous = strategy.mode
    strategy.mode = mode
    await write_audit(
        session, actor, "strategy.mode", {"strategy_id": strategy_id, "from": previous, "to": mode}
    )
    return strategy


async def set_status(
    session: AsyncSession, strategy_id: str, status: str, actor: str = "api"
) -> StrategyVersion:
    """Set the active version's lifecycle status (doc §8.2)."""
    if status not in STATUSES:
        raise StrategyError(f"invalid status: {status!r}")
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None or strategy.active_version_id is None:
        raise StrategyError(f"strategy {strategy_id!r} has no active version")
    version = await session.get(StrategyVersion, strategy.active_version_id)
    if version is None:
        raise StrategyError("active version missing")
    previous = version.status
    version.status = status
    if status == "retired":
        strategy.mode = "off"
    await write_audit(
        session,
        actor,
        f"strategy.{status}",
        {"strategy_id": strategy_id, "version": version.version, "from": previous},
    )
    return version


async def promote(session: AsyncSession, strategy_id: str, actor: str = "api") -> StrategyVersion:
    """Advance the active version one lifecycle stage (candidate→paper→live)."""
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None or strategy.active_version_id is None:
        raise StrategyError(f"strategy {strategy_id!r} has no active version")
    version = await session.get(StrategyVersion, strategy.active_version_id)
    order = ["candidate", "paper", "live"]
    if version.status not in order or version.status == "live":
        raise StrategyError(f"cannot promote from status {version.status!r}")
    return await set_status(session, strategy_id, order[order.index(version.status) + 1], actor)
