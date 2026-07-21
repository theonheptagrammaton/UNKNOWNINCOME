"""The experiment ledger — canonical family hash + append-only persistence (§23.2).

A *genome family* is the structural identity of a strategy independent of its tuned
parameters: its trigger + filter + exit indicators, bound to a symbol × timeframe
cell and a direction. Re-optimizing the same strategy keeps that identity, so every
re-opt maps to the same :func:`genome_family_hash` and adds to the family's all-time
trial count — the number the Deflated Sharpe Ratio penalizes (doc §23.2).

The hash is canonical (sorted keys, compact separators, SHA-256) so it reproduces
across processes and runs, exactly like ``discovery.config.config_hash`` (rule #6).
The pure builders (:func:`genome_family_hash`, :func:`build_trial_rows`) are tested
without a database; the two ``async`` helpers do the append-only I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research import ExperimentTrial


def genome_family_hash(
    *, trigger: str, filter: str, exit: str, symbol: str, tf: str, direction: str
) -> str:
    """Reproducible 16-char hash of a strategy family (§23.2).

    Excludes tuned parameters and seed on purpose: two Optuna runs over the same
    trigger/filter/exit on the same symbol × tf are the *same hypothesis* and must
    share a hash so their trials accumulate.
    """
    payload = {
        "trigger": trigger,
        "filter": filter,
        "exit": exit,
        "symbol": symbol,
        "tf": tf,
        "direction": direction,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def family_hash_for_entry(entry: dict) -> str:
    """Family hash for a leaderboard entry (its ``combo`` summary + genome direction)."""
    combo = entry["combo"]
    direction = (entry.get("genome") or {}).get("direction", "both")
    return genome_family_hash(
        trigger=combo["trigger"],
        filter=combo["filter"],
        exit=combo["exit"],
        symbol=combo["symbol"],
        tf=combo["tf"],
        direction=direction,
    )


def build_trial_rows(scan_id: str, entries: list[dict], period: dict) -> list[dict]:
    """One append-only ledger row per leaderboard entry (pure — no DB, no clock).

    ``is_metrics``/``oos_metrics`` carry the *raw* numbers so the ledger stays an
    honest record of what was tried, independent of any later gate decision.
    """
    rows: list[dict] = []
    for e in entries:
        metrics = e.get("metrics") or {}
        rows.append({
            "scan_id": scan_id,
            "genome_hash": family_hash_for_entry(e),
            "symbol": e["symbol"],
            "tf": e["tf"],
            "period": period,
            "is_metrics": {"is_score": e.get("is_score"), "sharpe": metrics.get("sharpe")},
            "oos_metrics": {
                "oos_score": e.get("oos_score"),
                "oos_net_return": e.get("oos_net_return"),
                "oos_trades": e.get("oos_trades"),
                "sharpe": metrics.get("sharpe"),
            },
            "stage": e.get("status", "finalist"),
        })
    return rows


async def record_trials(session: AsyncSession, rows: list[dict]) -> int:
    """Append ledger rows (caller commits). Returns how many were written."""
    for r in rows:
        session.add(ExperimentTrial(**r))
    return len(rows)


async def family_counts(
    session: AsyncSession, hashes: Iterable[str]
) -> dict[str, int]:
    """All-time trial count per genome family, restricted to ``hashes`` (§23.2).

    This is the cross-scan number: it sums every row ever written for each family, so
    a strategy re-optimized across many scans reads back its full history.
    """
    wanted = list({h for h in hashes})
    if not wanted:
        return {}
    stmt = (
        select(ExperimentTrial.genome_hash, func.count())
        .where(ExperimentTrial.genome_hash.in_(wanted))
        .group_by(ExperimentTrial.genome_hash)
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}


async def all_family_counts(session: AsyncSession) -> dict[str, int]:
    """All-time trial count for **every** genome family (§23.2).

    A scan does not know which families it will produce until it runs, so the service
    loads the whole map up front and the gate looks up the ones it needs. Families are
    structural (indicator triple × symbol × tf × direction), so the map stays bounded.
    """
    stmt = select(ExperimentTrial.genome_hash, func.count()).group_by(
        ExperimentTrial.genome_hash
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}
