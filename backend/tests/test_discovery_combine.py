"""Stage 3 — role-based combination + category constraint (§7 Aşama 3)."""

from __future__ import annotations

import numpy as np

from app.discovery.candidates import SingleScan
from app.discovery.combine import build_combos, combo_to_run_config
from app.discovery.config import ScanConfig
from app.discovery.roles import role_for


def _scan(indicator_id: str, category: str, score: float, symbol: str = "BTCUSDT") -> SingleScan:
    return SingleScan(
        indicator_id=indicator_id,
        category=category,
        role=role_for(category),  # type: ignore[arg-type]
        symbol=symbol,
        tf="1h",
        score=score,
        num_trades=40,
        operand="k",
        output_cols=["x"],
        entry_vec=np.zeros(10),
    )


def _config() -> ScanConfig:
    return ScanConfig(
        symbols=["BTCUSDT"], timeframes=["1h"], combo_pool_per_role=8, top_n_combos=50
    )


def test_combos_span_three_distinct_categories() -> None:
    scans = [
        _scan("rsi", "momentum", 0.8),   # trigger
        _scan("cci", "momentum", 0.6),   # trigger
        _scan("obv", "volume", 0.7),     # filter
        _scan("atr", "volatility", 0.5),  # exit
    ]
    combos, tried = build_combos(scans, _config())
    assert tried == 2 * 1 * 1  # 2 triggers × 1 filter × 1 exit
    assert len(combos) == 2
    for c in combos:
        cats = {c.trigger.category, c.filter.category, c.exit.category}
        assert len(cats) == 3  # ≤ 1 indicator per category falls out of the role split
        assert role_for(c.trigger.category) == "trigger"
        assert role_for(c.filter.category) == "filter"
        assert role_for(c.exit.category) == "exit"
    # Ranked by mean member score, highest first.
    assert combos[0].trigger.indicator_id == "rsi"


def test_no_combo_without_all_three_roles() -> None:
    scans = [_scan("rsi", "momentum", 0.8), _scan("cci", "momentum", 0.6)]  # triggers only
    combos, tried = build_combos(scans, _config())
    assert combos == [] and tried == 0


def test_combo_to_run_config_is_a_valid_genome() -> None:
    scans = [
        _scan("rsi", "momentum", 0.8),
        _scan("obv", "volume", 0.7),
        _scan("atr", "volatility", 0.5),
    ]
    combos, _ = build_combos(scans, _config())
    rc = combo_to_run_config(combos[0], _config())
    assert rc.symbol == "BTCUSDT" and rc.tf == "1h"
    assert [i.id for i in rc.indicators] == ["rsi", "obv"]  # trigger + filter computed
    assert rc.rules.long_entry  # trigger entry AND filter confirm
    assert rc.risk_exit.enabled  # volatility-based stop/target is the exit leg


def test_combo_pool_caps_the_explosion() -> None:
    scans = [_scan(f"m{i}", "momentum", 1.0 - i * 0.01) for i in range(10)]
    scans += [_scan(f"v{i}", "volume", 0.5) for i in range(10)]
    scans += [_scan(f"x{i}", "volatility", 0.3) for i in range(10)]
    config = ScanConfig(
        symbols=["BTCUSDT"], timeframes=["1h"], combo_pool_per_role=3, top_n_combos=100
    )
    combos, tried = build_combos(scans, config)
    assert tried == 3 * 3 * 3  # capped to top-3 per role before combining
