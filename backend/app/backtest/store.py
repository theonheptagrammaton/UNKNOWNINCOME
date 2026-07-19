"""On-disk backtest artifacts.

The metric summary lives in PostgreSQL; the heavy report (candles/equity/
drawdown/markers/trades) is written next to the market data as JSON so the API
can stream it back without bloating the database.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings

ARTIFACT_SUBDIR = "_backtests"


def artifact_dir(run_id: str) -> Path:
    """Directory holding a run's artifacts."""
    return Path(settings.data_dir) / ARTIFACT_SUBDIR / run_id


def write_report(run_id: str, report: dict) -> str:
    """Write ``report.json`` for a run; returns its absolute path."""
    directory = artifact_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "report.json"
    path.write_text(json.dumps(report, separators=(",", ":")))
    return str(path)


def read_report(artifact_path: str | None) -> dict | None:
    """Load a run's report from disk (``None`` if absent)."""
    if not artifact_path:
        return None
    path = Path(artifact_path)
    if not path.exists():
        return None
    return json.loads(path.read_text())
