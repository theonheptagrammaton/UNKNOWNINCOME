"""Learned slippage model (doc §26.1) — measure execution cost, don't assume it.

Today slippage is a **guess**: a fixed 5 bps or 0.05×ATR (``CostConfig``). This module
turns real fills into a **measurement**. Every real (live-venue) fill records the
*expected* reference price against the *realized* fill price; observations are bucketed
by ``(symbol, tf, order-notional tier, volatility tier)`` and, once a bucket has
``min_samples`` fills, the backtest uses that bucket's learned adverse slippage instead
of the assumption.

Two pazarlıksız consequences (doc §26.1, rule #13):

* **Real fills only.** A paper fill is *simulated* — feeding it back would teach the
  model its own guess. Only ``mode == "live"`` observations count toward the learned
  model. A dev seeder exists for tests and is tagged as synthetic; it never closes an
  acceptance criterion.
* **If learned is worse than assumed, past backtests are re-run** (doc §26.1). This
  module only *detects* that (:func:`worse_than_assumption`); the re-run is driven by
  :mod:`app.execution.slippage_reconcile`.

Sync-readable like every backtest input: the learned model is materialised to a small
JSON artifact under ``data_dir`` (the same "async collector → sync artifact" seam Faz 11
used for liquidations), so the synchronous engine reads it with no live DB driver.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

# ── Bucketing ────────────────────────────────────────────────────────────────
# Order size in quote (USDT) notional — a larger order eats deeper into the book.
NOTIONAL_EDGES: tuple[float, ...] = (1_000.0, 10_000.0, 100_000.0, 1_000_000.0)
# Volatility = ATR as a fraction of price; higher vol ⇒ wider spreads / more slip.
VOL_EDGES: tuple[float, ...] = (0.005, 0.01, 0.02, 0.04)

MIN_SAMPLES_DEFAULT = 50  # doc §26.1: N≥50 fills before a bucket is trusted


def _tier(value: float, edges: tuple[float, ...]) -> int:
    """Index of the half-open bucket ``value`` falls in (0 … len(edges))."""
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


def notional_tier(notional: float) -> int:
    return _tier(max(notional, 0.0), NOTIONAL_EDGES)


def vol_tier(atr: float, price: float) -> int:
    """Volatility tier from ATR/price (0 when price/ATR is unusable)."""
    if price <= 0 or atr <= 0:
        return 0
    return _tier(atr / price, VOL_EDGES)


def bucket_key(symbol: str, tf: str, notional: float, atr: float, price: float) -> str:
    """Stable ``symbol|tf|nt|vt`` bucket handle (also the JSON key)."""
    return f"{symbol}|{tf}|{notional_tier(notional)}|{vol_tier(atr, price)}"


def adverse_slippage_bps(expected: float, fill: float, side: str) -> float:
    """Signed adverse slippage in bps: positive = filled worse than expected.

    ``side`` is the order side ("buy"/"sell"). A buy filled above the reference and a
    sell filled below it are both *adverse* (positive); a favourable fill is negative.
    """
    if expected <= 0:
        return 0.0
    raw = (fill - expected) / expected
    signed = raw if side == "buy" else -raw
    return signed * 1e4


# ── Observation ──────────────────────────────────────────────────────────────
@dataclass
class FillObservation:
    """One real fill: what we expected to pay vs what we actually paid."""

    symbol: str
    tf: str
    side: str  # "buy" | "sell"
    expected_price: float  # the reference price the order was sent at
    fill_price: float  # realized fill (incl. real venue slippage)
    order_notional: float  # |qty| × fill_price, quote currency
    atr: float  # ATR at the signal bar (for the volatility tier)
    ts: int

    @property
    def slippage_bps(self) -> float:
        return adverse_slippage_bps(self.expected_price, self.fill_price, self.side)

    @property
    def bucket(self) -> str:
        return bucket_key(
            self.symbol, self.tf, self.order_notional, self.atr, self.fill_price
        )


# ── Learned model ────────────────────────────────────────────────────────────
@dataclass
class BucketModel:
    """One bucket's learned slippage. ``trusted`` iff ``samples ≥ min_samples``."""

    bps: float  # median adverse slippage bps over the bucket's fills
    samples: int
    trusted: bool


@dataclass
class LearnedSlippageModel:
    """Bucket → learned slippage, plus the fallback assumption for untrusted buckets."""

    buckets: dict[str, BucketModel] = field(default_factory=dict)
    min_samples: int = MIN_SAMPLES_DEFAULT

    def lookup_bps(
        self, symbol: str, tf: str, notional: float, atr: float, price: float
    ) -> float | None:
        """Learned adverse bps for a fill, or ``None`` when the bucket isn't trusted."""
        b = self.buckets.get(bucket_key(symbol, tf, notional, atr, price))
        return b.bps if (b is not None and b.trusted) else None

    @property
    def trusted_buckets(self) -> int:
        return sum(1 for b in self.buckets.values() if b.trusted)

    def to_dict(self) -> dict:
        return {
            "min_samples": self.min_samples,
            "buckets": {
                k: {"bps": round(b.bps, 6), "samples": b.samples, "trusted": b.trusted}
                for k, b in self.buckets.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict) -> LearnedSlippageModel:
        min_samples = int(payload.get("min_samples", MIN_SAMPLES_DEFAULT))
        buckets = {
            k: BucketModel(
                bps=float(v["bps"]), samples=int(v["samples"]), trusted=bool(v["trusted"])
            )
            for k, v in payload.get("buckets", {}).items()
        }
        return cls(buckets=buckets, min_samples=min_samples)


def learn(
    observations: list[FillObservation], min_samples: int = MIN_SAMPLES_DEFAULT
) -> LearnedSlippageModel:
    """Fold fills into per-bucket median slippage; ``trusted`` at ``min_samples`` fills."""
    grouped: dict[str, list[float]] = {}
    for obs in observations:
        grouped.setdefault(obs.bucket, []).append(obs.slippage_bps)
    buckets = {
        key: BucketModel(
            bps=statistics.median(bpses),
            samples=len(bpses),
            trusted=len(bpses) >= min_samples,
        )
        for key, bpses in grouped.items()
    }
    return LearnedSlippageModel(buckets=buckets, min_samples=min_samples)


def worse_than_assumption(
    model: LearnedSlippageModel, assumed_bps: float, *, tolerance_bps: float = 0.0
) -> list[tuple[str, float]]:
    """Trusted buckets whose learned slippage is worse than the assumption.

    Returns ``(bucket_key, learned_bps)`` for every trusted bucket where the learned
    adverse slippage exceeds ``assumed_bps + tolerance_bps`` — i.e. the assumption was
    optimistic and past backtests under-costed those fills (doc §26.1). This is the
    "acı verir; yap" signal: the reconciler re-runs the affected strategies.
    """
    threshold = assumed_bps + tolerance_bps
    return [
        (key, b.bps)
        for key, b in sorted(model.buckets.items())
        if b.trusted and b.bps > threshold
    ]


# ── Sync-readable artifact ───────────────────────────────────────────────────
def model_path() -> Path:
    return Path(settings.data_dir) / "slippage_model.json"


def materialize(model: LearnedSlippageModel, path: Path | None = None) -> Path:
    """Write the learned model to the sync-readable JSON artifact."""
    target = path or model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model.to_dict(), sort_keys=True, indent=2))
    return target


def load_model(path: Path | None = None) -> LearnedSlippageModel | None:
    """Load the materialised model, or ``None`` if it was never built."""
    target = path or model_path()
    if not target.exists():
        return None
    try:
        return LearnedSlippageModel.from_dict(json.loads(target.read_text()))
    except (ValueError, KeyError):
        return None
