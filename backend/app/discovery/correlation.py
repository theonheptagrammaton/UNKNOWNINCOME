"""Stage 2 — correlation elimination (doc §7 Aşama 2).

Indicators whose entry-signal series carry the same information (|ρ| > threshold)
are clustered; the highest-scored member represents the cluster and the rest are
dropped. This is what collapses the RSI + StochRSI + Williams %R chorus into a
single seat. Greedy and fully deterministic (score-desc, id-tiebreak).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ClusterItem:
    """One clustering candidate: an indicator + its pooled signal vector."""

    key: str  # indicator id
    score: float  # aggregate composite score across cells
    vector: np.ndarray = field(repr=False)  # pooled entry-signal series


def signal_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation of two signal vectors; 0 when undefined (flat/mismatched)."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    if a.std() == 0.0 or b.std() == 0.0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


@dataclass
class ClusterResult:
    survivors: list[ClusterItem]
    # representative key → absorbed keys (for the report / transparency)
    clusters: dict[str, list[str]]


def eliminate_correlated(items: list[ClusterItem], threshold: float) -> ClusterResult:
    """Keep one representative per |ρ|>threshold cluster (highest score wins)."""
    order = sorted(items, key=lambda it: (-it.score, it.key))
    absorbed: set[str] = set()
    survivors: list[ClusterItem] = []
    clusters: dict[str, list[str]] = {}
    for rep in order:
        if rep.key in absorbed:
            continue
        survivors.append(rep)
        clusters[rep.key] = []
        for other in order:
            if other.key == rep.key or other.key in absorbed:
                continue
            if abs(signal_correlation(rep.vector, other.vector)) > threshold:
                absorbed.add(other.key)
                clusters[rep.key].append(other.key)
    return ClusterResult(survivors=survivors, clusters=clusters)
