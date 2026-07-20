"""Stage 6 — leaderboard assembly (doc §7 Aşama 6).

One row per finalist combo: its genome, the symbol/tf context, the full §6.3 metric
set, the walk-forward layers, the Monte-Carlo band, the plateau verdict and any
engine-disagreement alarms. Rows are ranked by out-of-sample score; the total
number of combinations tried is carried at scan level (multiple-testing awareness,
§6.5 point 5) so the UI can show it.
"""

from __future__ import annotations

from app.backtest.config import RunConfig
from app.discovery.combine import Combo, combo_to_run_config
from app.discovery.config import ScanConfig
from app.discovery.optimize import OptimizeResult
from app.discovery.wfo import WFOReport


def build_entry(
    combo: Combo, config: ScanConfig, opt: OptimizeResult, wfo: WFOReport
) -> dict:
    """Assemble one leaderboard row (unranked)."""
    rc: RunConfig = combo_to_run_config(combo, config, opt.trigger_params, opt.filter_params)
    return {
        "combo": combo.genome_summary,
        "genome": rc.model_dump(mode="json"),
        "symbol": combo.symbol,
        "tf": combo.tf,
        "oos_score": wfo.oos_score,
        "is_score": opt.best_score,
        "oos_net_return": wfo.oos_mean_net_return,
        "oos_trades": wfo.oos_trades,
        "metrics": wfo.full_metrics,
        "wfo_layers": wfo.layers,
        "monte_carlo": wfo.monte_carlo,
        "plateau_ok": wfo.plateau_ok,
        "survived": wfo.survived,
        "status": "candidate" if wfo.survived else "finalist",
        "alarms": [],  # filled by the finalist cross-check
    }


def rank(entries: list[dict]) -> list[dict]:
    """Sort by OOS score desc (deterministic tiebreak) and stamp 1-based ranks."""
    ordered = sorted(
        entries,
        key=lambda e: (-(e["oos_score"] or 0.0), e["combo"]["trigger"], e["combo"]["filter"],
                       e["combo"]["exit"], e["symbol"], e["tf"]),
    )
    for i, e in enumerate(ordered):
        e["rank"] = i + 1
    return ordered
