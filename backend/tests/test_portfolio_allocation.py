"""Tahsis motoru + klon testi + tam-Kelly yasağı (doc §24.3, §24.7)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.portfolio.allocation import (
    MAX_STRATEGY_WEIGHT,
    QUARTER_KELLY,
    StrategyAlloc,
    allocate,
    correlation_gate_factor,
    full_kelly_forbidden,
)


def test_clone_total_allocation_equals_single() -> None:
    """KLON TESTİ (doc §24.7): birebir aynı iki strateji canlıya alınınca toplam
    tahsisleri tek stratejininkine EŞİT olur (iki katı değil) — her biri yarısını alır.
    """
    single = allocate(
        [StrategyAlloc("A", vol=0.05)], corr=None, method="equal_risk", target_vol=0.01
    )
    corr = pd.DataFrame([[1.0, 1.0], [1.0, 1.0]], index=["A", "B"], columns=["A", "B"])
    clones = allocate(
        [StrategyAlloc("A", vol=0.05), StrategyAlloc("B", vol=0.05)],
        corr=corr, method="equal_risk", target_vol=0.01,
    )
    assert sum(clones.values()) == pytest.approx(sum(single.values()), rel=1e-9)
    assert clones["A"] == pytest.approx(clones["B"], rel=1e-9)  # 50/50 split
    assert clones["A"] == pytest.approx(single["A"] / 2, rel=1e-9)


def test_uncorrelated_pair_deploys_more_than_a_clone_pair() -> None:
    """Kovaryans-farkındalık: korelasyonsuz çift, klon çiftinden daha çok sermaye
    dağıtabilir (aynı portföy volu için) — motor gerçekten korelasyonu kullanıyor."""
    ident = pd.DataFrame([[1.0, 1.0], [1.0, 1.0]], index=["A", "B"], columns=["A", "B"])
    orthogonal = pd.DataFrame([[1.0, 0.0], [0.0, 1.0]], index=["A", "B"], columns=["A", "B"])
    strategies = [StrategyAlloc("A", vol=0.05), StrategyAlloc("B", vol=0.05)]
    clone_sum = sum(allocate(strategies, ident, target_vol=0.01).values())
    div_sum = sum(allocate(strategies, orthogonal, target_vol=0.01).values())
    assert div_sum > clone_sum


def test_strategy_cap_is_never_exceeded() -> None:
    """Tek strateji ≤ %25 (doc §24.3 pazarlıksız), yüksek hedef vol'de bile."""
    weights = allocate(
        [StrategyAlloc("A", vol=0.01), StrategyAlloc("B", vol=0.5)],
        corr=None, method="equal_risk", target_vol=0.5,
    )
    assert all(w <= MAX_STRATEGY_WEIGHT + 1e-12 for w in weights.values())


def test_full_kelly_forbidden_only_quarter_is_used() -> None:
    """Tam Kelly ASLA (doc §24.3). Yüksek-edge strateji çeyrek Kelly + %25 tavanı."""
    assert full_kelly_forbidden() is True
    # edge/var = 0.1/0.04 = 2.5 (tam Kelly). Çeyreği 0.625; tavan 0.25.
    w = allocate([StrategyAlloc("A", vol=0.2, edge=0.1)], method="kelly")
    assert w["A"] == pytest.approx(min(MAX_STRATEGY_WEIGHT, QUARTER_KELLY * 2.5))
    assert w["A"] <= MAX_STRATEGY_WEIGHT + 1e-12
    # Negatif edge ⇒ sermaye yok.
    assert allocate([StrategyAlloc("B", vol=0.2, edge=-0.05)], method="kelly")["B"] == 0.0


def test_manual_lock_uses_operator_weights_capped() -> None:
    w = allocate([StrategyAlloc("A", vol=0.1, locked_weight=0.4)], method="manual")
    assert w["A"] == MAX_STRATEGY_WEIGHT  # 0.4 locked → capped to 0.25


def test_full_kelly_string_is_rejected() -> None:
    with pytest.raises(ValueError):
        allocate([StrategyAlloc("A", vol=0.2, edge=0.1)], method="full_kelly")


def test_correlation_gate_factor_proportional() -> None:
    """|ρ|>0.70 ⇒ korelasyonla orantılı kısıt (doc §24.2)."""
    assert correlation_gate_factor(0.60) == 1.0  # eşik altı, kısıt yok
    assert correlation_gate_factor(0.70) == 1.0  # tam eşikte
    assert correlation_gate_factor(0.85) == pytest.approx(0.5)  # kısıt
    assert correlation_gate_factor(1.0) == 0.0  # klon tek slotu paylaşır
    assert correlation_gate_factor(-0.9) < 0.5  # |ρ| kullanılır
