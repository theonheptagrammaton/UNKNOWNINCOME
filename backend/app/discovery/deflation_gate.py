"""Aşama 5.5 wiring — turn WFO survivors into gate verdicts (doc §23.5).

The pure statistics live in :mod:`app.research.deflation` / :mod:`app.research.gate`;
this module assembles their inputs from a scan's finalist entries and their walk-forward
reports, then stamps each entry with ``dsr``, ``pbo``, ``trials_total``, the buy & hold
comparison and the pass/fail verdict — demoting anything that fails to ``rejected``.

Two inputs come from *outside* a single scan and are threaded in, keeping the pipeline
database-free:

* ``prior_trials`` — each genome family's all-time trial count from the ledger
  (:mod:`app.research.registry`), so re-optimizing the same idea keeps raising N.
* ``combos_tried`` — this scan's selection breadth; the honest multiple-testing N for
  *any* winner is at least how many combos we searched.
"""

from __future__ import annotations

import logging

import numpy as np

from app.data.duckdb_query import query_ohlcv
from app.discovery.config import ScanConfig
from app.discovery.wfo import WFOReport
from app.research.deflation import pbo_cscv
from app.research.gate import GateInputs, evaluate_gate, sharpe_moments
from app.research.registry import family_hash_for_entry

logger = logging.getLogger(__name__)

_PBO_SPLITS = 16


def _trial_sharpes(wfos: list[WFOReport]) -> list[float]:
    """Per-trade OOS Sharpe of every evaluated combo — the sample for Var[SR]."""
    out: list[float] = []
    for w in wfos:
        sr, _, _, _ = sharpe_moments(np.asarray(w.oos_trade_returns, dtype="float64"))
        out.append(sr)
    return out


def _var_sr(trial_sharpes: list[float]) -> float:
    """Variance of the trial Sharpe estimates (scan-level input to SR*₀, §23.3).

    Falls back to the analytic null variance ``1/(T̄−1)`` when the empirical spread is
    unavailable (fewer than two trials or a degenerate zero variance)."""
    arr = np.asarray(trial_sharpes, dtype="float64")
    if arr.size >= 2:
        v = float(arr.var(ddof=1))
        if v > 0:
            return v
    return 1.0  # conservative: a wide null spread keeps the benchmark honestly high


def _buy_hold_oos_mean(config: ScanConfig, symbol: str, tf: str, layers: list[dict]) -> float:
    """Mean buy & hold return over the same OOS test windows the strategy was scored on.

    Apples-to-apples with ``oos_mean_net_return`` (both are mean per-fold returns), so
    the "OOS return ≤ B&H" check compares like with like."""
    if not layers:
        return 0.0
    df = query_ohlcv(config.market, symbol, tf, config.start_ts, config.end_ts)
    if df.empty:
        return 0.0
    ts = df["ts"].to_numpy(dtype="int64")
    close = df["close"].to_numpy(dtype="float64")
    rets: list[float] = []
    for lyr in layers:
        lo, hi = int(lyr["test_start"]), int(lyr["test_end"])
        mask = (ts >= lo) & (ts <= hi)
        window = close[mask]
        if window.size >= 2 and window[0] > 0:
            rets.append(float(window[-1] / window[0] - 1.0))
    return float(np.mean(rets)) if rets else 0.0


def _pbo_by_cell(entries: list[dict], wfos: list[WFOReport]) -> dict[tuple[str, str], float | None]:
    """One PBO per symbol × tf cohort from its combos' aligned per-bar returns (§23.4).

    ``None`` when a cohort cannot be cross-validated (fewer than two combos, or too few
    shared bars) — the gate treats that as a failure, never a pass."""
    cells: dict[tuple[str, str], list[np.ndarray]] = {}
    for e, w in zip(entries, wfos, strict=True):
        series = np.asarray(w.full_bar_returns, dtype="float64")
        if series.size:
            cells.setdefault((e["symbol"], e["tf"]), []).append(series)

    out: dict[tuple[str, str], float | None] = {}
    for cell, series_list in cells.items():
        # Align on the shared bar count (same symbol × tf ⇒ same axis; guard anyway).
        lengths = [s.size for s in series_list]
        width = min(lengths)
        aligned = [s[:width] for s in series_list]
        matrix = np.column_stack(aligned) if len(aligned) >= 2 else None
        if matrix is None or width < _PBO_SPLITS:
            out[cell] = None
            continue
        try:
            out[cell] = pbo_cscv(matrix, n_splits=_PBO_SPLITS)
        except ValueError as exc:  # uncomputable ⇒ conservative fail
            logger.debug("PBO uncomputable for %s: %s", cell, exc)
            out[cell] = None
    return out


def apply_deflation_gate(
    entries: list[dict],
    wfos: list[WFOReport],
    config: ScanConfig,
    combos_tried: int,
    prior_trials: dict[str, int] | None = None,
) -> None:
    """Run Aşama 5.5 in place: stamp gate fields on ``entries`` and demote failures.

    ``entries`` and ``wfos`` are parallel (one WFO report per entry). The heavy return
    arrays on ``wfos`` are consumed here and never persisted — only scalar verdicts land
    on the entries.
    """
    prior_trials = prior_trials or {}
    var_sr = _var_sr(_trial_sharpes(wfos))
    pbo_by_cell = _pbo_by_cell(entries, wfos)

    for e, w in zip(entries, wfos, strict=True):
        family = family_hash_for_entry(e)
        # Honest multiple-testing N: this scan's breadth + the family's all-time history.
        n_trials = combos_tried + prior_trials.get(family, 0)
        sr, skew, kurt, _ = sharpe_moments(np.asarray(w.oos_trade_returns, dtype="float64"))
        bh = _buy_hold_oos_mean(config, e["symbol"], e["tf"], e.get("wfo_layers", []))

        result = evaluate_gate(GateInputs(
            sr=sr,
            skew=skew,
            kurtosis=kurt,
            oos_trades=int(e.get("oos_trades") or 0),
            n_trials=n_trials,
            var_sr=var_sr,
            pbo=pbo_by_cell.get((e["symbol"], e["tf"])),
            oos_net_return=float(e.get("oos_net_return") or 0.0),
            bh_return=bh,
        ))

        e["genome_hash"] = family
        e["trials_total"] = n_trials
        e["dsr"] = result.dsr
        e["sr_star"] = result.sr_star
        e["pbo"] = result.pbo
        e["bh_return"] = bh
        e["bh_excess"] = float(e.get("oos_net_return") or 0.0) - bh
        e["gate_passed"] = result.passed
        e["gate_reasons"] = result.reasons
        # The gate is the final say on candidacy (§23.5): a WFO survivor that fails any
        # hard check is demoted to "rejected" and can no longer be promoted.
        if e.get("survived") and not result.passed:
            e["survived"] = False
            e["status"] = "rejected"
