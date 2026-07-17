"""Application version and build metadata."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache

APP_VERSION = "0.1.0"


@lru_cache(maxsize=1)
def get_git_sha() -> str:
    """Return the current git commit sha.

    Prefers the ``GIT_SHA`` env var (injected at Docker build time); falls back
    to querying git locally, then to ``"unknown"``.
    """
    env_sha = os.getenv("GIT_SHA")
    if env_sha:
        return env_sha.strip()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"
