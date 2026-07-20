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
    """Seed heartbeat, ensure the schema exists and launch the paper bot loop (§9.1)."""
    from app.core.db import init_models
    from app.core.logging import configure_logging
    from app.strategy.plugin_loader import load_plugins

    configure_logging()
    await heartbeat(ctx)
    await init_models()
    load_plugins()  # register plugin primitives (doc §8.6)

    if settings.bot_enabled:
        await _start_bot(ctx)


async def _enqueue_reopt(strategy_id: str) -> None:
    """Best-effort enqueue of a degradation-triggered re-optimization (doc §8.5)."""
    from app.core.queue import enqueue

    await enqueue("reopt_strategy_job", strategy_id)


async def _start_bot(ctx: dict[str, Any]) -> None:
    """Rehydrate + run the paper trading loop as a supervised background task."""
    import asyncio

    from app.bot.engine import BotEngine
    from app.bot.notifier import default_notifier
    from app.bot.telegram import run_polling
    from app.core.db import SessionLocal

    engine = BotEngine(
        SessionLocal, notifier=default_notifier(), reopt_enqueue=_enqueue_reopt
    )
    try:
        async with SessionLocal() as session:
            await engine.rehydrate(session)
            await session.commit()
    except Exception as exc:  # pragma: no cover - startup resilience
        logger.warning("bot rehydrate skipped: %s", exc)

    stop = {"v": False}
    ctx["bot_stop"] = stop

    async def _sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)

    ctx["bot_task"] = asyncio.create_task(
        engine.run(stop=lambda: stop["v"], sleep=_sleep)
    )
    ctx["telegram_task"] = asyncio.create_task(
        run_polling(SessionLocal, lambda: stop["v"])
    )
    logger.info("paper bot loop started")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Signal the bot loop to stop and cancel its background tasks."""
    stop = ctx.get("bot_stop")
    if stop is not None:
        stop["v"] = True
    for key in ("bot_task", "telegram_task"):
        task = ctx.get(key)
        if task is not None:
            task.cancel()


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


async def run_backtest_job(ctx: dict[str, Any], run_id: str) -> dict[str, str]:
    """Run a queued backtest (§6) and persist its outcome + report artifact."""
    from app.backtest.service import execute_backtest
    from app.core.db import SessionLocal

    async with SessionLocal() as session:
        await execute_backtest(session, run_id)
    return {"run_id": run_id}


async def run_discovery_job(ctx: dict[str, Any], scan_id: str) -> dict[str, str]:
    """Run a queued discovery scan (§7) and persist its leaderboard + artifact."""
    from app.core.db import SessionLocal
    from app.discovery.service import execute_scan

    async with SessionLocal() as session:
        await execute_scan(session, scan_id)
    return {"scan_id": scan_id}


async def reopt_strategy_job(ctx: dict[str, Any], strategy_id: str) -> dict[str, str | None]:
    """Re-optimize one strategy (WFO v1) → a pending-approval version (doc §8.3, §8.5)."""
    from app.bot.notifier import default_notifier
    from app.core.db import SessionLocal
    from app.strategy import regen

    async with SessionLocal() as session:
        version = await regen.regenerate(
            session, strategy_id, reason="degrade", notifier=default_notifier()
        )
        await session.commit()
        return {"strategy_id": strategy_id, "version_id": version.id if version else None}


async def scheduled_reopt(ctx: dict[str, Any]) -> None:
    """Cron: weekly WFO re-optimization of every running strategy (doc §8.3 v1)."""
    if not settings.reopt_enabled:
        return
    from app.bot.notifier import default_notifier
    from app.core.db import SessionLocal
    from app.strategy.scheduler import run_scheduled_reopt

    try:
        produced = await run_scheduled_reopt(SessionLocal, default_notifier())
        logger.info("weekly reopt: %d pending version(s) queued for approval", len(produced))
    except Exception as exc:  # pragma: no cover - cron resilience
        logger.warning("scheduled_reopt failed: %s", exc)


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
    on_shutdown = shutdown
    functions = [sync_data_job, run_backtest_job, run_discovery_job, reopt_strategy_job]
    cron_jobs = [
        cron(heartbeat, second={0, 15, 30, 45}, run_at_startup=True),
        cron(incremental_sync, minute=set(range(0, 60, 5))),
        cron(refresh_universe, weekday="mon", hour=0, minute=5),
        # Weekly WFO re-optimization (doc §8.3 v1). Sunday 03:00 UTC, off-peak.
        cron(scheduled_reopt, weekday="sun", hour=3, minute=0),
    ]
