"""Genome hashing + immutable versioning + lineage + convert-to-strategy (§8.1–8.2)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.backtest import BacktestRun
from app.models.strategy import StrategyVersion
from app.strategy import service
from app.strategy.genome import diff_genomes, genome_hash

MARKET = "binance_usdm"


def _genome(name="S1", tp=9) -> dict:
    return {
        "name": name,
        "config": {
            "market": MARKET, "symbol": "BTCUSDT", "tf": "1h", "direction": "long",
            "indicators": [{"key": "ema", "id": "ema", "params": {"timeperiod": tp}}],
            "rules": {"long_entry": [{"primitive": "regime", "args": {"x": "ema", "rule": "gt:0"}}],
                      "long_exit": [], "short_entry": [], "short_exit": []},
            "costs": {"funding_enabled": False},
        },
    }


def test_genome_hash_is_deterministic_and_sensitive() -> None:
    assert genome_hash(_genome(tp=9)) == genome_hash(_genome(tp=9))
    assert genome_hash(_genome(tp=9)) != genome_hash(_genome(tp=21))


async def test_create_strategy_makes_version_one(db_session: AsyncSession) -> None:
    strat, v1 = await service.create_strategy(db_session, _genome("Trend"))
    await db_session.commit()
    assert v1.version == 1
    assert v1.status == "candidate"
    assert v1.parent_version_id is None
    assert strat.active_version_id == v1.id
    assert strat.name == "Trend"


async def test_new_version_is_immutable_with_lineage(db_session: AsyncSession) -> None:
    strat, v1 = await service.create_strategy(db_session, _genome("Trend", tp=9))
    await db_session.commit()
    v1_hash = v1.genome_hash

    v2 = await service.add_version(db_session, strat.id, _genome("Trend", tp=21))
    await db_session.commit()

    assert v2.version == 2
    assert v2.parent_version_id == v1.id  # lineage preserved
    assert strat.active_version_id == v2.id  # hot-reload pointer moved
    # v1 is untouched (immutable).
    fresh_v1 = await db_session.get(StrategyVersion, v1.id)
    assert fresh_v1.genome_hash == v1_hash
    assert fresh_v1.version == 1


async def test_convert_from_backtest_run(db_session: AsyncSession) -> None:
    run = BacktestRun(
        id="run-1",
        config={"market": MARKET, "symbol": "ETHUSDT", "tf": "4h",
                "indicators": [], "rules": {}, "costs": {"funding_enabled": False}},
        config_hash="abc", seed=42, status="done", metrics={"num_trades": 5},
    )
    db_session.add(run)
    await db_session.commit()

    strat, v1 = await service.create_from_backtest_run(db_session, "run-1")
    await db_session.commit()
    assert strat.created_from_run_id == "run-1"
    assert v1.source == {"kind": "run", "id": "run-1"}
    assert v1.genome["config"]["symbol"] == "ETHUSDT"


async def test_promote_advances_lifecycle(db_session: AsyncSession) -> None:
    strat, v1 = await service.create_strategy(db_session, _genome("P"))
    await db_session.commit()
    await service.promote(db_session, strat.id)  # candidate → paper
    await db_session.commit()
    refreshed = await db_session.get(StrategyVersion, v1.id)
    assert refreshed.status == "paper"


def test_diff_genomes_reports_changes() -> None:
    changes = diff_genomes(_genome(tp=9), _genome(tp=21))
    key = "config.indicators[0].params.timeperiod"
    assert key in changes
    assert changes[key] == {"from": 9, "to": 21}
