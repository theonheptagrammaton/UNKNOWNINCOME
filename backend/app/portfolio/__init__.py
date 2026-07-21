"""Portföy katmanı (doc §24, Faz 10).

v1'in en büyük mimari boşluğu: stratejiler tek başına değil, bir portföy olarak
değerlendirilir (kural 16). Bu paket beş parçadır:

- :mod:`correlation` — strateji getiri serileri arası kayan 90g Pearson matrisi.
- :mod:`allocation` — eşit-risk (varsayılan) | ters-vol | çeyrek-Kelly | manuel.
- :mod:`netting` — aynı sembolde birden çok strateji → tek pozisyon, risk bir kez.
- :mod:`limits` — portföy düzeyi risk limitleri (strateji limitlerinden ÖNCE).
- :mod:`service` — orkestrasyon + korelasyon kapısı + UI görüntüsü.

Limitler :class:`app.execution.risk.RiskLayer`'e enjekte edilir ve strateji
kapılarından önce değerlendirilir; portföy reddi de ``risk_events``'e düşer.
"""

from app.portfolio.limits import (
    AddedLeg,
    PortfolioDecision,
    PortfolioLimits,
    PortfolioPosition,
    PortfolioSnapshot,
    check_drawdown,
    check_open,
)

__all__ = [
    "AddedLeg",
    "PortfolioDecision",
    "PortfolioLimits",
    "PortfolioPosition",
    "PortfolioSnapshot",
    "check_drawdown",
    "check_open",
]
