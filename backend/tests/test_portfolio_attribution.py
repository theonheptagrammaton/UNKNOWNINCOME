"""Engine wiring: netleştirilmiş pozisyon kapanınca PnL orantılı atfedilir (§24.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.engine import BotEngine
from app.bot.killswitch import KillSwitch
from app.models.base import Base
from app.models.trading import Trade

pytestmark = pytest.mark.asyncio


async def _factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/bot.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_shared_symbol_close_writes_proportional_attribution(tmp_path) -> None:
    factory = await _factory(tmp_path)
    engine = BotEngine(factory, killswitch=KillSwitch(tmp_path / "KILLSWITCH"))
    async with factory() as s:
        # Two strategies hold one netted BTCUSDT long: A 1000 notional, B 3000.
        a = Trade(mode="paper", strategy_id="A", symbol="BTCUSDT", side="long",
                  qty=10, entry_price=100.0, entry_ts=1, status="closed", pnl=400.0)
        b = Trade(mode="paper", strategy_id="B", symbol="BTCUSDT", side="long",
                  qty=30, entry_price=100.0, entry_ts=1, status="open")
        s.add_all([a, b])
        await s.flush()
        await engine._attribute_shared(s, a, "BTCUSDT", "paper")
        assert a.attribution == {"A": pytest.approx(100.0), "B": pytest.approx(300.0)}


async def test_single_strategy_symbol_has_no_attribution(tmp_path) -> None:
    """Tek strateji sembolü ⇒ attribution None (kendi satırı zaten tüm PnL'i taşır)."""
    factory = await _factory(tmp_path)
    engine = BotEngine(factory, killswitch=KillSwitch(tmp_path / "KILLSWITCH"))
    async with factory() as s:
        solo = Trade(mode="paper", strategy_id="solo", symbol="ETHUSDT", side="long",
                     qty=5, entry_price=100.0, entry_ts=1, status="closed", pnl=50.0)
        s.add(solo)
        await s.flush()
        await engine._attribute_shared(s, solo, "ETHUSDT", "paper")
        assert solo.attribution is None
