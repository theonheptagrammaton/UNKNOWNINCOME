"""Kill switch — four independent channels, one fast signal (doc §9.4, §10.3).

Channels: the UI button, ``POST /api/bot/killswitch``, the on-disk ``KILLSWITCH``
file flag, and Telegram ``/kill``. The first, second and fourth all funnel through
:func:`engage`, which drops the **file** on the shared data volume; the third *is*
that file. So the bot only has to poll one cheap, cross-process predicate
(file exists) to honour all four — and it polls fast enough to stop in < 2 s.

The authoritative record also lives in ``settings`` (survives a volume wipe) and
every engage/clear writes an ``audit_log`` row. Engaging cancels open orders and
closes the new-order path; open positions are left for the operator to close or
hold (doc §9.4).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.clock import now_ms
from app.core.config import settings
from app.core.settings_store import KEY_KILLSWITCH, get_setting, set_setting


def killswitch_path() -> Path:
    """Absolute path of the file flag (shared across api/worker via the data volume)."""
    if settings.killswitch_file:
        return Path(settings.killswitch_file)
    return Path(settings.data_dir) / "KILLSWITCH"


class KillSwitch:
    """A fast, synchronous engagement check the bot loop polls every ~0.5 s."""

    def __init__(
        self, file_path: Path | None = None, extra_sources: list[Callable[[], bool]] | None = None
    ) -> None:
        self._file_path = file_path or killswitch_path()
        self._extra = extra_sources or []

    def is_engaged(self) -> bool:
        """Engaged if the file flag exists or any extra source reports engaged."""
        try:
            if self._file_path.exists():
                return True
        except OSError:  # pragma: no cover - fs edge
            pass
        return any(src() for src in self._extra)

    def engage_file(self, reason: str = "") -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_path.write_text(reason or "engaged")

    def clear_file(self) -> None:
        try:
            self._file_path.unlink()
        except FileNotFoundError:
            pass


async def engage(session: AsyncSession, actor: str = "api", reason: str = "") -> None:
    """Engage the kill switch from a control channel (UI/API/Telegram). Caller commits."""
    KillSwitch().engage_file(reason)
    await set_setting(
        session, KEY_KILLSWITCH, {"engaged": True, "actor": actor, "ts": now_ms(), "reason": reason}
    )
    await write_audit(session, actor, "killswitch.engage", {"reason": reason})


async def clear(session: AsyncSession, actor: str = "api") -> None:
    """Clear the kill switch so the bot may resume (deliberate operator action)."""
    KillSwitch().clear_file()
    await set_setting(session, KEY_KILLSWITCH, {"engaged": False, "actor": actor, "ts": now_ms()})
    await write_audit(session, actor, "killswitch.clear", {})


async def is_engaged_db(session: AsyncSession) -> bool:
    """Authoritative DB view of the flag (bot uses the file for the fast path)."""
    value = await get_setting(session, KEY_KILLSWITCH)
    return bool((value or {}).get("engaged")) or killswitch_path().exists()
