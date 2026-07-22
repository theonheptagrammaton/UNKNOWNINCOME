"""Open-interest collector — 5-minute REST poll (Faz 11 §25.3).

Open interest tells apart moves that look identical on price: *price ↑ + OI ↑* is new
money, *price ↑ + OI ↓* is short-covering. Binance exposes only ~30 days of OI history
over REST, so — like liquidations — it is collected **forward**: poll the current OI
every 5 minutes and append it on a 5-minute grid. Gap scanning reuses the exact OHLCV
discipline (:func:`app.data.gaps.find_gaps` on the OI grid), so a missed poll shows up
as a gap rather than silently vanishing.

Three testable pieces (the collector loop is injectable — no real network, no sleeping):

* :func:`oi_row` — pure ``fetch_open_interest`` dict → a grid-aligned Parquet row.
* :func:`scan_gaps` — interior gaps in the stored OI series (same rule as OHLCV).
* :func:`run_oi_collector` — the resilient poll loop; a failing symbol is logged and
  skipped, the loop keeps polling the rest.

Run standalone (operator / systemd):

    python -m app.data.collectors.open_interest
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

import pandas as pd

from app.core.config import settings
from app.data.gaps import find_gaps
from app.data.parquet_store import OPEN_INTEREST_COLUMNS, read_open_interest, write_open_interest
from app.data.timeframes import OI_INTERVAL_MS, OI_TF

logger = logging.getLogger(__name__)

# (ccxt_symbol, normalized_symbol) pairs the loop polls each tick.
SymbolPair = tuple[str, str]
Fetch = Callable[[str], Awaitable[dict]]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _grid_ts(now_ms: int) -> int:
    """Floor a wall-clock time to the 5-minute OI grid open."""
    return (now_ms // OI_INTERVAL_MS) * OI_INTERVAL_MS


def oi_row(oi: dict, grid_ts: int) -> dict[str, float]:
    """Map a ccxt ``fetch_open_interest`` dict to a grid-aligned Parquet row.

    The row's ``ts`` is the poll's 5-minute grid open (not the venue timestamp) so the
    series stays on a regular grid for gap scanning. ``openInterestValue`` is optional
    (Binance USDT-M returns only the base amount) → NaN when absent.
    """
    amount = oi.get("openInterestAmount")
    value = oi.get("openInterestValue")
    return {
        "ts": int(grid_ts),
        "open_interest": float(amount) if amount is not None else float("nan"),
        "open_interest_value": float(value) if value is not None else float("nan"),
    }


def scan_gaps(market: str, symbol: str) -> list[tuple[int, int]]:
    """Interior gaps in the stored OI series (same discipline as OHLCV, §25.5)."""
    df = read_open_interest(market, symbol)
    if df.empty:
        return []
    present = sorted(int(t) for t in df["ts"].tolist())
    return find_gaps(present, OI_TF)


def _write_row(market: str, symbol: str, row: dict[str, float]) -> None:
    write_open_interest(
        market, symbol, pd.DataFrame([row], columns=OPEN_INTEREST_COLUMNS)
    )


async def run_oi_collector(
    fetch: Fetch,
    symbols: list[SymbolPair],
    *,
    market: str | None = None,
    stop: Callable[[], bool] = lambda: False,
    poll_seconds: float | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    now_ms: Callable[[], int] = _now_ms,
    max_polls: int | None = None,
) -> int:
    """Poll current OI for each symbol every ``poll_seconds`` until ``stop()``.

    ``fetch``/``sleep``/``now_ms`` are injectable so the loop is unit-tested without a
    socket or real time. A failing symbol is logged and skipped (the poll continues for
    the rest). Returns the total number of rows written.
    """
    mkt = market or settings.market
    interval = poll_seconds if poll_seconds is not None else settings.open_interest_poll_seconds
    written = 0
    polls = 0
    while not stop():
        grid_ts = _grid_ts(now_ms())
        for ccxt_symbol, symbol in symbols:
            try:
                oi = await fetch(ccxt_symbol)
                _write_row(mkt, symbol, oi_row(oi, grid_ts))
                written += 1
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the loop
                logger.warning("OI poll failed for %s (%s: %s)", symbol, type(exc).__name__, exc)
        polls += 1
        if max_polls is not None and polls >= max_polls:
            break
        if stop():
            break
        await sleep(interval)
    logger.info("OI collector stopped (rows written=%d over %d polls)", written, polls)
    return written


def main() -> int:  # pragma: no cover - operator entry point
    """Standalone runner (systemd-friendly): poll OI for the latest universe."""
    from app.core.db import SessionLocal, init_models
    from app.core.logging import configure_logging
    from app.data.adapters.binance_usdm import BinanceUsdmAdapter
    from app.data.sync import resolve_market_infos
    from app.data.universe import latest_universe_symbols

    configure_logging()
    logging.getLogger("app").setLevel(logging.INFO)
    stop_flag = {"v": False}

    async def _run() -> None:
        await init_models()
        adapter = BinanceUsdmAdapter()
        try:
            async with SessionLocal() as session:
                names = await latest_universe_symbols(session, adapter.market)
            infos = await resolve_market_infos(adapter, names)
            pairs = [(i.ccxt_symbol, i.symbol) for i in infos]
            logger.info("OI collector polling %d symbols every %.0fs", len(pairs),
                        settings.open_interest_poll_seconds)
            await run_oi_collector(adapter.fetch_open_interest, pairs, stop=lambda: stop_flag["v"])
        finally:
            await adapter.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        stop_flag["v"] = True
        logger.info("OI collector interrupted; exiting")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
