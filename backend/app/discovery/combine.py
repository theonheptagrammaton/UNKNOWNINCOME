"""Stage 3 — role-based combination (doc §7 Aşama 3).

Surviving indicators are combined by *role*, never at random: one trigger + one
filter + one exit/risk leg, at most one per category (which the role taxonomy
guarantees — the three roles live in three disjoint category sets). Combos are
formed per symbol × tf cell from the top-K of each role, ranked by their members'
scores, and the global top-N are carried into Optuna. This is the step that turns
millions of blind triples into thousands of sensible ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from app.backtest.config import IndicatorSpec, Rules, RunConfig
from app.discovery.candidates import SingleScan
from app.discovery.config import ScanConfig
from app.discovery.roles import role_for
from app.discovery.signal_synth import filter_confirm, standalone_rules
from app.indicators.registry import get_registry

_LENGTH_PARAM_NAMES = ("atr_length", "timeperiod", "length", "timeperiod1")


@dataclass
class Combo:
    """A trigger + filter + exit triple bound to one symbol × tf cell."""

    trigger: SingleScan
    filter: SingleScan
    exit: SingleScan
    symbol: str
    tf: str
    score: float

    @property
    def key(self) -> str:
        return (
            f"{self.trigger.indicator_id}+{self.filter.indicator_id}"
            f"+{self.exit.indicator_id}@{self.symbol}:{self.tf}"
        )

    @property
    def genome_summary(self) -> dict:
        return {
            "trigger": self.trigger.indicator_id,
            "filter": self.filter.indicator_id,
            "exit": self.exit.indicator_id,
            "symbol": self.symbol,
            "tf": self.tf,
        }


def _exit_atr_length(exit_id: str, fallback: int) -> int:
    """ATR length for the risk exit, taken from the exit indicator when it has one."""
    def_ = get_registry().get(exit_id)
    if def_ is not None:
        for name in _LENGTH_PARAM_NAMES:
            if name in def_.params:
                return int(def_.params[name].default)
    return fallback


def build_combos(
    surviving: list[SingleScan], config: ScanConfig
) -> tuple[list[Combo], int]:
    """Form role-based combos per cell; return (global top-N, total combos tried)."""
    by_cell: dict[tuple[str, str], dict[str, list[SingleScan]]] = {}
    for s in surviving:
        role = role_for(s.category)
        if role is None:
            continue
        cell = by_cell.setdefault((s.symbol, s.tf), {"trigger": [], "filter": [], "exit": []})
        cell[role].append(s)

    pool = max(1, config.combo_pool_per_role)
    combos: list[Combo] = []
    tried = 0
    for (symbol, tf), roles in by_cell.items():
        triggers = _top(roles["trigger"], pool)
        filters = _top(roles["filter"], pool)
        exits = _top(roles["exit"], pool)
        for trig, filt, ex in product(triggers, filters, exits):
            tried += 1
            combos.append(
                Combo(
                    trigger=trig, filter=filt, exit=ex, symbol=symbol, tf=tf,
                    score=(trig.score + filt.score + ex.score) / 3.0,
                )
            )
    combos.sort(key=lambda c: (-c.score, c.key))
    return combos[: config.top_n_combos], tried


def _top(scans: list[SingleScan], k: int) -> list[SingleScan]:
    return sorted(scans, key=lambda s: (-s.score, s.indicator_id))[:k]


def combo_to_run_config(
    combo: Combo,
    config: ScanConfig,
    trigger_params: dict[str, float] | None = None,
    filter_params: dict[str, float] | None = None,
) -> RunConfig:
    """Materialize a combo (optionally with tuned params) into a runnable genome."""
    trig, filt, ex = combo.trigger, combo.filter, combo.exit

    # Operands are rebuilt against the combo's own indicator keys ("trig"/"filt"),
    # not the Stage-1 scan key — same single-vs-multi-output rule as resolve_operands.
    trig_operand = "trig" if len(trig.output_cols) == 1 else f"trig.{trig.output_cols[0]}"
    filt_operand = "filt" if len(filt.output_cols) == 1 else f"filt.{filt.output_cols[0]}"

    trig_rules = standalone_rules(trig.indicator_id, trig.category, trig_operand, config.direction)
    long_conf, short_conf = filter_confirm(filt_operand)
    add_long = long_conf if config.direction != "short" else []
    add_short = short_conf if config.direction != "long" else []
    rules = Rules(
        long_entry=list(trig_rules.long_entry) + add_long,
        long_exit=list(trig_rules.long_exit),
        short_entry=list(trig_rules.short_entry) + add_short,
        short_exit=list(trig_rules.short_exit),
    )

    risk = config.risk_exit.model_copy(
        update={"atr_length": _exit_atr_length(ex.indicator_id, config.risk_exit.atr_length)}
    )
    return RunConfig(
        market=config.market,
        symbol=combo.symbol,
        tf=combo.tf,
        start_ts=config.start_ts,
        end_ts=config.end_ts,
        direction=config.direction,
        indicators=[
            IndicatorSpec(key="trig", id=trig.indicator_id, params=trigger_params or {}),
            IndicatorSpec(key="filt", id=filt.indicator_id, params=filter_params or {}),
        ],
        rules=rules,
        costs=config.costs,
        capital=config.capital,
        risk_exit=risk,
        seed=config.seed,
    )
