"""The producer interface — the modular self-improvement seam (doc §8.3).

§8.3's architecture splits self-improvement into three independent parts:

    Üretici (producer) → Doğrulayıcı (§6.5 defense line) → Terfi kapısı (§9.5)

The **producer** is the only part that changes when "which mechanism" changes:

* v1 — ``wfo_reopt`` : walk-forward re-optimization (refresh parameters on new data).
* v2 — ``genetic``   : cross/mutate genomes to *generate* new rule combinations.
* v3 — ``rl``        : a reinforcement-learning research rail.

This module defines the interface + a registry so the rest of the system (the
scheduler, the degradation handler, the API) talks to a ``StrategyGenerator`` and
never to a concrete mechanism. v1 is implemented in :mod:`app.strategy.reoptimize`;
the genetic/RL producers are **defined but empty** here (``propose`` raises), exactly
as §8.3 asks — "arayüz boş ama tanımlı kalsın" — so "net değil" never blocks today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class GenerationRequest:
    """Everything a producer needs to propose a new version of one strategy."""

    strategy_id: str
    genome: dict  # the current active genome: {"name", "config"}
    parent_version_id: str | None
    reason: str  # why we are regenerating: "scheduled" | "degrade:rolling_pf" | …
    seed: int = 42
    # Optional explicit training window (ms UTC); ``None`` ⇒ the producer derives it
    # from the available data (e.g. hold out the most recent test slice).
    train_window: tuple[int, int] | None = None
    trials: int | None = None  # optimizer budget override (None ⇒ producer default)


@dataclass
class GenerationResult:
    """A producer's proposal: a new genome + its §6.5 validation report."""

    genome: dict  # proposed new genome {"name", "config"}
    wfo_report: dict  # validation report (oos/plateau/monte-carlo + metrics)
    summary: dict = field(default_factory=dict)  # human-readable diff + score deltas
    survived: bool = False  # passed the §6.5 defense line
    regime: str | None = None  # regime the new version suits (doc §8.4)


@runtime_checkable
class StrategyGenerator(Protocol):
    """Anything that can propose a new strategy version (doc §8.3 Üretici)."""

    kind: str

    def propose(self, request: GenerationRequest) -> GenerationResult | None:
        """Propose a new version, or ``None`` when nothing viable was found."""
        ...


# ── registry ──────────────────────────────────────────────────────────────────
_GENERATORS: dict[str, StrategyGenerator] = {}


def register_generator(generator: StrategyGenerator) -> None:
    """Register a producer under its ``kind`` (last registration wins)."""
    _GENERATORS[generator.kind] = generator


def get_generator(kind: str) -> StrategyGenerator:
    """Look up a producer by kind; raises ``KeyError`` if unregistered/empty."""
    try:
        return _GENERATORS[kind]
    except KeyError as exc:
        raise KeyError(
            f"no strategy generator registered for kind {kind!r}; "
            f"available: {sorted(_GENERATORS)}"
        ) from exc


def available_generators() -> list[str]:
    return sorted(_GENERATORS)


# ── v2/v3 producers: defined but empty (doc §8.3) ─────────────────────────────
class _NotImplementedGenerator:
    """A named-but-empty producer: the interface exists, the mechanism does not yet."""

    kind = "abstract"
    note = "not implemented"

    def propose(self, request: GenerationRequest) -> GenerationResult | None:
        raise NotImplementedError(
            f"the {self.kind!r} producer is defined but not implemented yet "
            f"({self.note}); v1 uses 'wfo_reopt' (doc §8.3)"
        )


class GeneticGenerator(_NotImplementedGenerator):
    """v2 — genetic producer (cross/mutate genomes). Interface reserved (doc §8.3)."""

    kind = "genetic"
    note = "v2 — üretici katman (genome cross/mutation)"


class RLGenerator(_NotImplementedGenerator):
    """v3 — reinforcement-learning producer. Interface reserved (doc §8.3)."""

    kind = "rl"
    note = "v3 — opsiyonel araştırma rayı (RL)"


# The empty producers are registered so the seam is real and inspectable; calling
# them raises (they cannot silently no-op). v1 (``wfo_reopt``) registers itself on
# import of :mod:`app.strategy.reoptimize`.
register_generator(GeneticGenerator())
register_generator(RLGenerator())
