"""The strategy genome (doc §8.1) — a named, reproducible ``RunConfig``.

A genome is deliberately *the same object a backtest runs*: ``{"name", "config"}``
where ``config`` is a validated :class:`RunConfig`. That equivalence is the whole
point — the paper bot evaluates the identical indicators/rules the backtest was
validated against, so paper↔backtest comparison is exact (doc §9.1) and there is no
second, drifting rule engine.

Every edit produces a *new immutable version* (doc §8.6); ``genome_hash`` gives each
one a stable identity for lineage, dedup and diff.
"""

from __future__ import annotations

import hashlib
import json

from app.backtest.config import RunConfig


class GenomeError(ValueError):
    """Raised when a genome payload is malformed."""


def normalize_genome(genome: dict) -> dict:
    """Validate + canonicalize a genome to ``{"name", "config"}``.

    ``name`` is required and non-empty; ``config`` must validate as a ``RunConfig``.
    The returned dict is JSON-canonical (config round-tripped through the model), so
    two logically-equal genomes normalize identically.
    """
    if not isinstance(genome, dict):
        raise GenomeError("genome must be an object")
    name = str(genome.get("name") or "").strip()
    if not name:
        raise GenomeError("genome.name is required")
    raw_config = genome.get("config")
    if raw_config is None:
        raise GenomeError("genome.config is required")
    try:
        config = RunConfig.model_validate(raw_config)
    except Exception as exc:  # pydantic ValidationError et al.
        raise GenomeError(f"invalid genome.config: {exc}") from exc
    if not config.symbol:
        raise GenomeError("genome.config.symbol is required")
    return {"name": name, "config": config.model_dump(mode="json")}


def genome_config(genome: dict) -> RunConfig:
    """Extract the runnable :class:`RunConfig` from a (raw or normalized) genome."""
    return RunConfig.model_validate(normalize_genome(genome)["config"])


def genome_hash(genome: dict) -> str:
    """Reproducible 16-char SHA-256 of the normalized genome (doc §6 rule #6)."""
    norm = normalize_genome(genome)
    payload = json.dumps(norm, sort_keys=True, separators=(",", ":"), default=float)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def diff_genomes(a: dict, b: dict) -> dict:
    """Flat path→{from,to} diff of two genomes (for the UI version diff, doc §8.1)."""
    fa = _flatten(normalize_genome(a))
    fb = _flatten(normalize_genome(b))
    keys = sorted(set(fa) | set(fb))
    changes: dict[str, dict] = {}
    for k in keys:
        va, vb = fa.get(k, _MISSING), fb.get(k, _MISSING)
        if va != vb:
            changes[k] = {
                "from": None if va is _MISSING else va,
                "to": None if vb is _MISSING else vb,
            }
    return changes


_MISSING = object()


def _flatten(obj: object, prefix: str = "") -> dict[str, object]:
    """Flatten nested dicts/lists into dotted paths for a readable diff."""
    out: dict[str, object] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out
