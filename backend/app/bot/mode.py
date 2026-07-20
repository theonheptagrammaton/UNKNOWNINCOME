"""Mode switch — global + per-strategy Live/Paper/Off (doc §9.6).

There is no per-signal approval; control lives entirely in a three-position switch.
The **effective** mode of a strategy is the *lower* of the global switch and its own
(Off < Paper < Live), so a global Paper setting keeps every strategy out of Live.

LIVE is a real switch position, but it is closed by two gates (Phase 7): the config
master switch ``live_trading_enabled`` (:func:`live_enabled`) and the numeric promotion
gate (§9.5, :mod:`app.bot.promotion`). Flipping any switch to ``live`` is refused here
before it persists unless the gate opens; and even a stored ``live``, if the config
switch is off, executes on paper (:func:`execution_mode`). Every transition is written
to ``audit_log`` and raises a notification.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.settings_store import KEY_GLOBAL_MODE, get_setting, set_setting
from app.models.strategy import MODE_ORDER

MODES = ("off", "paper", "live")


def live_enabled() -> bool:
    """Whether the live venue path is switched on at all (config master switch)."""
    return settings.live_trading_enabled


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
    """The mode orders execute in. Live degrades to paper unless the config switch is on.

    The *numeric* gate (§9.5) and key availability are enforced separately when the
    engine builds the live wall; this is the coarse config-level gate."""
    if effective == "live" and not live_enabled():
        return "paper"
    return effective if should_trade(effective) else "off"


async def get_global_mode(session: AsyncSession) -> str:
    """Read the global switch (defaults to ``off`` when unset)."""
    value = await get_setting(session, KEY_GLOBAL_MODE)
    mode = (value or {}).get("mode", "off")
    return mode if mode in MODES else "off"


async def set_global_mode(session: AsyncSession, mode: str, actor: str = "api") -> str:
    """Set the global switch; the promotion gate (§9.5) guards the LIVE position.

    Records an audit row (doc §9.6). Caller commits. Raises
    :class:`~app.bot.promotion.GateNotMet` if LIVE is requested before the gate opens.
    """
    if mode not in MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    if mode == "live":
        from app.bot.promotion import assert_can_go_live

        await assert_can_go_live(session, "global", None)
    previous = await get_global_mode(session)
    await set_setting(session, KEY_GLOBAL_MODE, {"mode": mode})
    await write_audit(session, actor, "mode.global", {"from": previous, "to": mode})
    return previous
