"""Kill switch stops the bot in < 2 s from all four channels (doc §9.4 acceptance)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot import killswitch as ks
from app.bot.engine import BotEngine
from app.bot.killswitch import KillSwitch, killswitch_path
from app.bot.mode import set_global_mode
from app.bot.telegram import TelegramBot
from app.core.config import settings
from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.models.base import Base
from app.models.risk import RiskEvent
from app.models.trading import Order
from app.strategy import service
from fakes import make_wave_ohlcv

MARKET, SYMBOL, TF = "binance_usdm", "BTCUSDT", "1h"
CLOCK_MS = 1_700_000_000_000


def _genome() -> dict:
    return {
        "name": "AlwaysLong",
        "config": {
            "market": MARKET, "symbol": SYMBOL, "tf": TF, "direction": "long",
            "indicators": [{"key": "ema", "id": "ema", "params": {"timeperiod": 9}}],
            "rules": {"long_entry": [{"primitive": "regime", "args": {"x": "ema", "rule": "gt:0"}}],
                      "long_exit": [], "short_entry": [], "short_exit": []},
            "costs": {"funding_enabled": False},
            "capital": {"initial_cash": 10_000, "size_pct": 1.0, "leverage": 1.0},
        },
    }


async def _factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/ks.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "parquet"))
    (tmp_path / "parquet").mkdir(parents=True, exist_ok=True)
    write_ohlcv(MARKET, SYMBOL, TF, ohlcv_rows_to_frame(make_wave_ohlcv(200, TF, seed=7)))
    return tmp_path


async def _seed(factory):
    async with factory() as s:
        strat, _ = await service.create_strategy(s, _genome())
        await service.set_mode(s, strat.id, "paper")
        await set_global_mode(s, "paper")
        await s.commit()


# ── the four channels, each producing the shared file flag ────────────────────
async def _engage_file(factory) -> None:
    KillSwitch().engage_file("direct file flag")  # channel 3: KILLSWITCH file


async def _engage_api(factory) -> None:  # channel 2: POST /api/bot/killswitch
    async with factory() as s:
        await ks.engage(s, actor="api")
        await s.commit()


async def _engage_ui(factory) -> None:  # channel 1: UI button (→ same engage path)
    async with factory() as s:
        await ks.engage(s, actor="ui")
        await s.commit()


async def _engage_telegram(factory) -> None:  # channel 4: Telegram /kill
    bot = TelegramBot(factory, chat_id="123")
    await bot.handle("/kill", "123")
    await bot.handle("/kill confirm", "123")


@pytest.mark.parametrize(
    "engage", [_engage_file, _engage_api, _engage_ui, _engage_telegram]
)
async def test_each_channel_halts_the_bot(_env, engage) -> None:
    factory = await _factory(_env)
    await _seed(factory)
    engine = BotEngine(factory, clock=lambda: CLOCK_MS)  # default KillSwitch → shared file

    await engage(factory)
    assert killswitch_path().exists()  # every channel raises the shared file flag

    report = await engine.tick()
    assert report.killed is True
    async with factory() as s:
        assert (await s.execute(select(Order))).scalars().first() is None  # no orders
        events = (await s.execute(select(RiskEvent))).scalars().all()
        assert any(e.type == "killswitch" for e in events)


async def test_kill_response_is_under_two_seconds(_env) -> None:
    """The loop polls the switch every ``kill_poll`` (<2 s), so it halts within it."""
    factory = await _factory(_env)
    await _seed(factory)
    assert settings.bot_killswitch_poll_seconds < 2.0

    engine = BotEngine(
        factory, clock=lambda: CLOCK_MS, tick_seconds=0.0, kill_poll_seconds=0.5
    )
    assert engine._kill_poll < 2.0

    elapsed = {"t": 0.0}

    async def _sleep(seconds: float) -> None:
        elapsed["t"] += seconds

    # Engage before the loop; the very first poll must halt trading (no orders ever).
    await _engage_api(factory)
    await engine.run(stop=lambda: elapsed["t"] >= 2.0, sleep=_sleep, max_ticks=100)
    async with factory() as s:
        assert (await s.execute(select(Order))).scalars().first() is None
