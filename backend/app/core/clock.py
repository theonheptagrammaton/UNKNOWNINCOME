"""A single source of 'now' in epoch-milliseconds UTC (doc §2 rule 5).

All timestamps in the system are UTC ms; the UI converts to Europe/Istanbul. Tests
inject a fixed or fake clock so bot loops and cooldowns are deterministic (rule #6).
"""

from __future__ import annotations

import time
from collections.abc import Callable

Clock = Callable[[], int]


def now_ms() -> int:
    """Wall-clock time in epoch milliseconds (UTC)."""
    return int(time.time() * 1000)
