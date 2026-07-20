"""Typed helpers over the ``settings`` key-value table (doc §11).

Application state that is neither market data nor a strategy lives here: the global
mode switch, the kill-switch flag, risk limits and promotion-gate thresholds. Values
are always JSON objects (dicts) so the column type stays uniform.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import Setting

# Well-known keys.
KEY_GLOBAL_MODE = "global_mode"
KEY_KILLSWITCH = "killswitch"
KEY_RISK_LIMITS = "risk_limits"
KEY_PROMOTION_GATE = "promotion_gate"
KEY_REGIME_LOCK = "regime_lock"  # {"mode": "off"|"auto"|"trend"|"range"|"trend/high"|…}


async def get_setting(session: AsyncSession, key: str) -> dict | None:
    """Return the JSON value for ``key`` (``None`` if unset)."""
    row = (
        await session.execute(select(Setting).where(Setting.key == key))
    ).scalar_one_or_none()
    return dict(row.value) if row is not None else None


async def set_setting(session: AsyncSession, key: str, value: dict) -> None:
    """Upsert ``key`` → ``value`` (caller commits)."""
    row = (
        await session.execute(select(Setting).where(Setting.key == key))
    ).scalar_one_or_none()
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
