"""Mode switch — global + per-strategy Live/Paper/Off (doc §9.6).

There is no per-signal approval; control lives entirely in a three-position switch.
The **effective** mode of a strategy is the *lower* of the global switch and its own
(Off < Paper < Live), so a global Paper setting keeps every strategy out of Live.

LIVE is a real switch position and is stored/shown, but there is no live adapter
until Phase 7, so :func:`execution_mode` never returns "live" — an effective-Live
strategy still executes on paper (the UI disables the Live position with a tooltip).
Every transition is written to ``audit_log`` and raises a notification.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.settings_store import KEY_GLOBAL_MODE, get_setting, set_setting
from app.models.strategy import MODE_ORDER

MODES = ("off", "paper", "live")
# Live execution is gated until Phase 7 (no live adapter yet).
LIVE_ENABLED = False


def effective_mode(global_mode: str, strategy_mode: str) -> str:
    """The lower of the two switches (Off < Paper < Live), doc §9.6."""
    g = MODE_ORDER.get(global_mode, 0)
    s = MODE_ORDER.get(strategy_mode, 0)
    lower = min(g, s)
    for name, rank in MODE_ORDER.items():
        if rank == lower:
            return name
    return "off"


def should_trade(effective: str) -> bool:
    """Whether the bot acts on a strategy at this effective mode."""
    return MODE_ORDER.get(effective, 0) >= MODE_ORDER["paper"]


def execution_mode(effective: str) -> str:
    """The mode orders actually execute in. Live is paper until Phase 7."""
    if effective == "live" and not LIVE_ENABLED:
        return "paper"
    return effective if should_trade(effective) else "off"


async def get_global_mode(session: AsyncSession) -> str:
    """Read the global switch (defaults to ``off`` when unset)."""
    value = await get_setting(session, KEY_GLOBAL_MODE)
    mode = (value or {}).get("mode", "off")
    return mode if mode in MODES else "off"


async def set_global_mode(session: AsyncSession, mode: str, actor: str = "api") -> str:
    """Set the global switch; records an audit row (doc §9.6). Caller commits."""
    if mode not in MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    previous = await get_global_mode(session)
    await set_setting(session, KEY_GLOBAL_MODE, {"mode": mode})
    await write_audit(session, actor, "mode.global", {"from": previous, "to": mode})
    return previous
