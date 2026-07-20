"""Backtest run configuration + reproducible config hash (doc §6, rule #6).

A run is fully described by this config: symbol/tf/range, the indicators to
compute, the entry/exit rules built from §5.4 signal primitives, the cost model
(§6.2) and the capital/sizing. ``config_hash`` is a canonical SHA-256 of the
whole thing so the same config + seed reproduces bit-for-bit (pazarlıksız rule 6).

This is a deliberately *minimal* shape — the immutable, versioned strategy genome
(§8.1) arrives in Phase 5. Everything here is forward-compatible with it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["long", "short", "both"]
SlippageModel = Literal["fixed_bps", "atr"]


class IndicatorSpec(BaseModel):
    """One indicator to compute, addressed later by ``key`` in the rules."""

    key: str  # stable handle used by rules, e.g. "ema_fast"
    id: str  # registry id, e.g. "ema"
    params: dict[str, float] = Field(default_factory=dict)


BUILTIN_PRIMITIVES = (
    "threshold_cross", "line_cross", "slope", "band_touch", "regime", "pattern"
)


class RuleClause(BaseModel):
    """One signal primitive (§5.4) applied to resolved operands.

    ``args`` operands reference either a price field (open/high/low/close/volume),
    an indicator ``key`` (single-output), or ``key.output`` (multi-output).
    Constant operands (``level``) and enum operands (``direction``/``mode``/``rule``)
    are passed through verbatim.

    ``primitive`` is one of :data:`BUILTIN_PRIMITIVES` or a name contributed by a
    Python plugin (doc §8.6); it is typed ``str`` so plugin primitives validate.
    """

    primitive: str
    args: dict[str, str | float | int] = Field(default_factory=dict)


class Rules(BaseModel):
    """Entry/exit clause lists. Multiple clauses in a list are AND-combined."""

    long_entry: list[RuleClause] = Field(default_factory=list)
    long_exit: list[RuleClause] = Field(default_factory=list)
    short_entry: list[RuleClause] = Field(default_factory=list)
    short_exit: list[RuleClause] = Field(default_factory=list)


class CostConfig(BaseModel):
    """Cost model (§6.2). Defaults are ON; disabling flags the run red."""

    commission_bps: float = 4.0  # Binance USDT-M taker ≈ 0.04% per side
    slippage_model: SlippageModel = "fixed_bps"
    slippage_bps: float = 5.0  # fixed 5 bps
    atr_mult: float = 0.05  # 0.05 × ATR (when slippage_model == "atr")
    atr_length: int = 14
    funding_enabled: bool = True  # 8h historical perpetual funding


class CapitalConfig(BaseModel):
    """Starting capital and position sizing."""

    initial_cash: float = 10_000.0
    size_pct: float = 1.0  # fraction of equity deployed per position
    leverage: float = 1.0


class RiskExitConfig(BaseModel):
    """Volatility-based stop/target exits (doc §7 Aşama 3, §8.1 genome `exit`).

    Off by default (both multipliers ``None``) so every Phase-3 config behaves
    unchanged. When set, the ATR-at-entry defines a fixed stop/target band; the
    engine evaluates it at bar *close* and fills at the next open — lookahead-safe
    exactly like the signal path (rule #1). The discovery pipeline's "exit/risk"
    role wires these in.
    """

    atr_stop_mult: float | None = None  # stop distance = mult × ATR(entry)
    atr_target_mult: float | None = None  # target distance = mult × ATR(entry)
    atr_length: int = 14

    @property
    def enabled(self) -> bool:
        return self.atr_stop_mult is not None or self.atr_target_mult is not None


class RunConfig(BaseModel):
    """A complete, reproducible backtest request."""

    market: str = "binance_usdm"
    symbol: str
    tf: str
    start_ts: int | None = None
    end_ts: int | None = None
    direction: Direction = "both"
    indicators: list[IndicatorSpec] = Field(default_factory=list)
    rules: Rules = Field(default_factory=Rules)
    costs: CostConfig = Field(default_factory=CostConfig)
    capital: CapitalConfig = Field(default_factory=CapitalConfig)
    risk_exit: RiskExitConfig = Field(default_factory=RiskExitConfig)
    seed: int = 42


def canonical_config(config: RunConfig) -> str:
    """Canonical JSON of a config: sorted keys, compact separators, floats as floats.

    Excludes nothing — the whole config participates in the hash. ``seed`` is part
    of the hash so a different seed is a different run.
    """
    payload = config.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=float)


def config_hash(config: RunConfig) -> str:
    """Reproducible 16-char SHA-256 of the canonical config (doc §6, rule #6)."""
    return hashlib.sha256(canonical_config(config).encode()).hexdigest()[:16]
