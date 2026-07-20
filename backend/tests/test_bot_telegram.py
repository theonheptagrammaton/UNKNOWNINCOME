"""Telegram control: whitelist, mode switch, two-step kill, audit (doc §10.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot import killswitch as ks
from app.bot.mode import effective_mode, get_global_mode, should_trade
from app.bot.telegram import TelegramBot
from app.core.config import settings
from app.models.base import Base
from app.models.system import AuditLog

CHAT = "555"


async def _factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/tg.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_effective_mode_is_the_lower_switch() -> None:
    assert effective_mode("paper", "live") == "paper"  # global caps strategy
    assert effective_mode("live", "off") == "off"
    assert effective_mode("live", "paper") == "paper"
    assert should_trade("paper") and not should_trade("off")


async def test_non_whitelisted_chat_is_rejected(_env) -> None:
    factory = await _factory(_env)
    bot = TelegramBot(factory, chat_id=CHAT)
    resp = await bot.handle("/kill", "999")  # wrong chat id
    assert resp.accepted is False
    async with factory() as s:
        actions = [a.action for a in (await s.execute(select(AuditLog))).scalars().all()]
        assert "telegram.unauthorized" in actions


async def test_mode_switch_from_telegram(_env) -> None:
    factory = await _factory(_env)
    bot = TelegramBot(factory, chat_id=CHAT)
    resp = await bot.handle("/mode paper", CHAT)
    assert resp.accepted and "PAPER" in resp.text
    async with factory() as s:
        assert await get_global_mode(s) == "paper"
    await bot.handle("/mode off", CHAT)
    async with factory() as s:
        assert await get_global_mode(s) == "off"


async def test_mode_live_is_disabled_until_phase_7(_env) -> None:
    factory = await _factory(_env)
    bot = TelegramBot(factory, chat_id=CHAT)
    resp = await bot.handle("/mode live", CHAT)
    assert "disabled" in resp.text.lower()
    async with factory() as s:
        assert await get_global_mode(s) == "off"  # unchanged


async def test_kill_requires_two_step_confirmation(_env) -> None:
    factory = await _factory(_env)
    bot = TelegramBot(factory, chat_id=CHAT)
    first = await bot.handle("/kill", CHAT)
    assert "confirm" in first.text.lower()
    async with factory() as s:
        assert not await ks.is_engaged_db(s)  # not engaged yet

    second = await bot.handle("/kill confirm", CHAT)
    assert "engaged" in second.text.lower()
    async with factory() as s:
        assert await ks.is_engaged_db(s)


async def test_all_commands_are_audited(_env) -> None:
    factory = await _factory(_env)
    bot = TelegramBot(factory, chat_id=CHAT)
    for cmd in ("/status", "/pnl", "/positions"):
        await bot.handle(cmd, CHAT)
    async with factory() as s:
        actions = [a.action for a in (await s.execute(select(AuditLog))).scalars().all()]
        assert actions.count("telegram.command") == 3
