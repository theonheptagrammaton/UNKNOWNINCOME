"""Binance USDT-M perpetual futures adapter (ccxt).

Only public market-data endpoints are used, so API keys are optional.
"""

from __future__ import annotations

import ccxt.async_support as ccxt

from app.core.config import settings
from app.data.adapters.base import MarketDataAdapter, MarketInfo


def normalize_symbol(ccxt_symbol: str) -> str:
    """``BTC/USDT:USDT`` → ``BTCUSDT``."""
    return ccxt_symbol.split(":")[0].replace("/", "")


class BinanceUsdmAdapter(MarketDataAdapter):
    """ccxt-backed adapter for Binance USDT-M perpetuals."""

    market = "binance_usdm"

    def __init__(self) -> None:
        self._ex = ccxt.binanceusdm(
            {
                "apiKey": settings.binance_api_key or None,
                "secret": settings.binance_api_secret or None,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
        )
        if settings.binance_testnet:
            self._ex.set_sandbox_mode(True)

    async def list_markets(self) -> list[MarketInfo]:
        markets = await self._ex.load_markets()
        infos: list[MarketInfo] = []
        for m in markets.values():
            if not (m.get("swap") and m.get("linear")):
                continue
            if m.get("quote") != settings.universe_quote:
                continue
            infos.append(
                MarketInfo(
                    ccxt_symbol=m["symbol"],
                    symbol=normalize_symbol(m["symbol"]),
                    base=m["base"],
                    quote=m["quote"],
                    active=bool(m.get("active", True)),
                )
            )
        return infos

    async def fetch_ohlcv(
        self, ccxt_symbol: str, tf: str, since_ms: int, limit: int
    ) -> list[list[float]]:
        return await self._ex.fetch_ohlcv(ccxt_symbol, timeframe=tf, since=since_ms, limit=limit)

    async def fetch_funding_history(
        self, ccxt_symbol: str, since_ms: int, limit: int
    ) -> list[dict]:
        return await self._ex.fetch_funding_rate_history(ccxt_symbol, since=since_ms, limit=limit)

    async def fetch_tickers(self) -> dict[str, dict]:
        return await self._ex.fetch_tickers()

    async def close(self) -> None:
        await self._ex.close()
