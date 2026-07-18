"""TA-Lib and pandas-ta adapters: metadata discovery + compute dispatch.

Both libraries are wrapped behind the :class:`~app.indicators.registry.IndicatorDef`
schema. TA-Lib metadata comes free from its ``abstract`` API; pandas-ta has no
introspection API, so its indicators are probed once on a synthetic frame to
discover output columns. Output column names are normalised to stable,
parameter-independent tokens so cache keys stay consistent across parameters.
"""

from __future__ import annotations

import inspect
import logging

import numpy as np
import pandas as pd

from app.indicators.registry import (
    OHLCV_INPUTS,
    IndicatorDef,
    ParamSpec,
    curated_default,
    signal_templates,
    spec_for,
)

logger = logging.getLogger(__name__)

_GENERIC_OUTPUTS = {"real", "integer"}

# ── TA-Lib ───────────────────────────────────────────────────────────────────
_TALIB_GROUP_CATEGORY: dict[str, str] = {
    "Overlap Studies": "overlap",
    "Momentum Indicators": "momentum",
    "Volatility Indicators": "volatility",
    "Volume Indicators": "volume",
    "Cycle Indicators": "cycle",
    "Pattern Recognition": "pattern",
    "Statistic Functions": "statistic",
    "Price Transform": "price",
}
# Math groups are transforms/operators, not signal sources — excluded (§5.1).
_TALIB_SKIP_GROUPS = {"Math Operators", "Math Transform"}
# Category overrides where the TA-Lib group is misleading.
_TALIB_CATEGORY_OVERRIDE = {"bbands": "volatility"}


def _flatten_inputs(input_names: dict) -> list[str]:
    """Flatten TA-Lib ``input_names`` values into the OHLCV columns required."""
    needed: list[str] = []
    for value in input_names.values():
        if isinstance(value, str):
            needed.append(value)
        else:
            needed.extend(value)
    # Canonical order, de-duplicated.
    return [c for c in OHLCV_INPUTS if c in needed]


def _talib_output_names(fid: str, raw_names: list[str]) -> list[str]:
    """Stable output column names for a TA-Lib function."""
    if len(raw_names) == 1 and raw_names[0] in _GENERIC_OUTPUTS:
        return [fid]
    return [
        n if n not in _GENERIC_OUTPUTS else f"{fid}_{i}" for i, n in enumerate(raw_names)
    ]


def build_talib_defs() -> list[IndicatorDef]:
    """Auto-register every usable TA-Lib function from its abstract metadata."""
    try:
        import talib
        from talib import abstract
    except Exception as exc:  # pragma: no cover - talib always present in CI
        logger.warning("TA-Lib unavailable, skipping: %s", exc)
        return []

    defs: list[IndicatorDef] = []
    for group, names in talib.get_function_groups().items():
        if group in _TALIB_SKIP_GROUPS:
            continue
        category = _TALIB_GROUP_CATEGORY.get(group, "statistic")
        for name in names:
            info = abstract.Function(name).info
            inputs = _flatten_inputs(info["input_names"])
            # Skip functions needing non-price array inputs (e.g. MAVP's "periods").
            if any(c not in OHLCV_INPUTS for c in _raw_input_cols(info["input_names"])):
                continue
            fid = name.lower()
            params = {p: spec_for(p, d) for p, d in info["parameters"].items()}
            outputs = _talib_output_names(fid, list(info["output_names"]))
            defs.append(
                IndicatorDef(
                    id=fid,
                    name=info["display_name"] or name,
                    category=_TALIB_CATEGORY_OVERRIDE.get(fid, category),
                    source="talib",
                    inputs=inputs,
                    params=params,
                    outputs=outputs,
                    signal_templates=signal_templates(
                        _TALIB_CATEGORY_OVERRIDE.get(fid, category), len(outputs), "talib"
                    ),
                )
            )
    return defs


def _raw_input_cols(input_names: dict) -> list[str]:
    cols: list[str] = []
    for value in input_names.values():
        cols.extend([value] if isinstance(value, str) else value)
    return cols


def compute_talib(def_: IndicatorDef, ohlcv: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Compute a TA-Lib indicator; returns a frame of the def's output columns."""
    from talib import abstract

    inputs = {c: ohlcv[c].to_numpy(dtype="float64") for c in OHLCV_INPUTS if c in ohlcv}
    raw = abstract.Function(def_.id.upper())(inputs, **_coerce(def_, params))
    arrays = raw if isinstance(raw, list) else [raw]
    return pd.DataFrame(
        {
            name: np.asarray(arr, dtype="float64")
            for name, arr in zip(def_.outputs, arrays, strict=False)
        }
    )


# ── pandas-ta ────────────────────────────────────────────────────────────────
_PTA_CATEGORY: dict[str, str] = {
    "momentum": "momentum",
    "overlap": "overlap",
    "trend": "trend",
    "volatility": "volatility",
    "volume": "volume",
    "cycle": "cycle",
    "statistics": "statistic",
    "candle": "pattern",
}
# Repainting / forward-displaced / multi-series-arg / non-signal indicators.
_PTA_EXCLUDE = {
    "zigzag", "pivots", "ichimoku", "tos_stdevall", "hilo", "alligator", "smc",
    "exhc", "ha", "cdl_pattern", "cdl_z", "short_run", "long_run", "vhm", "slope",
    "increasing", "decreasing", "amat", "decay", "log_return", "percent_return",
    "pvol", "pvr",
}
# pandas-ta parameter names we expose as tunable (curated defaults in registry).
_PTA_NUMERIC = {
    "length", "fast", "slow", "signal", "atr_length", "multiplier",
    "upper_length", "lower_length",
}


def _probe_frame(n: int = 240) -> pd.DataFrame:
    """Deterministic synthetic OHLCV with a UTC DatetimeIndex for probing."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.standard_normal(n))
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    open_ = close + rng.standard_normal(n) * 0.2
    volume = rng.random(n) * 1000 + 100
    idx = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def stable_name(column: str) -> str:
    """Strip embedded parameter values from a pandas-ta column (``SUPERT_7_3.0`` → ``supert``)."""
    parts = [tok for tok in str(column).split("_") if not _is_number(tok)]
    return "_".join(parts).lower() or str(column).lower()


def _pta_result_frame(result: pd.Series | pd.DataFrame) -> pd.DataFrame:
    if isinstance(result, pd.Series):
        return result.to_frame()
    return result


def build_pandas_ta_defs() -> list[IndicatorDef]:
    """Probe pandas-ta indicators once on a synthetic frame; register those that work."""
    try:
        import pandas_ta as ta
    except Exception as exc:  # pragma: no cover
        logger.warning("pandas-ta unavailable, skipping: %s", exc)
        return []

    try:
        import talib
        talib_ids = {f.lower() for f in talib.get_functions()}
    except Exception:  # pragma: no cover
        talib_ids = set()

    probe = _probe_frame()
    in_cols = set(OHLCV_INPUTS)
    defs: list[IndicatorDef] = []
    for category, names in ta.Category.items():
        our_category = _PTA_CATEGORY.get(category)
        if our_category is None:
            continue
        for name in names:
            if name in talib_ids or name in _PTA_EXCLUDE:
                continue
            try:
                res = getattr(probe.ta, name)()
            except Exception:
                continue
            if res is None:
                continue
            frame = _pta_result_frame(res)
            cols = list(frame.columns)
            if set(cols) <= in_cols or frame.empty:
                continue  # bogus (echoed inputs) or nothing computed
            outputs = _dedupe([stable_name(c) for c in cols])
            sig = inspect.signature(getattr(ta, name))
            params = {
                p: spec_for(p, curated_default(p))
                for p in sig.parameters
                if p in _PTA_NUMERIC
            }
            inputs = [c for c in OHLCV_INPUTS if c in sig.parameters] or ["close"]
            defs.append(
                IndicatorDef(
                    id=name,
                    name=name.replace("_", " ").upper(),
                    category=our_category,
                    source="pandas_ta",
                    inputs=inputs,
                    params=params,
                    outputs=outputs,
                    signal_templates=signal_templates(our_category, len(outputs), "pandas_ta"),
                )
            )
    return defs


def _dedupe(items: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for it in items:
        if it in seen:
            seen[it] += 1
            out.append(f"{it}{seen[it]}")
        else:
            seen[it] = 0
            out.append(it)
    return out


def compute_pandas_ta(def_: IndicatorDef, ohlcv: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Compute a pandas-ta indicator; normalises output columns to stable names."""
    import pandas_ta  # noqa: F401  registers the .ta accessor

    work = ohlcv.loc[:, [c for c in OHLCV_INPUTS if c in ohlcv]].copy()
    if "ts" in ohlcv:
        work.index = pd.to_datetime(ohlcv["ts"].to_numpy(dtype="int64"), unit="ms", utc=True)
    call_params = {
        k: _coerce_value(v, def_.params[k]) for k, v in params.items() if k in def_.params
    }
    res = getattr(work.ta, def_.id)(**call_params)
    frame = _pta_result_frame(res).reset_index(drop=True)
    frame.columns = _dedupe([stable_name(c) for c in frame.columns])
    # Align to the declared outputs (defaults may add/rename edge columns).
    for col in def_.outputs:
        if col not in frame.columns:
            frame[col] = np.nan
    return frame.loc[:, def_.outputs].astype("float64")


# ── Parameter coercion ───────────────────────────────────────────────────────
def _coerce_value(value: float, spec: ParamSpec) -> int | float:
    if spec.kind in ("int", "categorical"):
        return int(round(value))
    return float(value)


def _coerce(def_: IndicatorDef, params: dict) -> dict:
    """Fill missing params with defaults and coerce every value to its spec type."""
    out: dict[str, int | float] = {}
    for name, spec in def_.params.items():
        raw = params.get(name, spec.default)
        out[name] = _coerce_value(raw, spec)
    return out
