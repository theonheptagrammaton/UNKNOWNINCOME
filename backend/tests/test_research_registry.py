"""The experiment ledger — canonical family hash + append-only accumulation (§23.2)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.research import registry


def _entry(trigger="rsi", filter="obv", exit="atr", symbol="BTCUSDT", tf="1h", direction="both"):
    return {
        "combo": {"trigger": trigger, "filter": filter, "exit": exit, "symbol": symbol, "tf": tf},
        "genome": {"direction": direction},
        "symbol": symbol,
        "tf": tf,
        "is_score": 1.2,
        "oos_score": 0.8,
        "oos_net_return": 0.05,
        "oos_trades": 41,
        "status": "candidate",
        "metrics": {"sharpe": 1.1},
    }


def test_family_hash_is_param_independent_and_stable() -> None:
    """Same structure ⇒ same hash regardless of tuned params; different leg ⇒ different."""
    a = registry.family_hash_for_entry(_entry())
    b = registry.family_hash_for_entry(_entry())
    assert a == b and len(a) == 16
    # A different exit indicator is a different family.
    assert registry.family_hash_for_entry(_entry(exit="natr")) != a
    # A different symbol/tf/direction is a different family (§23.2).
    assert registry.family_hash_for_entry(_entry(symbol="ETHUSDT")) != a
    assert registry.family_hash_for_entry(_entry(tf="4h")) != a
    assert registry.family_hash_for_entry(_entry(direction="long")) != a


def test_build_trial_rows_is_pure_and_carries_raw_metrics() -> None:
    rows = registry.build_trial_rows("scan-1", [_entry()], {"start_ts": 1, "end_ts": 2})
    assert len(rows) == 1
    row = rows[0]
    assert row["scan_id"] == "scan-1"
    assert row["genome_hash"] == registry.family_hash_for_entry(_entry())
    assert row["oos_metrics"]["oos_trades"] == 41
    assert row["period"] == {"start_ts": 1, "end_ts": 2}


@pytest.mark.asyncio
async def test_reopt_grows_family_count(db_session: AsyncSession) -> None:
    """Re-optimizing the same strategy across scans accumulates its all-time count (§23.2)."""
    entry = _entry()
    family = registry.family_hash_for_entry(entry)

    for scan in range(50):  # 50 re-optimizations of the *same* strategy
        rows = registry.build_trial_rows(f"scan-{scan}", [entry], {"start_ts": 0, "end_ts": 1})
        await registry.record_trials(db_session, rows)
    await db_session.commit()

    counts = await registry.family_counts(db_session, [family])
    assert counts[family] == 50
    # The whole-ledger read the service uses agrees.
    assert (await registry.all_family_counts(db_session))[family] == 50


@pytest.mark.asyncio
async def test_distinct_families_counted_separately(db_session: AsyncSession) -> None:
    a, b = _entry(), _entry(exit="natr")
    rows = registry.build_trial_rows("s", [a, b, a], {"start_ts": 0, "end_ts": 1})
    await registry.record_trials(db_session, rows)
    await db_session.commit()
    counts = await registry.all_family_counts(db_session)
    assert counts[registry.family_hash_for_entry(a)] == 2
    assert counts[registry.family_hash_for_entry(b)] == 1
