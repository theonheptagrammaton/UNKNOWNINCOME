"""Execute a queued discovery scan and persist its progress + outcome.

Stage-0 universe resolution (the survivorship guard) needs the DB session, so it
lives here; the CPU-bound pipeline runs in a worker thread while this coroutine
commits live progress (stage + fraction + combos tried) every second, so the UI
can watch a long scan advance. Mirrors :mod:`app.backtest.service`.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.discovery.config import ScanConfig
from app.discovery.pipeline import ScanResult, run_scan
from app.discovery.store import write_leaderboard
from app.models.discovery import DiscoveryScan
from app.research import registry
from app.research.gate import gate_constants

logger = logging.getLogger(__name__)

_PROGRESS_INTERVAL_S = 1.0


async def _resolve_universe(session: AsyncSession, config: ScanConfig) -> list[str]:
    """Stage 0: explicit symbols win; else the snapshot valid at ``universe_as_of``;
    else the latest snapshot (doc §4.5 survivorship guard)."""
    from app.data.universe import latest_universe_symbols, universe_symbols_as_of

    if config.symbols:
        return list(config.symbols)
    if config.universe_as_of is not None:
        return await universe_symbols_as_of(session, config.market, config.universe_as_of)
    return await latest_universe_symbols(session, config.market)


async def execute_scan(session: AsyncSession, scan_id: str) -> None:
    """Run the discovery scan for ``scan_id`` and update its row (done | failed)."""
    scan = (
        await session.execute(select(DiscoveryScan).where(DiscoveryScan.id == scan_id))
    ).scalar_one_or_none()
    if scan is None:
        logger.warning("execute_scan: scan %s not found", scan_id)
        return

    scan.status = "running"
    scan.stage = "stage0_universe"
    await session.commit()

    try:
        config = ScanConfig.model_validate(scan.config)
        symbols = await _resolve_universe(session, config)
        if not symbols:
            raise ValueError("no symbols resolved for scan (empty universe)")

        # Aşama 5.5 inputs from outside this scan: the ledger's all-time family trial
        # counts (§23.2) and an audit row pinning the active gate constants — the only
        # place a threshold change is recorded, since they are code constants (§23.5).
        prior_trials = await registry.all_family_counts(session)
        await write_audit(session, "system", "deflation_gate.thresholds", gate_constants())
        await session.commit()

        holder = {"stage": "stage1_single_scan", "progress": 0.0, "combos": 0}

        def progress_cb(stage: str, fraction: float, combos_tried: int) -> None:
            holder["stage"] = stage
            holder["progress"] = fraction
            holder["combos"] = combos_tried

        task = asyncio.create_task(
            asyncio.to_thread(run_scan, config, symbols, progress_cb, prior_trials)
        )
        while not task.done():
            await asyncio.sleep(_PROGRESS_INTERVAL_S)
            scan.stage = holder["stage"]
            scan.progress = float(holder["progress"])
            scan.combos_tried = int(holder["combos"])
            await session.commit()
        result: ScanResult = await task

        # Append this scan's trials to the ledger so the next scan's DSR sees them
        # (§23.2: re-optimizing the same family keeps raising N).
        period = {"start_ts": config.start_ts, "end_ts": config.end_ts}
        rows = registry.build_trial_rows(scan_id, result.leaderboard, period)
        await registry.record_trials(session, rows)

        scan.leaderboard = _summary(result)
        scan.artifact_path = write_leaderboard(scan_id, _full_payload(result))
        scan.combos_tried = result.combos_tried
        scan.progress = 1.0
        scan.stage = "done"
        scan.status = "done"
        scan.error = None
        logger.info(
            "discovery %s done: %d finalists, %d candidates, %d combos, %d alarms",
            scan_id, len(result.leaderboard), result.num_candidates,
            result.combos_tried, len(result.alarms),
        )
    except Exception as exc:  # pragma: no cover - exercised via failed-scan test
        scan.status = "failed"
        scan.error = f"{type(exc).__name__}: {exc}"
        logger.warning("discovery %s failed: %s", scan_id, exc)
    await session.commit()


def _summary(result: ScanResult) -> dict:
    """Compact leaderboard for the DB row (full detail goes to the artifact)."""
    rows = []
    for e in result.leaderboard:
        m = e.get("metrics") or {}
        rows.append({
            "rank": e.get("rank"),
            "combo": e["combo"],
            "symbol": e["symbol"],
            "tf": e["tf"],
            "oos_score": e.get("oos_score"),
            "status": e.get("status"),
            "net_return": m.get("net_return"),
            "sharpe": m.get("sharpe"),  # raw (rule #14) — UI labels it "raw"
            "max_drawdown": m.get("max_drawdown"),
            "profit_factor": m.get("profit_factor"),
            "win_rate": m.get("win_rate"),
            "num_trades": m.get("num_trades"),
            "composite_score": m.get("composite_score"),
            "alarms": len(e.get("alarms") or []),
            # Aşama 5.5 deflation-gate columns (doc §23).
            "dsr": e.get("dsr"),
            "pbo": e.get("pbo"),
            "trials_total": e.get("trials_total"),
            "bh_excess": e.get("bh_excess"),
            "gate_passed": e.get("gate_passed"),
        })
    return {
        "combos_tried": result.combos_tried,
        "num_candidates": result.num_candidates,
        "num_alarms": len(result.alarms),
        "universe": result.universe,
        "stage_timings": result.stage_timings,
        "rows": rows,
    }


def _full_payload(result: ScanResult) -> dict:
    return {
        "combos_tried": result.combos_tried,
        "num_candidates": result.num_candidates,
        "num_alarms": len(result.alarms),
        "universe": result.universe,
        "stage_timings": result.stage_timings,
        "alarms": result.alarms,
        "leaderboard": result.leaderboard,
    }
