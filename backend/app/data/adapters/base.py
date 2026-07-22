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
        """OHLCV rows from ``since_ms``.

        Each row is ``[ts, open, high, low, close, volume]`` and MAY carry two
        extra trailing fields ``taker_buy_base_volume, number_of_trades`` (Faz 11
        §25.2) when the venue exposes them; the Parquet store treats those as
        optional columns, so a plain 6-wide row is always valid.
        """

    @abstractmethod
    async def fetch_funding_history(
        self, ccxt_symbol: str, since_ms: int, limit: int
    ) -> list[dict]:
        """Funding-rate history entries from ``since_ms``."""

    async def fetch_open_interest(self, ccxt_symbol: str) -> dict:  # noqa: B027
        """Current open interest ``{timestamp, openInterestAmount, openInterestValue}``.

        Optional: OI cannot be backfilled (like liquidations) so it is polled
        forward (doc §25.3). Adapters without an OI endpoint may leave this unset.
        """
        raise NotImplementedError

    @abstractmethod
    async def fetch_tickers(self) -> dict[str, dict]:
        """Current tickers keyed by ccxt symbol (24h volume, bid/ask)."""

    async def close(self) -> None:  # noqa: B027  optional hook, default no-op
        """Release any network resources."""
