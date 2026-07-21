"""Sembol bazında pozisyon netleştirme + PnL atfı (doc §24.4).

İki strateji aynı anda BTCUSDT long açarsa borsada **tek** pozisyon vardır
(one-way mod zaten bunu dayatıyor). O halde:

- Risk **bir kez** sayılır, iki kez değil. Aksi halde risk katmanı yalan söyler:
  beş strateji × %1 = %5 sanılır, gerçekte tek yönde %5'lik tek bahis vardır.
- PnL, katkıda bulunan stratejilere **orantılı** dağıtılır (``trades.attribution``).

Saf: sayıları alır, net pozisyonu ve atıf sözlüğünü döndürür. DB'siz.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Leg:
    """Bir stratejinin bir semboldeki bacağı (netleştirmeden önce)."""

    strategy_id: str
    symbol: str
    side: str  # long | short
    notional: float  # abs notional (qty × fiyat), ≥ 0


@dataclass
class NetPosition:
    """Bir sembolün netleştirilmiş tek pozisyonu."""

    symbol: str
    net_side: str  # long | short | flat
    net_notional: float  # net yön büyüklüğü (risk BİR KEZ)
    gross_notional: float  # toplam bacak büyüklüğü (atıf paydası)


def _signed(leg: Leg) -> float:
    return leg.notional if leg.side == "long" else -leg.notional


def net_position(legs: list[Leg]) -> NetPosition:
    """Aynı semboldeki bacakları tek net pozisyona indir (risk bir kez sayılır).

    Net = imzalı büyüklüklerin toplamı; brüt = mutlak büyüklüklerin toplamı.
    Farklı sembolleri karıştırma çağıranın işi (``net_by_symbol`` bunu yapar).
    """
    if not legs:
        return NetPosition(symbol="", net_side="flat", net_notional=0.0, gross_notional=0.0)
    symbol = legs[0].symbol
    signed = sum(_signed(leg) for leg in legs)
    gross = sum(abs(leg.notional) for leg in legs)
    side = "long" if signed > 0 else "short" if signed < 0 else "flat"
    return NetPosition(
        symbol=symbol, net_side=side, net_notional=abs(signed), gross_notional=gross
    )


def net_by_symbol(legs: list[Leg]) -> dict[str, NetPosition]:
    """Bacakları sembole göre grupla ve her sembolü netleştir."""
    groups: dict[str, list[Leg]] = defaultdict(list)
    for leg in legs:
        groups[leg.symbol].append(leg)
    return {sym: net_position(group) for sym, group in groups.items()}


def attribute_pnl(total_pnl: float, legs: list[Leg]) -> dict[str, float]:
    """Netleştirilmiş pozisyonun realize PnL'ini bacaklara orantılı atfet.

    Atıf, her bacağın **imzalı** notional payına orantılıdır: aynı yöndeki
    stratejiler pozitif pay, ters yöndeki (hedge eden) stratejiler negatif pay
    alır — böylece toplam korunur. Payda net yön büyüklüğüdür; net flat (tam
    hedge) ise atıf brüt paya düşer (bilgi kaybı olmadan toplam = PnL).

    Döndürülen sözlüğün değerleri toplamı ``total_pnl``'e eşittir (kuruş
    yuvarlamaları hariç). Tek strateji ⇒ tüm PnL ona gider.
    """
    if not legs:
        return {}
    signed = {leg.strategy_id: 0.0 for leg in legs}
    for leg in legs:
        signed[leg.strategy_id] += _signed(leg)
    net = sum(signed.values())
    denom = net if abs(net) > 1e-12 else sum(abs(v) for v in signed.values())
    if abs(denom) <= 1e-12:
        # Ne net ne brüt var (hepsi sıfır) ⇒ eşit böl.
        share = total_pnl / len(signed)
        return {sid: share for sid in signed}
    return {sid: total_pnl * (s / denom) for sid, s in signed.items()}
