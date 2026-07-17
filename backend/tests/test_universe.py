"""Tests for the dynamic universe builder."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.data.adapters.base import MarketInfo
from app.data.universe import (
    UniverseCandidate,
    build_universe,
    is_leveraged_token,
    is_stablecoin,
    select_universe,
)
from app.models.market import Symbol, UniverseSnapshot
from fakes import FakeAdapter, make_ohlcv


def test_stable_and_leveraged_detection() -> None:
    assert is_stablecoin("USDC")
    assert not is_stablecoin("BTC")
    assert is_leveraged_token("BTC3L")
    assert is_leveraged_token("ETHBULL")
    assert not is_leveraged_token("JUP")  # UP-suffix false positive guarded


def _cand(symbol: str, base: str, median_vol: float, spread: float) -> UniverseCandidate:
    return UniverseCandidate(
        symbol=symbol,
        ccxt_symbol=f"{base}/USDT:USDT",
        base=base,
        quote="USDT",
        quote_volume_24h=1e9,
        median_volume_usd=median_vol,
        spread_bps=spread,
    )


def test_select_universe_filters_and_ranks() -> None:
    candidates = [
        _cand("BTCUSDT", "BTC", 5e8, 1.0),
        _cand("ETHUSDT", "ETH", 3e8, 1.0),
        _cand("USDCUSDT", "USDC", 9e9, 0.5),  # stablecoin → excluded
        _cand("BTC3LUSDT", "BTC3L", 1e8, 1.0),  # leveraged → excluded
        _cand("LOWUSDT", "LOW", 1e3, 1.0),  # below min volume → excluded
        _cand("WIDUSDT", "WID", 2e8, 50.0),  # spread too wide → excluded
    ]
    selected = select_universe(candidates, size=30, min_median_volume_usd=1e6, max_spread_bps=5.0)
    assert [c.symbol for c in selected] == ["BTCUSDT", "ETHUSDT"]


async def test_build_universe_persists_dated_snapshot(
    db_session: AsyncSession, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "universe_min_median_volume_usd", 0.0)
    markets = [
        MarketInfo("BTC/USDT:USDT", "BTCUSDT", "BTC", "USDT", True),
        MarketInfo("ETH/USDT:USDT", "ETHUSDT", "ETH", "USDT", True),
        MarketInfo("USDC/USDT:USDT", "USDCUSDT", "USDC", "USDT", True),
    ]
    tickers = {
        "BTC/USDT:USDT": {"quoteVolume": 1e9, "bid": 100, "ask": 100.01},
        "ETH/USDT:USDT": {"quoteVolume": 5e8, "bid": 50, "ask": 50.005},
        "USDC/USDT:USDT": {"quoteVolume": 2e9, "bid": 1, "ask": 1.0001},
    }
    series = {(m.ccxt_symbol, "1d"): make_ohlcv(0, 30, "1d") for m in markets}
    adapter = FakeAdapter(series=series, markets=markets, tickers=tickers)

    snapshot = await build_universe(adapter, db_session, size=30)

    assert set(snapshot.symbols) == {"BTCUSDT", "ETHUSDT"}  # stablecoin excluded
    stored = (await db_session.execute(select(UniverseSnapshot))).scalars().all()
    assert len(stored) == 1
    assert stored[0].as_of_date is not None
    symbols = (await db_session.execute(select(Symbol))).scalars().all()
    assert {s.symbol for s in symbols} == {"BTCUSDT", "ETHUSDT"}
