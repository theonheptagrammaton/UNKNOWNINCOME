"""arq worker entrypoint.

Runs background jobs (data sync, scans, WFO, bot loop) in later phases. For
Phase 0 it maintains a Redis heartbeat so the container has a meaningful
health signal proving the arq event loop is alive.

Run with: ``arq app.workers.main.WorkerSettings``
"""

from __future__ import annotations

import time
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings

HEARTBEAT_KEY = "unknownincome:worker:heartbeat"
HEARTBEAT_TTL = 60  # seconds


async def heartbeat(ctx: dict[str, Any]) -> None:
    """Write a fresh heartbeat timestamp; the container healthcheck reads it."""
    await ctx["redis"].set(HEARTBEAT_KEY, str(int(time.time())), ex=HEARTBEAT_TTL)


async def startup(ctx: dict[str, Any]) -> None:
    """Seed the heartbeat immediately so health passes before the first cron."""
    await heartbeat(ctx)


class WorkerSettings:
    """arq worker configuration."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    cron_jobs = [
        cron(heartbeat, second={0, 15, 30, 45}, run_at_startup=True),
    ]
