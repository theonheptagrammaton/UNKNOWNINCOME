"""Slippage reconciliation (doc §26.1): rebuild from live fills only, and when reality
is worse than the assumption emit an event + trigger the re-run seam (the painful part)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.execution.slippage_reconcile import rebuild_slippage_model, reconcile_slippage
from app.models.risk import RiskEvent
from app.models.trading import SlippageObservation


def _obs(mode: str, bps: float, n: int) -> list[SlippageObservation]:
    expected = 100.0
    fill = expected * (1 + bps / 1e4)  # buy filled `bps` above expected → adverse
    return [
        SlippageObservation(
            ts=1_700_000_000_000 + i, mode=mode, symbol="BTCUSDT", tf="1h", side="buy",
            expected_price=expected, fill_price=fill, order_notional=5_000.0, atr=0.8,
            slippage_bps=bps, strategy_version_id="v1",
        )
        for i in range(n)
    ]


class _Notifier:
    def __init__(self) -> None:
        self.msgs: list[str] = []

    async def notify(self, msg: str) -> None:
        self.msgs.append(msg)


async def _seed(factory: async_sessionmaker[AsyncSession], rows: list) -> None:
    async with factory() as s:
        s.add_all(rows)
        await s.commit()


async def test_rebuild_counts_live_fills_only(
    db_session_factory, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    await _seed(db_session_factory, _obs("live", 30.0, 50) + _obs("paper", 30.0, 60))
    async with db_session_factory() as s:
        model = await rebuild_slippage_model(s, min_samples=50)
    assert model.trusted_buckets == 1
    assert next(iter(model.buckets.values())).samples == 50  # only the live fills
    assert (Path(tmp_path) / "slippage_model.json").exists()  # sync-readable artifact


async def test_reconcile_flags_and_reruns_when_worse(
    db_session_factory, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    await _seed(db_session_factory, _obs("live", 30.0, 50))  # learned 30 bps ≫ assumed 5

    reran: list[tuple[str, str]] = []

    async def _rerun(symbol: str, tf: str) -> None:
        reran.append((symbol, tf))

    notifier = _Notifier()
    async with db_session_factory() as s:
        report = await reconcile_slippage(
            s, assumed_bps=5.0, min_samples=50, rerun=_rerun, notifier=notifier
        )
        await s.commit()

    assert report.rerun_needed
    assert report.worse_buckets and report.worse_buckets[0][1] == pytest.approx(30.0)
    assert reran == [("BTCUSDT", "1h")]
    assert notifier.msgs
    async with db_session_factory() as s:
        events = (await s.execute(
            select(RiskEvent).where(RiskEvent.type == "slippage_worse")
        )).scalars().all()
    assert len(events) == 1
    assert events[0].detail["learned_bps"] == pytest.approx(30.0)


async def test_reconcile_noop_when_learned_better_than_assumed(
    db_session_factory, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    await _seed(db_session_factory, _obs("live", 2.0, 50))  # learned 2 bps < assumed 5

    async with db_session_factory() as s:
        report = await reconcile_slippage(s, assumed_bps=5.0, min_samples=50)
        await s.commit()
    assert not report.rerun_needed
    async with db_session_factory() as s:
        events = (await s.execute(
            select(RiskEvent).where(RiskEvent.type == "slippage_worse")
        )).scalars().all()
    assert events == []
