"""Survivorship-bias guard (doc §4.5): a dated scan uses that day's universe."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.data.universe import (
    UniverseCandidate,
    latest_universe_symbols,
    persist_snapshot,
    universe_symbols_as_of,
)

MARKET = "binance_usdm"


def _cand(symbol: str) -> UniverseCandidate:
    base = symbol.replace("USDT", "")
    return UniverseCandidate(
        symbol=symbol, ccxt_symbol=f"{base}/USDT:USDT", base=base, quote="USDT",
        quote_volume_24h=1e9, median_volume_usd=1e7, spread_bps=1.0,
    )


async def test_scan_uses_snapshot_valid_at_test_date(db_session: AsyncSession) -> None:
    # An old universe (Jan) and a newer one (Jun) — the winners list changed.
    await persist_snapshot(
        db_session, MARKET, [_cand("AAAUSDT"), _cand("BBBUSDT")], {"v": 1}, as_of=date(2024, 1, 1)
    )
    await persist_snapshot(
        db_session, MARKET, [_cand("CCCUSDT"), _cand("DDDUSDT")], {"v": 2}, as_of=date(2024, 6, 1)
    )

    # A backtest dated in March must see the January universe, not June's.
    march = await universe_symbols_as_of(db_session, MARKET, date(2024, 3, 1))
    assert march == ["AAAUSDT", "BBBUSDT"]
    # July sees June.
    july = await universe_symbols_as_of(db_session, MARKET, date(2024, 7, 1))
    assert july == ["CCCUSDT", "DDDUSDT"]
    # Before any snapshot ⇒ empty (nothing to survive on).
    assert await universe_symbols_as_of(db_session, MARKET, date(2023, 1, 1)) == []
    # "Latest" is the June list — which is exactly what a naive scan would wrongly use.
    assert await latest_universe_symbols(db_session, MARKET) == ["CCCUSDT", "DDDUSDT"]
