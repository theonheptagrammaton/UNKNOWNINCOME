"""Application logging setup.

Uvicorn only configures its own loggers, so ``app.*`` INFO logs (indicator cache
HIT/MISS, registry sync, data sync) never reach stdout by default. This attaches
a stream handler to the ``app`` logger at ``settings.log_level`` — making the
cache-hit logging (doc §5.5 acceptance) observable in production, not just tests.
"""

from __future__ import annotations

import logging

from app.core.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    """Route ``app.*`` logs to stdout at the configured level (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        app_logger.addHandler(handler)
    # Leave propagate=True: the root logger has no INFO handler under uvicorn, so
    # there is no double-emission, and pytest's caplog still captures via the root.
    _CONFIGURED = True
