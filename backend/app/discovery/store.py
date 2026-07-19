"""On-disk discovery artifacts.

The compact leaderboard summary lives in PostgreSQL (``discovery_scans.leaderboard``);
the heavy full leaderboard — every finalist's genome, WFO layers, Monte-Carlo band
and alarms — is written next to the market data as JSON so the API can stream it
back without bloating the database (mirrors ``app.backtest.store``).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings

ARTIFACT_SUBDIR = "_discovery"


def artifact_dir(scan_id: str) -> Path:
    return Path(settings.data_dir) / ARTIFACT_SUBDIR / scan_id


def write_leaderboard(scan_id: str, payload: dict) -> str:
    """Write ``leaderboard.json`` for a scan; returns its absolute path."""
    directory = artifact_dir(scan_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "leaderboard.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return str(path)


def read_leaderboard(artifact_path: str | None) -> dict | None:
    """Load a scan's full leaderboard from disk (``None`` if absent)."""
    if not artifact_path:
        return None
    path = Path(artifact_path)
    if not path.exists():
        return None
    return json.loads(path.read_text())
