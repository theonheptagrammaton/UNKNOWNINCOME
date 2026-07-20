"""WFO re-opt v1 producer (doc §8.3): tunable space, determinism, proposal + registry."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.strategy.generator import (
    GenerationRequest,
    available_generators,
    get_generator,
)
from app.strategy.genome import genome_config
from app.strategy.reoptimize import (
    ReoptConfig,
    WalkForwardReoptimizer,
    reoptimize_params,
    tunable_param_space,
)
from fakes import make_wave_ohlcv

MARKET, SYMBOL, TF = "binance_usdm", "BTCUSDT", "1h"


def _genome() -> dict:
    return {
        "name": "ReoptSubject",
        "config": {
            "market": MARKET, "symbol": SYMBOL, "tf": TF, "direction": "long",
            "indicators": [{"key": "ema", "id": "ema", "params": {"timeperiod": 9}}],
            "rules": {
                "long_entry": [{"primitive": "regime", "args": {"x": "ema", "rule": "gt:0"}}],
                "long_exit": [], "short_entry": [], "short_exit": [],
            },
            "costs": {"funding_enabled": False},
            "capital": {"initial_cash": 10_000, "size_pct": 1.0, "leverage": 1.0},
            "risk_exit": {"atr_stop_mult": 2.0, "atr_target_mult": 3.0, "atr_length": 14},
        },
    }


@pytest.fixture
def _data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(400, TF, seed=11)))
    return tmp_path


def test_tunable_space_reads_registry(_data) -> None:
    space = tunable_param_space(genome_config(_genome()))
    assert "ema" in space
    assert "timeperiod" in space["ema"]


def test_reoptimization_is_deterministic(_data) -> None:
    config = genome_config(_genome())
    reopt = ReoptConfig(trials=8, seed=42)
    a, score_a = reoptimize_params(config, (None, None), reopt)
    b, score_b = reoptimize_params(config, (None, None), reopt)
    assert a == b  # same seed ⇒ same parameters (rule #6)
    assert score_a == score_b


def test_producer_proposes_validated_genome(_data) -> None:
    gen = WalkForwardReoptimizer(ReoptConfig(trials=8, monte_carlo_runs=50, seed=42))
    request = GenerationRequest(
        strategy_id="s1", genome=_genome(), parent_version_id=None, reason="test", seed=42
    )
    result = gen.propose(request)
    assert result is not None
    # Proposal is a valid, runnable genome (normalizes without error).
    assert genome_config(result.genome).symbol == SYMBOL
    # Report carries the §6.5 evidence.
    assert "monte_carlo" in result.wfo_report
    assert "oos_score" in result.wfo_report
    assert "param_diff" in result.summary
    assert result.regime is not None  # data present ⇒ labelled (doc §8.4)


def test_producer_returns_none_without_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "empty"))
    gen = WalkForwardReoptimizer(ReoptConfig(trials=4, seed=42))
    request = GenerationRequest(
        strategy_id="s1", genome=_genome(), parent_version_id=None, reason="test"
    )
    assert gen.propose(request) is None


def test_generator_registry_seam() -> None:
    # v1 is registered and callable; v2/v3 are defined but empty (doc §8.3).
    assert "wfo_reopt" in available_generators()
    assert get_generator("wfo_reopt").kind == "wfo_reopt"

    req = GenerationRequest(strategy_id="s", genome=_genome(), parent_version_id=None, reason="x")
    for empty in ("genetic", "rl"):
        with pytest.raises(NotImplementedError):
            get_generator(empty).propose(req)
    with pytest.raises(KeyError):
        get_generator("does_not_exist")
