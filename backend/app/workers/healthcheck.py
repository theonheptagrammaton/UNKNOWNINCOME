"""Standalone worker healthcheck: exit 0 if the heartbeat key is present.

Invoked by the Docker healthcheck (``python -m app.workers.healthcheck``).
"""

from __future__ import annotations

import sys

import redis

from app.core.config import settings
from app.workers.main import HEARTBEAT_KEY


def main() -> int:
    try:
        client = redis.Redis.from_url(settings.redis_url)
        return 0 if client.exists(HEARTBEAT_KEY) else 1
    except redis.RedisError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
