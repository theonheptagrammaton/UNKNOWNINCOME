"""Two-engine agreement check + disagreement alarm (doc §6.1).

The finalist re-run should broadly reproduce the primary run. When a key metric
diverges beyond its tolerance, an :class:`Alarm` is raised — the "iki motor
uyuşmazsa alarm" contract. The comparison is engine-agnostic (it takes the two
metric sets), so the alarm logic is unit-tested independently of any engine.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from app.discovery.finalist.base import FinalistEngine, FinalistResult

logger = logging.getLogger(__name__)


@dataclass
class Alarm:
    """A single metric disagreement between the primary and finalist engines."""

    combo_key: str
    engine: str
    metric: str
    primary: float
    finalist: float
    rel_diff: float
    tolerance: float

    def as_dict(self) -> dict:
        return asdict(self)


def _rel_diff(a: float, b: float) -> float:
    """Symmetric relative difference; robust near zero."""
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


def compare(
    primary_metrics: dict,
    finalist: FinalistResult,
    tolerance: dict[str, float],
    combo_key: str = "",
) -> list[Alarm]:
    """Return one alarm per metric that diverges beyond its tolerance (empty = agree)."""
    pairs = {
        "net_return": (primary_metrics.get("net_return"), finalist.net_return),
        "num_trades": (primary_metrics.get("num_trades"), finalist.num_trades),
        "sharpe": (primary_metrics.get("sharpe"), finalist.sharpe),
    }
    alarms: list[Alarm] = []
    for metric, (p, f) in pairs.items():
        tol = tolerance.get(metric)
        if tol is None or p is None or f is None:
            continue
        rel = _rel_diff(float(p), float(f))
        if rel > tol:
            alarm = Alarm(combo_key, finalist.engine, metric, float(p), float(f), rel, tol)
            logger.warning(
                "engine-disagreement alarm %s: %s primary=%.4f finalist=%.4f (rel=%.2f > %.2f)",
                combo_key, metric, float(p), float(f), rel, tol,
            )
            alarms.append(alarm)
    return alarms


def get_finalist_engine() -> FinalistEngine:
    """backtesting.py when it imports, else the always-available lean second opinion."""
    try:
        import backtesting  # noqa: F401

        from app.discovery.finalist.backtesting_py import BacktestingPyEngine

        return BacktestingPyEngine()
    except Exception as exc:  # ImportError or a broken build ⇒ fall back
        logger.info("backtesting.py unavailable (%s); using lean second-opinion engine", exc)
        from app.discovery.finalist.lean_second import LeanSecondEngine

        return LeanSecondEngine()
