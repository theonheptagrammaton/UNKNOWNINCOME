"""Unified indicator registry (doc §5.3).

TA-Lib and pandas-ta indicators are described by a single metadata schema so the
discovery pipeline (Phase 4) can read the parameter space mechanically. Custom
plugins in ``custom/`` join the same registry.

The registry is pure metadata — building it does not require market data. It is
assembled once and memoised; :func:`get_registry` is the single entry point.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Canonical OHLCV inputs, in file/column order.
OHLCV_INPUTS = ("open", "high", "low", "close", "volume")

# Faz 11 §25 alpha-surface inputs beyond OHLCV: the free taker-flow kline columns
# plus the open-interest / funding / liquidation streams the new primitives consume.
# They are valid indicator inputs but are not part of the base OHLCV frame.
ALPHA_INPUTS = (
    "taker_buy_base_volume",
    "number_of_trades",
    "open_interest",
    "funding_rate",
    "liq_buy_notional",
    "liq_sell_notional",
)

# Every input an indicator may legitimately declare.
VALID_INPUTS = OHLCV_INPUTS + ALPHA_INPUTS

# doc §5.2 categories (+ "overlap" kept distinct so moving averages read cleanly).
CATEGORIES = (
    "trend",
    "momentum",
    "volatility",
    "volume",
    "cycle",
    "pattern",
    "statistic",
    "overlap",
    "price",
)

Source = Literal["talib", "pandas_ta", "custom"]
ParamKind = Literal["int", "float", "categorical"]


class ParamSpec(BaseModel):
    """One tunable parameter: default plus the search bounds Phase 4 will sweep."""

    default: float
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[int] | None = None
    kind: ParamKind = "int"


class IndicatorDef(BaseModel):
    """A single registry entry — the §5.3 metadata record."""

    id: str
    name: str
    category: str
    source: Source
    inputs: list[str] = Field(default_factory=list)
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    signal_templates: list[str] = Field(default_factory=list)
    available: bool = True


# ── Parameter specs ──────────────────────────────────────────────────────────
# Curated bounds for well-known parameter names. Anything unmatched falls back
# to a type-based heuristic (``_fallback_spec``) so no indicator is left without
# a usable search range.
_PARAM_SPECS: dict[str, ParamSpec] = {
    "timeperiod": ParamSpec(default=14, min=2, max=200, step=1, kind="int"),
    "timeperiod1": ParamSpec(default=7, min=2, max=100, step=1, kind="int"),
    "timeperiod2": ParamSpec(default=14, min=2, max=100, step=1, kind="int"),
    "timeperiod3": ParamSpec(default=28, min=2, max=200, step=1, kind="int"),
    "fastperiod": ParamSpec(default=12, min=2, max=100, step=1, kind="int"),
    "slowperiod": ParamSpec(default=26, min=5, max=200, step=1, kind="int"),
    "signalperiod": ParamSpec(default=9, min=2, max=100, step=1, kind="int"),
    "fastk_period": ParamSpec(default=5, min=2, max=100, step=1, kind="int"),
    "slowk_period": ParamSpec(default=3, min=2, max=100, step=1, kind="int"),
    "slowd_period": ParamSpec(default=3, min=2, max=100, step=1, kind="int"),
    "fastd_period": ParamSpec(default=3, min=2, max=100, step=1, kind="int"),
    "nbdev": ParamSpec(default=1.0, min=0.5, max=4.0, step=0.5, kind="float"),
    "nbdevup": ParamSpec(default=2.0, min=0.5, max=4.0, step=0.5, kind="float"),
    "nbdevdn": ParamSpec(default=2.0, min=0.5, max=4.0, step=0.5, kind="float"),
    "acceleration": ParamSpec(default=0.02, min=0.01, max=0.2, step=0.01, kind="float"),
    "maximum": ParamSpec(default=0.2, min=0.1, max=0.5, step=0.05, kind="float"),
    "fastlimit": ParamSpec(default=0.5, min=0.01, max=0.99, step=0.01, kind="float"),
    "slowlimit": ParamSpec(default=0.05, min=0.01, max=0.99, step=0.01, kind="float"),
    "vfactor": ParamSpec(default=0.7, min=0.0, max=1.0, step=0.1, kind="float"),
    "penetration": ParamSpec(default=0.3, min=0.0, max=1.0, step=0.1, kind="float"),
    # pandas-ta knobs
    "length": ParamSpec(default=14, min=2, max=200, step=1, kind="int"),
    "fast": ParamSpec(default=12, min=2, max=100, step=1, kind="int"),
    "slow": ParamSpec(default=26, min=5, max=200, step=1, kind="int"),
    "signal": ParamSpec(default=9, min=2, max=100, step=1, kind="int"),
    "atr_length": ParamSpec(default=14, min=2, max=100, step=1, kind="int"),
    "multiplier": ParamSpec(default=3.0, min=1.0, max=6.0, step=0.5, kind="float"),
    "upper_length": ParamSpec(default=20, min=2, max=200, step=1, kind="int"),
    "lower_length": ParamSpec(default=20, min=2, max=200, step=1, kind="int"),
}

# Any TA-Lib parameter ending in ``matype`` selects a moving-average type (0..8).
_MATYPE_CHOICES = list(range(9))


def spec_for(name: str, default: float) -> ParamSpec:
    """Return the search spec for a parameter, curated where known."""
    if name.endswith("matype"):
        return ParamSpec(default=float(default), choices=list(_MATYPE_CHOICES), kind="categorical")
    if name in _PARAM_SPECS:
        spec = _PARAM_SPECS[name].model_copy()
        spec.default = float(default)
        return spec
    return _fallback_spec(default)


def curated_default(name: str) -> float:
    """Curated default for a known parameter name (0.0 if unknown)."""
    spec = _PARAM_SPECS.get(name)
    return spec.default if spec else 0.0


def _fallback_spec(default: float) -> ParamSpec:
    """Type-based bounds for an unrecognised parameter name."""
    if isinstance(default, bool):  # guard: bool is an int subclass
        return ParamSpec(default=float(default), choices=[0, 1], kind="categorical")
    if isinstance(default, int):
        lo = max(2, default // 2) if default else 1
        hi = max(100, default * 3)
        return ParamSpec(default=float(default), min=lo, max=hi, step=1, kind="int")
    # float
    lo = round(default * 0.25, 4) if default else 0.0
    hi = round(default * 4.0, 4) if default else 1.0
    return ParamSpec(default=float(default), min=lo, max=hi, step=0.05, kind="float")


# ── Signal templates ─────────────────────────────────────────────────────────
def signal_templates(category: str, n_outputs: int, source: str) -> list[str]:
    """Heuristic set of §5.4 primitives that fit an indicator's shape."""
    if category == "pattern":
        return ["pattern"]
    if category == "momentum":
        base = ["threshold_cross", "slope"]
        return base if n_outputs > 1 else ["threshold_cross", "midline_cross", "slope"]
    if category in ("trend", "overlap", "price"):
        return ["line_cross", "slope"]
    if category == "volatility":
        return ["band_touch"] if n_outputs >= 3 else ["slope", "regime"]
    if category == "volume":
        return ["slope", "threshold_cross"]
    if category == "cycle":
        return ["regime", "threshold_cross"]
    if category == "statistic":
        return ["threshold_cross", "slope"]
    return ["slope"]


# ── Registry assembly (memoised) ─────────────────────────────────────────────
_REGISTRY: dict[str, IndicatorDef] | None = None


def build_registry(*, include_custom: bool = True) -> dict[str, IndicatorDef]:
    """Assemble the registry from all sources. Precedence: custom > talib > pandas_ta."""
    from app.indicators.sources import build_pandas_ta_defs, build_talib_defs

    registry: dict[str, IndicatorDef] = {}
    # pandas-ta first (lowest precedence), then TA-Lib overrides, then custom.
    for build in (build_pandas_ta_defs, build_talib_defs):
        for d in build():
            registry[d.id] = d

    if include_custom:
        from app.indicators.loader import load_custom_defs

        for d in load_custom_defs():
            registry[d.id] = d

    logger.info(
        "indicator registry built: %d defs (talib=%d, pandas_ta=%d, custom=%d)",
        len(registry),
        sum(v.source == "talib" for v in registry.values()),
        sum(v.source == "pandas_ta" for v in registry.values()),
        sum(v.source == "custom" for v in registry.values()),
    )
    return registry


def get_registry(*, rebuild: bool = False) -> dict[str, IndicatorDef]:
    """Return the memoised registry, building it on first use."""
    global _REGISTRY
    if _REGISTRY is None or rebuild:
        _REGISTRY = build_registry()
    return _REGISTRY


def get_indicator(indicator_id: str) -> IndicatorDef | None:
    """Look up a single indicator definition by id."""
    return get_registry().get(indicator_id)


def list_indicators(
    category: str | None = None, source: str | None = None
) -> list[IndicatorDef]:
    """Registry entries, optionally filtered by category and/or source, id-sorted."""
    defs = get_registry().values()
    if category is not None:
        defs = [d for d in defs if d.category == category]
    if source is not None:
        defs = [d for d in defs if d.source == source]
    return sorted(defs, key=lambda d: d.id)
