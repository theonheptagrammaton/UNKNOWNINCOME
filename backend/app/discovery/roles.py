"""Indicator role taxonomy for role-based combination (doc §7 Aşama 3).

Combinations are built from **roles**, not at random: a *trigger* (entry signal,
usually momentum/crossover) + a *filter* (regime/trend confirmation) + an
*exit/risk* leg (volatility-based stop/target). Each registry category maps to
exactly one role, so a valid combo automatically spans three distinct categories —
the "en fazla 1 indikatör per kategori" constraint falls out for free.
"""

from __future__ import annotations

from typing import Literal

Role = Literal["trigger", "filter", "exit"]

# One role per §5.2 category (see indicators/registry.CATEGORIES).
ROLE_BY_CATEGORY: dict[str, Role] = {
    "momentum": "trigger",
    "overlap": "trigger",
    "price": "trigger",
    "pattern": "trigger",
    "trend": "filter",
    "cycle": "filter",
    "statistic": "filter",
    "volume": "filter",
    "volatility": "exit",
}


def role_for(category: str) -> Role | None:
    """Role for a registry category, or ``None`` if it plays no combination role."""
    return ROLE_BY_CATEGORY.get(category)
