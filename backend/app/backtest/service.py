"""Execute a queued backtest and persist its outcome.

Shared by the arq worker and the tests so the run→persist path is exercised the
same way in both. ``run_backtest`` is CPU-bound and synchronous; the surrounding
persistence is async so it composes with the app's SQLAlchemy sessions.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.config import RunConfig
from app.backtest.runner import run_backtest
from app.backtest.store import write_report
from app.models.backtest import BacktestRun

logger = logging.getLogger(__name__)


async def execute_backtest(session: AsyncSession, run_id: str) -> None:
    """Run the backtest for ``run_id`` and update its row (done | failed)."""
    run = (
        await session.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        logger.warning("execute_backtest: run %s not found", run_id)
        return

    run.status = "running"
    await session.commit()

    try:
        config = RunConfig.model_validate(run.config)
        out = run_backtest(config)
        artifact_path = write_report(run_id, out["report"])
        run.metrics = out["metrics"]
        run.artifact_path = artifact_path
        run.status = "done"
        run.error = None
        logger.info("backtest %s done: %d trades", run_id, out["metrics"]["num_trades"])
    except Exception as exc:  # pragma: no cover - exercised via failed-run test
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        logger.warning("backtest %s failed: %s", run_id, exc)
    await session.commit()
