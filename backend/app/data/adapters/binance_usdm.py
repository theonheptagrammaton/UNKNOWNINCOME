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
        """One page of klines as extended rows (Faz 11 §25.2).

        ccxt's ``fetch_ohlcv`` throws away ``taker_buy_base_volume`` and
        ``number_of_trades``, so we hit the raw ``fapiPublicGetKlines`` endpoint and
        map the full array. Sync-layer pagination (``fetch_ohlcv_range``) still drives
        ``since``/``limit``; this returns a single page. Falls back to the plain
        6-wide OHLCV if the raw endpoint is unavailable, so the schema stays optional.
        """
        raw_klines = getattr(self._ex, "fapiPublicGetKlines", None)
        if raw_klines is None:  # pragma: no cover - defensive: non-futures ccxt build
            return await self._ex.fetch_ohlcv(
                ccxt_symbol, timeframe=tf, since=since_ms, limit=limit
            )
        market = self._ex.market(ccxt_symbol)
        interval = self._ex.safe_string(self._ex.timeframes, tf, tf)
        params: dict[str, object] = {"symbol": market["id"], "interval": interval, "limit": limit}
        if since_ms is not None:
            params["startTime"] = int(since_ms)
        raw = await raw_klines(params)
        # Binance kline array: [0]=openTime [1]=o [2]=h [3]=l [4]=c [5]=volume
        # [6]=closeTime [7]=quoteVol [8]=numberOfTrades [9]=takerBuyBaseVol …
        return [
            [
                int(k[0]),
                float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]),
                float(k[9]), float(k[8]),
            ]
            for k in raw
        ]

    async def fetch_funding_history(
        self, ccxt_symbol: str, since_ms: int, limit: int
    ) -> list[dict]:
        return await self._ex.fetch_funding_rate_history(ccxt_symbol, since=since_ms, limit=limit)

    async def fetch_open_interest(self, ccxt_symbol: str) -> dict:
        """Current open interest snapshot for one symbol (doc §25.3, 5-min poll)."""
        return await self._ex.fetch_open_interest(ccxt_symbol)

    async def fetch_tickers(self) -> dict[str, dict]:
        return await self._ex.fetch_tickers()

    async def close(self) -> None:
        await self._ex.close()
