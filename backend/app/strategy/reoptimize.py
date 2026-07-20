"""WFO re-optimization — the v1 producer (doc §8.3, §15/Faz 6).

"Refresh the parameters of an existing genome on new data, then re-run the §6.5
defense line." This is the low-complexity / high-explainability mechanism §8.3
mandates as the compulsory base: the *rules stay the same*, only the parameters
move, and every proposal is validated (OOS walk-forward + parameter plateau +
Monte-Carlo) before it is allowed anywhere near approval.

It deliberately reuses the Phase-4 discovery primitives so a re-optimization score
is identical to a discovery/backtest score:

* :func:`app.discovery.evaluate.run_eval` — the lean single-config evaluation.
* :func:`app.discovery.wfo.rolling_windows` / :func:`app.discovery.wfo.monte_carlo`
  / :func:`app.discovery.wfo._neighbor_values` — the walk-forward machinery.
* :func:`app.indicators.registry.get_registry` — the per-parameter search bounds.

The whole module is pure, synchronous CPU work (no DB, no I/O beyond the Parquet
reads ``run_eval`` does), so it is deterministic — the same ``seed`` reproduces the
same parameters — and unit-testable against a Parquet fixture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from app.backtest.config import RunConfig
from app.backtest.runner import NoDataError
from app.core.config import settings
from app.data.duckdb_query import query_ohlcv
from app.discovery.evaluate import MIN_BARS, run_eval
from app.discovery.wfo import Window, _neighbor_values, monte_carlo, rolling_windows
from app.indicators.registry import ParamSpec, get_registry
from app.strategy.generator import (
    GenerationRequest,
    GenerationResult,
    register_generator,
)
from app.strategy.genome import diff_genomes, genome_config, normalize_genome
from app.strategy.regime import classify_regime

logger = logging.getLogger(__name__)

_FAIL_SCORE = -1e9


@dataclass
class ReoptConfig:
    """Knobs for a single re-optimization (defaults come from ``settings``)."""

    trials: int = 30
    train_days: int = 90
    test_days: int = 30
    step_days: int = 30
    monte_carlo_runs: int = 300
    plateau_ratio: float = 0.5
    plateau_steps: int = 1
    seed: int = 42

    @classmethod
    def from_settings(cls, *, seed: int = 42, trials: int | None = None) -> ReoptConfig:
        return cls(
            trials=trials if trials is not None else settings.reopt_trials,
            train_days=settings.reopt_train_days,
            test_days=settings.reopt_test_days,
            step_days=settings.reopt_step_days,
            monte_carlo_runs=settings.reopt_monte_carlo_runs,
            plateau_ratio=settings.reopt_plateau_ratio,
            plateau_steps=settings.reopt_plateau_steps,
            seed=seed,
        )


# ── parameter space ───────────────────────────────────────────────────────────
def tunable_param_space(config: RunConfig) -> dict[str, dict[str, ParamSpec]]:
    """The tunable parameters of a genome, keyed by indicator ``key`` (§7 Aşama 4).

    Uses the same registry bounds discovery sweeps, so re-optimization searches the
    identical space a fresh scan would — the rules are fixed, only these move.
    """
    registry = get_registry()
    space: dict[str, dict[str, ParamSpec]] = {}
    for spec in config.indicators:
        def_ = registry.get(spec.id)
        if def_ is None or not def_.params:
            continue
        space[spec.key] = dict(def_.params)
    return space


def _with_params(config: RunConfig, params_by_key: dict[str, dict[str, float]]) -> RunConfig:
    """A copy of ``config`` with the given indicator params overwritten (merge)."""
    new = config.model_copy(deep=True)
    for spec in new.indicators:
        overrides = params_by_key.get(spec.key)
        if overrides:
            spec.params = {**spec.params, **overrides}
    return new


def _windowed(config: RunConfig, start: int | None, end: int | None) -> RunConfig:
    return config.model_copy(update={"start_ts": start, "end_ts": end})


def evaluate_score(config: RunConfig, start: int | None = None, end: int | None = None) -> float:
    """Composite §6.4 score of a config on a window; failures score −∞ (pruned)."""
    try:
        ev = run_eval(_windowed(config, start, end))
    except NoDataError:
        return _FAIL_SCORE
    except Exception as exc:  # a bad param combo must not sink the study
        logger.debug("reopt eval failed: %s", exc)
        return _FAIL_SCORE
    return float(ev.metrics.get("composite_score") or 0.0)


# ── optimization ──────────────────────────────────────────────────────────────
def _suggest(trial, key: str, params: dict[str, ParamSpec]) -> dict[str, float]:
    """Suggest one value per tunable parameter, namespaced by indicator ``key``."""
    out: dict[str, float] = {}
    for name, spec in params.items():
        tname = f"{key}__{name}"
        if spec.kind == "categorical" and spec.choices:
            out[name] = trial.suggest_categorical(tname, spec.choices)
        elif spec.min is None or spec.max is None:
            out[name] = spec.default  # unbounded ⇒ pin to default
        elif spec.kind == "int":
            step = int(spec.step or 1)
            out[name] = trial.suggest_int(tname, int(spec.min), int(spec.max), step=max(1, step))
        else:
            step = spec.step if spec.step else None
            out[name] = trial.suggest_float(tname, float(spec.min), float(spec.max), step=step)
    return out


def reoptimize_params(
    config: RunConfig, window: tuple[int | None, int | None], reopt: ReoptConfig
) -> tuple[dict[str, dict[str, float]], float]:
    """Search the genome's parameters on ``window``; return (params_by_key, score).

    Seeded TPE, single-threaded — mirrors :func:`app.discovery.optimize.optimize_combo`
    exactly, so the same seed reproduces the same parameters (rule #6).
    """
    space = tunable_param_space(config)
    start, end = window

    # No tunable parameters (or no budget) ⇒ a single deterministic evaluation.
    if not space or reopt.trials <= 0:
        return {}, evaluate_score(config, start, end)

    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        params = {key: _suggest(trial, key, specs) for key, specs in space.items()}
        return evaluate_score(_with_params(config, params), start, end)

    sampler = optuna.samplers.TPESampler(seed=reopt.seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=reopt.trials, n_jobs=1)

    best_by_key: dict[str, dict[str, float]] = {key: {} for key in space}
    for tname, value in study.best_params.items():
        key, name = tname.split("__", 1)
        best_by_key.setdefault(key, {})[name] = value
    return {k: v for k, v in best_by_key.items() if v}, float(study.best_value)


# ── walk-forward validation (§6.5) at the genome level ────────────────────────
@dataclass
class GenomeWFOReport:
    oos_score: float
    layers: list[dict]
    plateau_ok: bool
    plateau_scores: list[float]
    monte_carlo: dict
    full_metrics: dict = field(default_factory=dict)
    survived: bool = False

    def as_dict(self) -> dict:
        return {
            "producer": "wfo_reopt",
            "oos_score": self.oos_score,
            "layers": self.layers,
            "plateau_ok": self.plateau_ok,
            "plateau_scores": self.plateau_scores,
            "monte_carlo": self.monte_carlo,
            "metrics": self.full_metrics,
            "survived": self.survived,
        }


def _plateau(config: RunConfig, full_span: tuple[int, int], best_score: float, reopt: ReoptConfig):
    """Perturb each tuned param ±step; neighbours must score ≥ ratio × best (§6.5.3)."""
    space = tunable_param_space(config)
    values = {spec.key: dict(spec.params) for spec in config.indicators}
    floor = reopt.plateau_ratio * best_score
    scores: list[float] = []
    ok = True
    for key, specs in space.items():
        for name, spec in specs.items():
            value = float(values.get(key, {}).get(name, spec.default))
            for nv in _neighbor_values(spec, value, reopt.plateau_steps):
                trial = _with_params(config, {key: {name: nv}})
                s = evaluate_score(trial, full_span[0], full_span[1])
                scores.append(s)
                if s < floor:
                    ok = False
    return ok, scores


def walk_forward_genome(
    config: RunConfig, full_span: tuple[int, int], reopt: ReoptConfig
) -> GenomeWFOReport:
    """Full §6.5 validation of an already-tuned genome over ``full_span``."""
    ts0, ts1 = full_span
    windows = rolling_windows(ts0, ts1, reopt.train_days, reopt.test_days, reopt.step_days)
    if not windows:
        # Data span < train+test ⇒ fall back to a single 70/30 IS/OOS split (§6.5.1).
        split = ts0 + int(0.7 * (ts1 - ts0))
        windows = [Window(ts0, split, split, ts1)]

    layers: list[dict] = []
    for w in windows:
        try:
            ev = run_eval(_windowed(config, w.test_start, w.test_end))
            score = float(ev.metrics.get("composite_score") or 0.0)
            metrics = ev.metrics
        except Exception as exc:  # resilience per layer (incl. NoDataError)
            logger.debug("reopt wfo layer failed: %s", exc)
            score, metrics = 0.0, {}
        layers.append({
            "test_start": w.test_start, "test_end": w.test_end,
            "composite_score": score, "net_return": metrics.get("net_return"),
            "num_trades": metrics.get("num_trades", 0),
        })

    oos_scores = [x["composite_score"] for x in layers]
    oos_score = float(np.mean(oos_scores)) if oos_scores else 0.0

    try:
        full = run_eval(_windowed(config, ts0, ts1))
        full_score = float(full.metrics.get("composite_score") or 0.0)
        full_metrics = full.metrics
        trade_rets = np.array([t.return_pct for t in full.result.trades], dtype="float64")
    except Exception as exc:
        logger.debug("reopt wfo full eval failed: %s", exc)
        full_score, full_metrics, trade_rets = 0.0, {}, np.zeros(0)

    plateau_ok, plateau_scores = _plateau(config, full_span, full_score, reopt)
    mc = monte_carlo(trade_rets, reopt.monte_carlo_runs, reopt.seed)
    survived = (
        oos_score > 0.0
        and plateau_ok
        and bool(full_metrics.get("passes_hard_filters", False))
    )
    return GenomeWFOReport(
        oos_score=oos_score, layers=layers, plateau_ok=plateau_ok,
        plateau_scores=plateau_scores, monte_carlo=mc, full_metrics=full_metrics,
        survived=survived,
    )


# ── the v1 producer ───────────────────────────────────────────────────────────
class WalkForwardReoptimizer:
    """v1 producer (doc §8.3): refresh parameters on new data, then validate (§6.5)."""

    kind = "wfo_reopt"

    def __init__(self, reopt: ReoptConfig | None = None) -> None:
        self._reopt = reopt

    def propose(self, request: GenerationRequest) -> GenerationResult | None:
        reopt = self._reopt or ReoptConfig.from_settings(
            seed=request.seed, trials=request.trials
        )
        try:
            config = genome_config(request.genome)
        except Exception as exc:
            logger.warning("reopt: bad genome for %s: %s", request.strategy_id, exc)
            return None

        ohlcv = query_ohlcv(config.market, config.symbol, config.tf).reset_index(drop=True)
        if len(ohlcv) < MIN_BARS:
            logger.info("reopt: insufficient data for %s/%s", config.symbol, config.tf)
            return None
        ts0, ts1 = int(ohlcv["ts"].iloc[0]), int(ohlcv["ts"].iloc[-1])
        train = request.train_window or (ts0, ts1)

        old_score = evaluate_score(config, ts0, ts1)
        best_params, opt_score = reoptimize_params(config, train, reopt)
        new_config = _with_params(config, best_params)
        report = walk_forward_genome(new_config, (ts0, ts1), reopt)

        new_genome = normalize_genome({
            "name": request.genome.get("name") or config.symbol,
            "config": new_config.model_dump(mode="json"),
        })
        regime = classify_regime(
            ohlcv,
            adx_period=settings.regime_adx_period,
            adx_trend_threshold=settings.regime_adx_trend_threshold,
            atr_period=settings.regime_atr_period,
            atr_high_pct=settings.regime_atr_high_pct,
        )
        summary = {
            "reason": request.reason,
            "params": best_params,
            "param_diff": diff_genomes(request.genome, new_genome),
            "old_score": old_score,
            "optimized_score": opt_score,
            "oos_score": report.oos_score,
            "train_window": list(train),
            "full_window": [ts0, ts1],
        }
        return GenerationResult(
            genome=new_genome,
            wfo_report=report.as_dict(),
            summary=summary,
            survived=report.survived,
            regime=regime.label if regime else None,
        )


# Register the v1 producer so the seam is live (doc §8.3).
register_generator(WalkForwardReoptimizer())
