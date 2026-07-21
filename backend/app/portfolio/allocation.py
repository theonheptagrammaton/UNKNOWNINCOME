"""Sermaye tahsisi (doc §24.3).

Yöntemler: **eşit-risk** (varsayılan — volatilite bütçesi, kovaryans-farkında),
ters volatilite (basit alternatif), **çeyrek Kelly** (tavanlı), manuel kilit.

**Tam Kelly YASAK.** Tam Kelly matematiksel olarak büyüme-optimaldir ama pratikte
%50 drawdown'ları normal sayar (doc §24.3); çeyrek Kelly beklenen büyümenin ~%94'ünü
varyansın ~%25'iyle verir. ``method="kelly"`` çağrısı bile reddedilir.

**Pazarlıksız tavan (kod sabiti, doc §24.3):** tek strateji ≤ %25 tahsis. Sembol
net ≤ %35 ve brüt kaldıraç ≤ 3x **çalışma-zamanı** limitleridir ve
:mod:`app.portfolio.limits` içinde gerçek açık maruziyete karşı uygulanır — tahsis
bir hedeftir, limit sert bir duvardır.

Klon testi (doc §24.7) eşit-risk'te **yapı gereği** geçer: iki birebir aynı (ρ=1)
strateji portföy volatilitesini düşürmez, dolayısıyla ekstra bütçe talep edemez;
ikisinin toplam tahsisi tek stratejininkine eşittir (her biri yarısını alır).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# ── Pazarlıksız tavan (doc §24.3) ────────────────────────────────────────────
MAX_STRATEGY_WEIGHT = 0.25  # tek strateji ≤ %25 tahsis (kod sabiti)
QUARTER_KELLY = 0.25  # tam Kelly'nin çeyreği — tam Kelly asla
CORRELATION_GATE = 0.70  # doc §24.2 — üstünde tahsis kısıtı veya red
DEFAULT_TARGET_VOL = 0.02  # portföy günlük getiri std hedefi (eşit-risk ölçeği)

ALLOCATION_METHODS = ("equal_risk", "inverse_vol", "kelly", "manual")


@dataclass
class StrategyAlloc:
    """Tahsis motorunun bir strateji için ihtiyacı olan minimum girdi."""

    strategy_id: str
    vol: float  # getiri serisinin dönem-başı std'i (> 0 olmalı)
    edge: float = 0.0  # ortalama dönem-başı getiri (yalnızca Kelly)
    symbol: str | None = None
    direction: int = 0  # +1 long-eğilimli, -1 short, 0 bilinmiyor
    locked_weight: float | None = None  # manuel kilit (operatör sabitler)


def allocate(
    strategies: list[StrategyAlloc],
    corr: pd.DataFrame | None = None,
    method: str = "equal_risk",
    target_vol: float = DEFAULT_TARGET_VOL,
) -> dict[str, float]:
    """Strateji → hedef sermaye ağırlığı (equity kesri) sözlüğü.

    Ağırlıklar sermaye kesridir (kaldıraç değil); brüt kaldıraç ve sembol tavanı
    çalışma-zamanında :mod:`limits` tarafından ayrıca uygulanır. Her ağırlık
    ``MAX_STRATEGY_WEIGHT``'e kırpılır. Boş girdi ⇒ boş sözlük.
    """
    if method == "kelly":
        pass  # çeyrek Kelly aşağıda; "kelly" adı çeyreği ima eder, tam Kelly değil
    if method not in ALLOCATION_METHODS:
        raise ValueError(f"unknown allocation method: {method!r}")
    if not strategies:
        return {}

    if method == "manual":
        weights = {s.strategy_id: float(s.locked_weight or 0.0) for s in strategies}
    elif method == "kelly":
        weights = _quarter_kelly(strategies)
    elif method == "inverse_vol":
        weights = _inverse_vol(strategies)
    else:  # equal_risk (varsayılan)
        weights = _equal_risk(strategies, corr, target_vol)

    # Pazarlıksız tek-strateji tavanı (doc §24.3).
    return {sid: min(w, MAX_STRATEGY_WEIGHT) for sid, w in weights.items()}


def full_kelly_forbidden() -> bool:
    """Tam Kelly asla kullanılmaz (doc §24.3). Niyet belgesi + test kancası."""
    return True


def correlation_gate_factor(rho: float, threshold: float = CORRELATION_GATE) -> float:
    """|ρ| > eşik olan yeni stratejinin tahsis çarpanı (doc §24.2, varsayılan kısıt).

    Eşikte 1.0 (kısıt yok), ρ→1'de 0.0 (klon tek slotu paylaşır). Aradaki
    ``(1−|ρ|)/(1−eşik)`` doğrusal kısıttır: korelasyonla orantılı (doc §24.2).
    ``ρ=0.85, eşik=0.70`` ⇒ 0.5 (yeni strateji tahsisinin yarısını alır).
    """
    r = abs(rho)
    if r <= threshold:
        return 1.0
    if r >= 1.0:
        return 0.0
    return (1.0 - r) / (1.0 - threshold)


# ── yöntemler ────────────────────────────────────────────────────────────────
def _inverse_vol(strategies: list[StrategyAlloc]) -> dict[str, float]:
    """Ağırlık ∝ 1/σ, toplam 1'e normalize (doc §24.3 basit alternatif)."""
    inv = {s.strategy_id: (1.0 / s.vol if s.vol > 0 else 0.0) for s in strategies}
    total = sum(inv.values())
    if total <= 0:
        return {s.strategy_id: 0.0 for s in strategies}
    return {sid: v / total for sid, v in inv.items()}


def _quarter_kelly(strategies: list[StrategyAlloc]) -> dict[str, float]:
    """f* = edge/varyans, çeyreği alınır, strateji başına ≤ %25 (doc §24.3).

    Negatif edge ⇒ 0 (kaybeden stratejiye sermaye yok). Tam Kelly asla; burada
    yalnızca ``QUARTER_KELLY`` katsayısı uygulanır.
    """
    out: dict[str, float] = {}
    for s in strategies:
        var = s.vol * s.vol
        f_star = (s.edge / var) if var > 0 else 0.0
        out[s.strategy_id] = max(0.0, min(QUARTER_KELLY * f_star, MAX_STRATEGY_WEIGHT))
    return out


def _equal_risk(
    strategies: list[StrategyAlloc], corr: pd.DataFrame | None, target_vol: float
) -> dict[str, float]:
    """Kovaryans-farkında eşit volatilite bütçesi (doc §24.3 varsayılan).

    Yön ters-vol ağırlıklarıdır (Σw=1); bu yön, portföy volatilitesi
    ``target_vol``'a oturacak biçimde ölçeklenir: ``g = target_vol / √(wᵀΣw)``,
    ``a = g·w``. Kovaryans Σ, korelasyon matrisi + stratejilerin vol'lerinden
    kurulur. ρ=1 klonlar Σ'yı tekilleştirir ve √(wᵀΣw) tek stratejininkine eşit
    kalır ⇒ toplam tahsis katlanmaz (klon testi).
    """
    ids = [s.strategy_id for s in strategies]
    vols = np.array([max(s.vol, 0.0) for s in strategies], dtype="float64")
    direction = _unit_inverse_vol(vols)
    sigma = _covariance(ids, vols, corr)
    port_var = float(direction @ sigma @ direction)
    if port_var <= 0:
        # Vol yok (hepsi sabit) ⇒ ters-vol yönünü olduğu gibi kullan.
        return dict(zip(ids, direction, strict=True))
    scale = target_vol / np.sqrt(port_var)
    weights = direction * scale
    return {sid: float(w) for sid, w in zip(ids, weights, strict=True)}


def _unit_inverse_vol(vols: np.ndarray) -> np.ndarray:
    """Ters-vol yön vektörü, toplamı 1 (sıfır vol ⇒ eşit ağırlığa düş)."""
    inv = np.where(vols > 0, 1.0 / np.where(vols > 0, vols, 1.0), 0.0)
    total = inv.sum()
    if total <= 0:
        n = len(vols)
        return np.full(n, 1.0 / n) if n else inv
    return inv / total


def _covariance(
    ids: list[str], vols: np.ndarray, corr: pd.DataFrame | None
) -> np.ndarray:
    """Σ = D·R·D, D = diag(vol), R = korelasyon (yoksa birim = korelasyonsuz)."""
    n = len(ids)
    if corr is None or corr.empty:
        r = np.eye(n)
    else:
        r = np.eye(n)
        for i, a in enumerate(ids):
            for j, b in enumerate(ids):
                if a in corr.index and b in corr.columns:
                    r[i, j] = float(corr.at[a, b])
    d = np.diag(vols)
    return d @ r @ d
