"""Test doubles for the data layer (no network)."""

from __future__ import annotations

from app.data.adapters.base import MarketDataAdapter, MarketInfo
from app.data.timeframes import tf_to_ms


def make_ohlcv(start_ts: int, count: int, tf: str, base_price: float = 100.0) -> list[list[float]]:
    """Deterministic contiguous OHLCV bars ``[ts, o, h, l, c, v]``."""
    step = tf_to_ms(tf)
    bars: list[list[float]] = []
    for i in range(count):
        price = base_price + i
        bars.append([start_ts + i * step, price, price + 1, price - 1, price + 0.5, 10.0 + i])
    return bars


class FakeAdapter(MarketDataAdapter):
    """In-memory adapter returning preconfigured series/markets/tickers."""

    market = "binance_usdm"

    def __init__(
        self,
        series: dict[tuple[str, str], list[list[float]]] | None = None,
        markets: list[MarketInfo] | None = None,
        tickers: dict[str, dict] | None = None,
        funding: dict[str, list[dict]] | None = None,
    ) -> None:
        self.series = series or {}
        self._markets = markets or []
        self._tickers = tickers or {}
        self._funding = funding or {}

    async def list_markets(self) -> list[MarketInfo]:
        return list(self._markets)

    async def fetch_ohlcv(
        self, ccxt_symbol: str, tf: str, since_ms: int, limit: int
    ) -> list[list[float]]:
        bars = self.series.get((ccxt_symbol, tf), [])
        page = [b for b in bars if b[0] >= since_ms][:limit]
        return [list(b) for b in page]

    async def fetch_funding_history(
        self, ccxt_symbol: str, since_ms: int, limit: int
    ) -> list[dict]:
        entries = self._funding.get(ccxt_symbol, [])
        return [e for e in entries if int(e["timestamp"]) >= since_ms][:limit]

    async def fetch_tickers(self) -> dict[str, dict]:
        return dict(self._tickers)
