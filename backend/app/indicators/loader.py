"""Custom indicator plugin loader (doc §5.1).

Any ``.py`` file dropped into ``indicators/custom/`` that exposes an ``INDICATOR``
metadata dict and a ``compute(df, **params)`` callable is auto-registered. This
is the "extensible reality" escape hatch — new sources without touching core.

Plugin contract::

    INDICATOR = {
        "id": "zscore",
        "name": "Rolling Z-Score",
        "category": "statistic",
        "inputs": ["close"],
        "params": {"length": {"default": 20, "min": 5, "max": 200, "step": 1}},
        "outputs": ["zscore"],
        "signal_templates": ["threshold_cross", "slope"],
    }

    def compute(df: pd.DataFrame, length: int = 20) -> pd.DataFrame | pd.Series: ...
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from types import ModuleType

import pandas as pd

from app.indicators import custom as custom_pkg
from app.indicators.registry import IndicatorDef, ParamSpec

logger = logging.getLogger(__name__)

# Cache of loaded plugin modules, keyed by indicator id.
_PLUGINS: dict[str, ModuleType] = {}


def _iter_plugin_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    for info in pkgutil.iter_modules(custom_pkg.__path__):
        if info.name.startswith("_"):
            continue
        try:
            modules.append(importlib.import_module(f"{custom_pkg.__name__}.{info.name}"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("custom indicator %r failed to import: %s", info.name, exc)
    return modules


def _def_from_module(module: ModuleType) -> IndicatorDef | None:
    meta = getattr(module, "INDICATOR", None)
    compute = getattr(module, "compute", None)
    if meta is None or not callable(compute):
        return None
    params = {
        name: (spec if isinstance(spec, ParamSpec) else ParamSpec(**spec))
        for name, spec in meta.get("params", {}).items()
    }
    return IndicatorDef(
        id=meta["id"],
        name=meta.get("name", meta["id"]),
        category=meta.get("category", "statistic"),
        source="custom",
        inputs=meta.get("inputs", ["close"]),
        params=params,
        outputs=meta.get("outputs", [meta["id"]]),
        signal_templates=meta.get("signal_templates", ["threshold_cross", "slope"]),
    )


def load_custom_defs() -> list[IndicatorDef]:
    """Scan ``custom/`` and return the registry defs for valid plugins."""
    _PLUGINS.clear()
    defs: list[IndicatorDef] = []
    for module in _iter_plugin_modules():
        d = _def_from_module(module)
        if d is None:
            logger.warning("custom module %r missing INDICATOR/compute, skipped", module.__name__)
            continue
        _PLUGINS[d.id] = module
        defs.append(d)
    return defs


def compute_custom(def_: IndicatorDef, ohlcv: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Dispatch to a loaded custom plugin's ``compute``."""
    module = _PLUGINS.get(def_.id)
    if module is None:  # registry built without custom, or hot-added — reload.
        load_custom_defs()
        module = _PLUGINS.get(def_.id)
    if module is None:
        raise KeyError(f"custom indicator {def_.id!r} not loaded")
    call = {name: params.get(name, spec.default) for name, spec in def_.params.items()}
    result = module.compute(ohlcv, **call)
    frame = result.to_frame() if isinstance(result, pd.Series) else result
    frame = frame.reset_index(drop=True)
    if list(frame.columns) != def_.outputs and len(frame.columns) == len(def_.outputs):
        frame.columns = def_.outputs
    return frame.astype("float64")
