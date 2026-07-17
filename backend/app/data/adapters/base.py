"""Market-data adapter interface (asset-agnostic core, doc §2 rule 8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketInfo:
    """A tradable instrument as reported by an exchange."""

    ccxt_symbol: str  # exchange-native unified symbol, e.g. BTC/USDT:USDT
    symbol: str  # normalized, e.g. BTCUSDT
    base: str
    quote: str
    active: bool


class MarketDataAdapter(ABC):
    """Read-only market-data source for one market."""

    market: str

    @abstractmethod
    async def list_markets(self) -> list[MarketInfo]:
        """All instruments on the market."""

    @abstractmethod
    async def fetch_ohlcv(
        self, ccxt_symbol: str, tf: str, since_ms: int, limit: int
    ) -> list[list[float]]:
        """OHLCV rows ``[ts, open, high, low, close, volume]`` from ``since_ms``."""

    @abstractmethod
    async def fetch_funding_history(
        self, ccxt_symbol: str, since_ms: int, limit: int
    ) -> list[dict]:
        """Funding-rate history entries from ``since_ms``."""

    @abstractmethod
    async def fetch_tickers(self) -> dict[str, dict]:
        """Current tickers keyed by ccxt symbol (24h volume, bid/ask)."""

    async def close(self) -> None:  # noqa: B027  optional hook, default no-op
        """Release any network resources."""
