"""Thin arq enqueue helper (kept separate so API handlers stay Redis-agnostic)."""

from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings


async def enqueue(job_name: str, *args: object) -> str | None:
    """Enqueue an arq job by name; returns the job id (or ``None``)."""
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job(job_name, *args)
        return job.job_id if job else None
    finally:
        await pool.close()
