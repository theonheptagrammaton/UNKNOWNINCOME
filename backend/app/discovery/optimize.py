"""Stage 4 — parameter optimization (doc §7 Aşama 4).

Each top-N combo's trigger + filter parameters are searched with Optuna's TPE
sampler over the registry's per-parameter bounds (:class:`ParamSpec`). The sampler
is seeded and runs single-threaded so the same scan seed reproduces the same
trials — a hard acceptance criterion (aynı seed → aynı sıralama). The objective is
the §6.4 composite score on the in-sample window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.backtest.runner import NoDataError
from app.discovery.combine import Combo, combo_to_run_config
from app.discovery.config import ScanConfig
from app.discovery.evaluate import run_eval
from app.indicators.registry import ParamSpec, get_registry

logger = logging.getLogger(__name__)

_FAIL_SCORE = -1e9


@dataclass
class OptimizeResult:
    trigger_params: dict[str, float] = field(default_factory=dict)
    filter_params: dict[str, float] = field(default_factory=dict)
    best_score: float = 0.0


def _suggest(trial, prefix: str, params: dict[str, ParamSpec]) -> dict[str, float]:
    """Suggest one value per tunable parameter, namespaced by ``prefix``."""
    out: dict[str, float] = {}
    for name, spec in params.items():
        tname = f"{prefix}__{name}"
        if spec.kind == "categorical" and spec.choices:
            out[name] = trial.suggest_categorical(tname, spec.choices)
        elif spec.min is None or spec.max is None:
            out[name] = spec.default  # unbounded ⇒ pin to default
        elif spec.kind == "int":
            step = int(spec.step or 1)
            out[name] = trial.suggest_int(tname, int(spec.min), int(spec.max), step=max(1, step))
        else:  # float
            step = spec.step if spec.step else None
            out[name] = trial.suggest_float(tname, float(spec.min), float(spec.max), step=step)
    return out


def _tunable(indicator_id: str) -> dict[str, ParamSpec]:
    def_ = get_registry().get(indicator_id)
    return dict(def_.params) if def_ is not None else {}


def optimize_combo(combo: Combo, config: ScanConfig) -> OptimizeResult:
    """Search a combo's parameters; returns the best trigger/filter params + score."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    trig_params = _tunable(combo.trigger.indicator_id)
    filt_params = _tunable(combo.filter.indicator_id)

    # No tunable parameters ⇒ a single deterministic evaluation at defaults.
    if (not trig_params and not filt_params) or config.optuna_trials <= 0:
        score = _score(combo, config, {}, {})
        return OptimizeResult(best_score=score)

    def objective(trial: optuna.Trial) -> float:
        t = _suggest(trial, "trig", trig_params)
        f = _suggest(trial, "filt", filt_params)
        return _score(combo, config, t, f)

    sampler = optuna.samplers.TPESampler(seed=config.seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=config.optuna_trials, n_jobs=1)

    best = study.best_params
    return OptimizeResult(
        trigger_params={k[len("trig__"):]: v for k, v in best.items() if k.startswith("trig__")},
        filter_params={k[len("filt__"):]: v for k, v in best.items() if k.startswith("filt__")},
        best_score=float(study.best_value),
    )


def _score(
    combo: Combo, config: ScanConfig, trig: dict[str, float], filt: dict[str, float]
) -> float:
    """Composite score for one parameterization; failures score −∞ (pruned)."""
    rc = combo_to_run_config(combo, config, trig, filt)
    try:
        ev = run_eval(rc)
    except NoDataError:
        return _FAIL_SCORE
    except Exception as exc:  # a bad param combo must not sink the study
        logger.debug("optuna eval failed for %s: %s", combo.key, exc)
        return _FAIL_SCORE
    return float(ev.metrics.get("composite_score") or 0.0)
