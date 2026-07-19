"""Stage 1 — single scan (doc §7 Aşama 1).

Every candidate indicator runs standalone, on every symbol × timeframe cell, with
a default rule synthesized from its shape (:mod:`signal_synth`). Each run yields a
§6.4 composite score plus its entry-signal vector (fed to Stage-2 correlation).
The indicator compute-cache (§5.5) makes the repeated computes across cells cheap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from app.backtest.engine import run_engine
from app.backtest.metrics import compute_metrics
from app.backtest.rules import build_signals, resolve_operands
from app.data.duckdb_query import query_funding, query_ohlcv
from app.discovery import signal_synth
from app.discovery.config import ScanConfig
from app.discovery.evaluate import MIN_BARS, entry_vector
from app.discovery.roles import Role, role_for
from app.indicators.compute import compute_indicator
from app.indicators.registry import get_registry

logger = logging.getLogger(__name__)


@dataclass
class SingleScan:
    """One indicator's standalone result on one symbol × tf cell."""

    indicator_id: str
    category: str
    role: Role
    symbol: str
    tf: str
    score: float
    num_trades: int
    operand: str
    output_cols: list[str]
    entry_vec: np.ndarray = field(repr=False)


def candidate_ids(config: ScanConfig) -> list[str]:
    """Registry ids to scan, per ``config.candidate`` (id-sorted, deterministic)."""
    reg = get_registry()
    sel = config.candidate
    if sel.mode == "ids":
        wanted = [i for i in sel.ids if i in reg and reg[i].available]
        return sorted(dict.fromkeys(wanted))
    if sel.mode == "categories":
        cats = set(sel.categories)
        return sorted(
            d.id for d in reg.values()
            if d.available and d.category in cats and role_for(d.category) is not None
        )
    # "all" — every available indicator whose category carries a combination role.
    return sorted(
        d.id for d in reg.values()
        if d.available and role_for(d.category) is not None
    )


def indicator_operand(
    market: str, symbol: str, tf: str, indicator_id: str, key: str = "k"
) -> tuple[str, list[str]]:
    """Resolve an indicator's primary operand string from its *actual* columns.

    Single-output indicators are reachable by the bare ``key``; multi-output ones by
    ``key.<first_output>``. Reading the real computed columns (cache HIT) avoids any
    registry-vs-runtime output-name drift.
    """
    frame = compute_indicator(market, symbol, tf, indicator_id, {})
    cols = [c for c in frame.columns if c != "ts"]
    if not cols:
        return "", []
    operand = key if len(cols) == 1 else f"{key}.{cols[0]}"
    return operand, cols


def _scan_one(config: ScanConfig, indicator_id: str, symbol: str, tf: str) -> SingleScan | None:
    """Run one indicator standalone on one cell; ``None`` on no-data/compute failure."""
    reg = get_registry()
    def_ = reg.get(indicator_id)
    if def_ is None:
        return None
    role = role_for(def_.category)
    if role is None:
        return None

    ohlcv = query_ohlcv(
        config.market, symbol, tf, config.start_ts, config.end_ts
    ).reset_index(drop=True)
    if len(ohlcv) < MIN_BARS:
        return None

    frame = compute_indicator(
        config.market, symbol, tf, indicator_id, {},
        start_ts=config.start_ts, end_ts=config.end_ts,
    )
    aligned = ohlcv[["ts"]].merge(frame, on="ts", how="left").reset_index(drop=True)
    cols = [c for c in aligned.columns if c != "ts"]
    if not cols:
        return None
    operand = "k" if len(cols) == 1 else f"k.{cols[0]}"

    ops = resolve_operands(ohlcv, {"k": aligned})
    rules = signal_synth.standalone_rules(indicator_id, def_.category, operand, config.direction)
    signals = build_signals(rules, ops, config.direction, len(ohlcv))

    funding = None
    if config.costs.funding_enabled:
        funding = query_funding(config.market, symbol, config.start_ts, config.end_ts)

    result = run_engine(ohlcv, signals, config.costs, config.capital, funding, config.risk_exit)
    metrics = compute_metrics(result, tf)
    return SingleScan(
        indicator_id=indicator_id,
        category=def_.category,
        role=role,
        symbol=symbol,
        tf=tf,
        score=float(metrics.get("composite_score") or 0.0),
        num_trades=int(metrics.get("num_trades") or 0),
        operand=operand,
        output_cols=cols,
        entry_vec=entry_vector(signals).to_numpy(dtype="float64"),
    )


def run_single_scan(
    config: ScanConfig, symbols: list[str], progress_cb=None
) -> list[SingleScan]:
    """Scan every candidate indicator × symbol × tf; returns all successful cells."""
    ids = candidate_ids(config)
    cells = [(s, tf) for s in symbols for tf in config.timeframes]
    results: list[SingleScan] = []
    total = max(1, len(ids))
    for i, indicator_id in enumerate(ids):
        for symbol, tf in cells:
            try:
                scan = _scan_one(config, indicator_id, symbol, tf)
            except Exception as exc:  # one bad indicator must not sink the scan
                logger.warning("single-scan %s %s/%s failed: %s", indicator_id, symbol, tf, exc)
                scan = None
            if scan is not None:
                results.append(scan)
        if progress_cb is not None:
            progress_cb((i + 1) / total)
    logger.info("stage1 single-scan: %d indicators × %d cells → %d results",
                len(ids), len(cells), len(results))
    return results
