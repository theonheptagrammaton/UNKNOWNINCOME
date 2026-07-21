"""Discovery pipeline orchestration — Aşama 1–6 (doc §7).

``run_scan`` is pure with respect to the database: it reads market data through the
DuckDB layer and reports progress through a callback, but never touches the ORM —
Stage-0 universe resolution and all persistence live in :mod:`app.discovery.service`.
Each stage is timed (the <2h-for-10×4 budget is measured from these logs), and the
whole run is deterministic for a fixed seed: Optuna is seeded, Monte-Carlo is
seeded, and every sort has an explicit tiebreak.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from app.discovery import leaderboard as lb
from app.discovery.candidates import SingleScan, run_single_scan
from app.discovery.combine import build_combos, combo_to_run_config
from app.discovery.config import ScanConfig, apply_fast_mode
from app.discovery.correlation import ClusterItem, eliminate_correlated
from app.discovery.deflation_gate import apply_deflation_gate
from app.discovery.finalist import compare, get_finalist_engine
from app.discovery.optimize import optimize_combo
from app.discovery.wfo import WFOReport, walk_forward

logger = logging.getLogger(__name__)

# progress_cb(stage_label, fraction 0..1, combos_tried)
ProgressCb = Callable[[str, float, int], None]


@dataclass
class ScanResult:
    leaderboard: list[dict]
    combos_tried: int
    alarms: list[dict]
    universe: list[str]
    stage_timings: dict[str, float] = field(default_factory=dict)

    @property
    def num_candidates(self) -> int:
        return sum(1 for e in self.leaderboard if e.get("survived"))


def _noop(stage: str, fraction: float, combos_tried: int) -> None:  # pragma: no cover
    pass


def _aggregate_for_correlation(scans: list[SingleScan]) -> list[ClusterItem]:
    """One pooled signal vector + mean score per indicator (Stage-2 input)."""
    by_id: dict[str, list[SingleScan]] = {}
    for s in scans:
        by_id.setdefault(s.indicator_id, []).append(s)
    items: list[ClusterItem] = []
    for indicator_id, group in sorted(by_id.items()):
        cells = sorted(group, key=lambda x: (x.symbol, x.tf))  # fixed pooling order
        vector = np.concatenate([g.entry_vec for g in cells]) if cells else np.zeros(0)
        score = float(np.mean([g.score for g in cells])) if cells else 0.0
        items.append(ClusterItem(key=indicator_id, score=score, vector=vector))
    return items


def run_scan(
    config: ScanConfig,
    symbols: list[str],
    progress_cb: ProgressCb | None = None,
    prior_trials: dict[str, int] | None = None,
) -> ScanResult:
    """Run Aşama 1–6 (incl. the 5.5 deflation gate) over ``symbols``.

    ``prior_trials`` maps each genome family hash to its all-time trial count from the
    ledger (doc §23.2); the service loads it before the run and records this scan's
    trials afterward. It defaults to empty so the pipeline stays database-free — the
    gate then penalizes only this scan's own selection breadth.
    """
    cb = progress_cb or _noop
    config = apply_fast_mode(config)
    if config.fast_mode:
        symbols = symbols[:2]
    timings: dict[str, float] = {}

    # ── Stage 1 — single scan ────────────────────────────────────────────────
    t0 = time.perf_counter()
    cb("stage1_single_scan", 0.02, 0)
    scans = run_single_scan(
        config, symbols, progress_cb=lambda f: cb("stage1_single_scan", 0.02 + 0.38 * f, 0)
    )
    timings["stage1_single_scan"] = time.perf_counter() - t0

    # ── Stage 2 — correlation elimination ────────────────────────────────────
    t0 = time.perf_counter()
    cb("stage2_correlation", 0.42, 0)
    cluster = eliminate_correlated(
        _aggregate_for_correlation(scans), config.correlation_threshold
    )
    surviving_ids = {it.key for it in cluster.survivors}
    surviving = [s for s in scans if s.indicator_id in surviving_ids]
    timings["stage2_correlation"] = time.perf_counter() - t0
    n_scanned = len({s.indicator_id for s in scans})
    logger.info("stage2: %d indicators → %d survivors", n_scanned, len(surviving_ids))

    # ── Stage 3 — role-based combination ─────────────────────────────────────
    t0 = time.perf_counter()
    combos, combos_tried = build_combos(surviving, config)
    cb("stage3_combination", 0.5, combos_tried)
    timings["stage3_combination"] = time.perf_counter() - t0
    logger.info("stage3: %d combos tried, %d carried forward", combos_tried, len(combos))

    # ── Stage 4 + 5 — Optuna then WFO, per combo ─────────────────────────────
    t0 = time.perf_counter()
    entries: list[dict] = []
    wfos: list[WFOReport] = []
    total = max(1, len(combos))
    for i, combo in enumerate(combos):
        opt = optimize_combo(combo, config)
        wfo = walk_forward(combo, config, opt)
        entries.append(lb.build_entry(combo, config, opt, wfo))
        wfos.append(wfo)
        cb("stage4_5_optimize_wfo", 0.48 + 0.42 * (i + 1) / total, combos_tried)
    timings["stage4_5_optimize_wfo"] = time.perf_counter() - t0

    # ── Stage 5.5 — deflation gate (doc §23.5, non-negotiable) ───────────────
    t0 = time.perf_counter()
    cb("stage5_5_deflation", 0.9, combos_tried)
    apply_deflation_gate(entries, wfos, config, combos_tried, prior_trials)
    timings["stage5_5_deflation"] = time.perf_counter() - t0
    logger.info(
        "stage5.5 deflation: %d/%d entries pass the gate",
        sum(1 for e in entries if e.get("gate_passed")), len(entries),
    )

    # ── Stage 6 — leaderboard + finalist cross-validation ────────────────────
    t0 = time.perf_counter()
    ranked = lb.rank(entries)
    alarms = _cross_validate(ranked, config, combos_tried, cb)
    timings["stage6_finalist"] = time.perf_counter() - t0
    cb("done", 1.0, combos_tried)

    logger.info(
        "scan complete: %d finalists, %d candidates, %d combos tried, %d alarms; timings=%s",
        len(ranked), sum(1 for e in ranked if e.get("survived")), combos_tried, len(alarms),
        {k: round(v, 2) for k, v in timings.items()},
    )
    return ScanResult(
        leaderboard=ranked, combos_tried=combos_tried, alarms=alarms,
        universe=symbols, stage_timings=timings,
    )


def _cross_validate(
    ranked: list[dict], config: ScanConfig, combos_tried: int, cb: ProgressCb
) -> list[dict]:
    """Re-run the top-K finalists on a second engine; collect disagreement alarms."""
    if not config.finalist.enabled or not ranked:
        return []
    engine = get_finalist_engine()
    alarms: list[dict] = []
    for entry in ranked[: config.finalist.top_k]:
        rc = _rebuild_run_config(entry, config)
        if rc is None:
            continue
        try:
            result = engine.verify(rc)
        except Exception as exc:  # a finalist failure must not sink the scan
            logger.warning("finalist verify failed for %s: %s", entry.get("combo"), exc)
            continue
        combo_key = "+".join(entry["combo"][k] for k in ("trigger", "filter", "exit"))
        found = compare(entry["metrics"], result, config.finalist.tolerance, combo_key)
        entry["alarms"] = [a.as_dict() for a in found]
        entry["finalist"] = {
            "engine": result.engine, "net_return": result.net_return,
            "num_trades": result.num_trades, "sharpe": result.sharpe,
        }
        alarms.extend(entry["alarms"])
    return alarms


def _rebuild_run_config(entry: dict, config: ScanConfig):
    """Reconstruct the finalist's RunConfig from its stored genome."""
    from app.backtest.config import RunConfig

    try:
        return RunConfig.model_validate(entry["genome"])
    except Exception:  # pragma: no cover - defensive
        return None


# combo_to_run_config is re-exported for the service/tests that build a genome.
__all__ = ["ScanResult", "run_scan", "combo_to_run_config"]
