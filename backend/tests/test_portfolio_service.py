"""Portföy servisi çekirdeği: korelasyon kapısı + görüntü (doc §24.2, §24.6, §24.7)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.portfolio.limits import PortfolioLimits, PortfolioPosition
from app.portfolio.service import StrategyStat, build_snapshot


def _series(values: list[float]) -> pd.Series:
    idx = pd.to_datetime(range(1, len(values) + 1), unit="D")
    return pd.Series(values, index=idx)


def _correlated_pair(rho: float, n: int = 60, seed: int = 3) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    a = rng.standard_normal(n)
    noise = rng.standard_normal(n)
    b = rho * a + np.sqrt(1 - rho * rho) * noise
    idx = pd.to_datetime(range(1, n + 1), unit="D")
    return pd.Series(a * 0.01, index=idx), pd.Series(b * 0.01, index=idx)


def test_correlation_gate_cuts_allocation_for_085_pair() -> None:
    """KABUL 5: 0.85 korelasyonlu yeni strateji tahsis kısıtıyla karşılanır (red değil)."""
    a, b = _correlated_pair(0.85)
    stats = [
        StrategyStat("A", "Alpha", "live", a, symbol="BTCUSDT"),
        StrategyStat("B", "Beta", "live", b, symbol="ETHUSDT"),
    ]
    snap = build_snapshot(stats, positions=[], equity=10_000.0, target_vol=0.004)
    rows = {r["strategy_id"]: r for r in snap["correlation_gate"]["rows"]}
    assert rows["A"]["gated"] and rows["B"]["gated"]  # ikisi de kapıda
    assert rows["A"]["rho"] > 0.70  # ölçülen korelasyon eşiğin üstünde
    assert 0.0 < rows["A"]["factor"] < 1.0  # kısıt (red değil): tahsis kesildi
    # Tahsis pozitif ama kısıtlı (reddedilmedi).
    targets = {row["strategy_id"]: row["target"] for row in snap["allocations"]}
    assert targets["A"] > 0.0 and targets["B"] > 0.0


def test_paper_strategies_appear_in_correlation_but_not_allocation() -> None:
    """Paper stratejiler matrise girer (doc §24.2) ama tahsis almaz (yalnızca canlı)."""
    live = _series([0.01, -0.02, 0.03, -0.01, 0.02])
    paper = _series([0.02, -0.01, 0.01, -0.02, 0.01])
    stats = [
        StrategyStat("L", "LiveOne", "live", live, symbol="BTCUSDT"),
        StrategyStat("P", "PaperOne", "paper", paper, symbol="ETHUSDT"),
    ]
    snap = build_snapshot(stats, positions=[], equity=10_000.0)
    assert set(snap["correlation"]["ids"]) == {"L", "P"}  # ikisi de matriste
    alloc_ids = {a["strategy_id"] for a in snap["allocations"]}
    assert alloc_ids == {"L"}  # yalnızca canlı tahsis alır


def test_net_exposure_and_concentration_warning() -> None:
    """Net maruziyet çubuğu + düz cümleli yoğunlaşma uyarısı (doc §24.6)."""
    positions = [PortfolioPosition("BTCUSDT", "long", 7_000.0)]  # 70% net long
    stats = [StrategyStat("A", "Alpha", "live", _series([0.01, 0.02]), symbol="BTCUSDT")]
    snap = build_snapshot(
        stats, positions=positions, equity=10_000.0,
        limits=PortfolioLimits(direction_concentration_pct=60.0),
    )
    net = {row["symbol"]: row for row in snap["net_exposure"]}
    assert net["BTCUSDT"]["net_pct"] == pytest.approx(70.0)
    assert net["BTCUSDT"]["cap_pct"] == 35.0
    assert any("net long" in w for w in snap["concentration_warnings"])


def test_snapshot_has_all_panel_sections() -> None:
    """UI paneli için gereken tüm bölümler mevcut (doc §24.6)."""
    stats = [StrategyStat("A", "Alpha", "live", _series([0.01, -0.01, 0.02]), symbol="BTCUSDT")]
    snap = build_snapshot(stats, positions=[], equity=10_000.0)
    for key in (
        "allocations", "correlation", "correlation_gate", "net_exposure",
        "contributions", "concentration_warnings", "caps", "method",
    ):
        assert key in snap
    assert snap["caps"]["max_strategy_allocation"] == 0.25
