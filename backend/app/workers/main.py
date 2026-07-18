"""arq worker entrypoint.

Phase 0: Redis heartbeat for the container healthcheck.
Phase 1: on-demand data sync job + incremental-sync and universe-refresh crons.

Heavy imports (ccxt/pandas/sqlalchemy) are done lazily inside jobs so the
healthcheck (``python -m app.workers.healthcheck``) stays fast.

Run with: ``arq app.workers.main.WorkerSettings``
"""

from __future__ import annotations

import logging
import time
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "unknownincome:worker:heartbeat"
HEARTBEAT_TTL = 60  # seconds


async def heartbeat(ctx: dict[str, Any]) -> None:
    """Write a fresh heartbeat timestamp; the container healthcheck reads it."""
    await ctx["redis"].set(HEARTBEAT_KEY, str(int(time.time())), ex=HEARTBEAT_TTL)


async def startup(ctx: dict[str, Any]) -> None:
    """Seed heartbeat and ensure the DB schema exists."""
    from app.core.db import init_models
    from app.core.logging import configure_logging

    configure_logging()
    await heartbeat(ctx)
    await init_models()


async def sync_data_job(
    ctx: dict[str, Any],
    symbols: list[str] | None,
    timeframes: list[str],
    months: float,
    funding: bool,
    incremental: bool,
) -> dict[str, int]:
    """Backfill/incremental sync for the given (or latest-universe) symbols."""
    from app.core.db import SessionLocal
    from app.data.adapters.binance_usdm import BinanceUsdmAdapter
    from app.data.sync import resolve_market_infos, sync_symbol
    from app.data.universe import latest_universe_symbols

    adapter = BinanceUsdmAdapter()
    series = 0
    try:
        async with SessionLocal() as session:
            requested = symbols or await latest_universe_symbols(session, adapter.market)
            infos = await resolve_market_infos(adapter, requested)
            for info in infos:
                results = await sync_symbol(
                    adapter,
                    session,
                    info,
                    timeframes,
                    months,
                    funding,
                    settings.ohlcv_fetch_limit,
                    incremental=incremental,
                )
                series += len(results)
            return {"symbols": len(infos), "series": series}
    finally:
        await adapter.close()


async def incremental_sync(ctx: dict[str, Any]) -> None:
    """Cron: pull newly closed bars for the active universe (best-effort)."""
    from app.core.db import SessionLocal
    from app.data.adapters.binance_usdm import BinanceUsdmAdapter
    from app.data.sync import resolve_market_infos, sync_symbol
    from app.data.universe import latest_universe_symbols

    try:
        async with SessionLocal() as session:
            symbols = await latest_universe_symbols(session, settings.market)
            if not symbols:
                return
            adapter = BinanceUsdmAdapter()
            try:
                for info in await resolve_market_infos(adapter, symbols):
                    await sync_symbol(
                        adapter,
                        session,
                        info,
                        settings.default_timeframes,
                        0,
                        False,
                        settings.ohlcv_fetch_limit,
                        incremental=True,
                    )
            finally:
                await adapter.close()
    except Exception as exc:  # pragma: no cover - cron resilience
        logger.warning("incremental_sync failed: %s", exc)


async def refresh_universe(ctx: dict[str, Any]) -> None:
    """Cron: rebuild the dynamic universe and write a dated snapshot."""
    from app.core.db import SessionLocal
    from app.data.adapters.binance_usdm import BinanceUsdmAdapter
    from app.data.universe import build_universe

    adapter = BinanceUsdmAdapter()
    try:
        async with SessionLocal() as session:
            snapshot = await build_universe(adapter, session)
            logger.info("universe refreshed: %d symbols", len(snapshot.symbols))
    except Exception as exc:  # pragma: no cover - cron resilience
        logger.warning("refresh_universe failed: %s", exc)
    finally:
        await adapter.close()


class WorkerSettings:
    """arq worker configuration."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    functions = [sync_data_job]
    cron_jobs = [
        cron(heartbeat, second={0, 15, 30, 45}, run_at_startup=True),
        cron(incremental_sync, minute=set(range(0, 60, 5))),
        cron(refresh_universe, weekday="mon", hour=0, minute=5),
    ]
