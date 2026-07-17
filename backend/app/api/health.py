"""Health check endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.version import APP_VERSION, get_git_sha

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: returns app version and git sha (doc Phase 0)."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "git_sha": get_git_sha(),
        "time": datetime.now(UTC).isoformat(),
    }
