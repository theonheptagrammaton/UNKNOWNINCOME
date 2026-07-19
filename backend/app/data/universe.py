"""Dynamic universe builder with dated snapshots (doc §4.5).

Selection = USDT-quoted perpetuals, stablecoins and leveraged tokens removed,
ranked by 30-day median USD volume with a spread ceiling, top-N. Every build is
persisted as a dated ``universe_snapshots`` row — the survivorship-bias guard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.data.adapters.base import MarketDataAdapter
from app.models.market import Symbol, UniverseSnapshot

STABLECOINS = frozenset(
    {
        "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "USDD", "PYUSD",
        "GUSD", "USTC", "EUR", "GBP", "USD", "AEUR", "EURI", "XUSD",
    }
)
_LEVERAGED_RE = re.compile(r"(BULL|BEAR)$|\d+(L|S)$")


def is_stablecoin(base: str) -> bool:
    return base.upper() in STABLECOINS


def is_leveraged_token(base: str) -> bool:
    return bool(_LEVERAGED_RE.search(base.upper()))


def spread_bps(ticker: dict) -> float | None:
    """Bid/ask spread in basis points, or ``None`` if unavailable."""
    bid = ticker.get("bid")
    ask = ticker.get("ask")
    if not bid or not ask or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 10_000 if mid > 0 else None


def median_usd_volume(daily_ohlcv: list[list[float]]) -> float:
    """Median of (close × base volume) across daily bars — a USD-volume proxy."""
    vals = [row[4] * row[5] for row in daily_ohlcv if row[4] and row[5]]
    return float(median(vals)) if vals else 0.0


@dataclass
class UniverseCandidate:
    symbol: str
    ccxt_symbol: str
    base: str
    quote: str
    quote_volume_24h: float
    median_volume_usd: float
    spread_bps: float | None


def select_universe(
    candidates: list[UniverseCandidate],
    size: int,
    min_median_volume_usd: float,
    max_spread_bps: float,
) -> list[UniverseCandidate]:
    """Apply exclusions + thresholds, rank by median USD volume, take top-N."""
    eligible: list[UniverseCandidate] = []
    for c in candidates:
        if is_stablecoin(c.base) or is_leveraged_token(c.base):
            continue
        if c.median_volume_usd < min_median_volume_usd:
            continue
        if c.spread_bps is not None and c.spread_bps > max_spread_bps:
            continue
        eligible.append(c)
    eligible.sort(key=lambda c: c.median_volume_usd, reverse=True)
    return eligible[:size]


async def _upsert_symbol(session: AsyncSession, market: str, cand: UniverseCandidate) -> None:
    stmt = select(Symbol).where(Symbol.market == market, Symbol.symbol == cand.symbol)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        session.add(
            Symbol(
                market=market,
                symbol=cand.symbol,
                ccxt_symbol=cand.ccxt_symbol,
                base=cand.base,
                quote=cand.quote,
                active=True,
            )
        )
    else:
        existing.ccxt_symbol = cand.ccxt_symbol
        existing.active = True


async def persist_snapshot(
    session: AsyncSession,
    market: str,
    selected: list[UniverseCandidate],
    criteria: dict,
    as_of: date | None = None,
) -> UniverseSnapshot:
    """Write/replace today's dated snapshot and upsert selected symbols."""
    as_of = as_of or datetime.now(UTC).date()
    for cand in selected:
        await _upsert_symbol(session, market, cand)

    stmt = select(UniverseSnapshot).where(
        UniverseSnapshot.market == market, UniverseSnapshot.as_of_date == as_of
    )
    snapshot = (await session.execute(stmt)).scalar_one_or_none()
    symbols = [c.symbol for c in selected]
    if snapshot is None:
        snapshot = UniverseSnapshot(
            market=market, as_of_date=as_of, symbols=symbols, criteria=criteria
        )
        session.add(snapshot)
    else:
        snapshot.symbols = symbols
        snapshot.criteria = criteria
    await session.commit()
    return snapshot


async def build_universe(
    adapter: MarketDataAdapter,
    session: AsyncSession,
    size: int | None = None,
    now_ms: int | None = None,
) -> UniverseSnapshot:
    """Full build: markets → prefilter by 24h volume → 30d median volume + spread → top-N."""
    size = size or settings.universe_size
    now = now_ms if now_ms is not None else int(datetime.now(UTC).timestamp() * 1000)
    window_ms = settings.universe_volume_window_days * 86_400_000

    markets = await adapter.list_markets()
    tickers = await adapter.fetch_tickers()

    prelim: list[tuple[float, object]] = []
    for m in markets:
        if not m.active or is_stablecoin(m.base) or is_leveraged_token(m.base):
            continue
        ticker = tickers.get(m.ccxt_symbol, {})
        qvol = float(ticker.get("quoteVolume") or 0.0)
        prelim.append((qvol, m))
    prelim.sort(key=lambda t: t[0], reverse=True)
    finalists = prelim[: settings.universe_prefilter_size]

    candidates: list[UniverseCandidate] = []
    for qvol, m in finalists:
        daily = await adapter.fetch_ohlcv(m.ccxt_symbol, "1d", now - window_ms, 60)
        candidates.append(
            UniverseCandidate(
                symbol=m.symbol,
                ccxt_symbol=m.ccxt_symbol,
                base=m.base,
                quote=m.quote,
                quote_volume_24h=qvol,
                median_volume_usd=median_usd_volume(daily),
                spread_bps=spread_bps(tickers.get(m.ccxt_symbol, {})),
            )
        )

    selected = select_universe(
        candidates,
        size=size,
        min_median_volume_usd=settings.universe_min_median_volume_usd,
        max_spread_bps=settings.universe_max_spread_bps,
    )
    criteria = {
        "size": size,
        "quote": settings.universe_quote,
        "min_median_volume_usd": settings.universe_min_median_volume_usd,
        "max_spread_bps": settings.universe_max_spread_bps,
        "volume_window_days": settings.universe_volume_window_days,
        "selected": [
            {
                "symbol": c.symbol,
                "median_volume_usd": round(c.median_volume_usd, 2),
                "spread_bps": round(c.spread_bps, 3) if c.spread_bps is not None else None,
            }
            for c in selected
        ],
    }
    return await persist_snapshot(session, adapter.market, selected, criteria, as_of=None)


async def latest_universe_symbols(session: AsyncSession, market: str) -> list[str]:
    """Symbols from the most recent snapshot (empty list if none)."""
    stmt = (
        select(UniverseSnapshot)
        .where(UniverseSnapshot.market == market)
        .order_by(UniverseSnapshot.as_of_date.desc())
        .limit(1)
    )
    snapshot = (await session.execute(stmt)).scalar_one_or_none()
    return list(snapshot.symbols) if snapshot else []


async def universe_symbols_as_of(
    session: AsyncSession, market: str, as_of: date
) -> list[str]:
    """Symbols from the most recent snapshot **on or before** ``as_of``.

    The survivorship-bias guard (doc §4.5): a backtest dated in the past must use
    the universe that was valid then — never today's winners list. Falls back to an
    empty list if no snapshot predates ``as_of``.
    """
    stmt = (
        select(UniverseSnapshot)
        .where(
            UniverseSnapshot.market == market,
            UniverseSnapshot.as_of_date <= as_of,
        )
        .order_by(UniverseSnapshot.as_of_date.desc())
        .limit(1)
    )
    snapshot = (await session.execute(stmt)).scalar_one_or_none()
    return list(snapshot.symbols) if snapshot else []
