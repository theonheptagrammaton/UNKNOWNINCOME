"""Telegram remote control — the Trade Deck's pocket shadow (doc §10.3).

Command set: ``/status`` · ``/pnl`` · ``/positions`` · ``/mode paper|off [strategy]``
· ``/kill``. Security is pazarlıksız: only the single whitelisted chat id is obeyed,
``/kill`` and ``/mode live`` require a two-step confirmation, and *every* command
(accepted or rejected) is written to ``audit_log``.

:class:`TelegramBot.handle` is pure of any network — it takes a text + chat id and
returns the reply, so the whole command surface is unit-tested offline. The real
long-poll driver (:func:`run_polling`) and :class:`TelegramNotifier` only come alive
when a bot token is configured (operator step), exactly like the Phase-1 live sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import killswitch as ks
from app.bot.mode import get_global_mode, live_enabled, set_global_mode
from app.core.audit import write_audit
from app.core.config import settings
from app.models.strategy import Strategy
from app.models.trading import EquitySnapshot, Trade
from app.strategy import service as strategy_service

logger = logging.getLogger(__name__)


@dataclass
class TelegramResponse:
    text: str
    accepted: bool = True  # False ⇒ whitelist rejected


@dataclass
class TelegramBot:
    """Stateful command dispatcher (holds pending two-step confirmations)."""

    session_factory: async_sessionmaker[AsyncSession]
    chat_id: str
    _pending: dict[str, str] = field(default_factory=dict)  # chat_id → pending action

    async def handle(self, text: str, chat_id: str) -> TelegramResponse:
        """Dispatch one message; whitelist first, then parse (doc §10.3)."""
        text = (text or "").strip()
        if str(chat_id) != str(self.chat_id):
            async with self.session_factory() as session:
                await write_audit(session, "telegram", "telegram.unauthorized",
                                  {"chat_id": str(chat_id), "text": text})
                await session.commit()
            return TelegramResponse("Unauthorized chat.", accepted=False)

        async with self.session_factory() as session:
            reply = await self._dispatch(session, text)
            await write_audit(session, "telegram", "telegram.command", {"text": text})
            await session.commit()
            return TelegramResponse(reply)

    async def _dispatch(self, session: AsyncSession, text: str) -> str:
        parts = text.split()
        if not parts:
            return "Send /status, /pnl, /positions, /mode, or /kill."
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "/status":
            return await self._status(session)
        if cmd == "/pnl":
            return await self._pnl(session)
        if cmd == "/positions":
            return await self._positions(session)
        if cmd == "/mode":
            return await self._mode(session, args)
        if cmd == "/kill":
            return await self._kill(session, args)
        return "Unknown command. Try /status, /pnl, /positions, /mode, /kill."

    # ── commands ─────────────────────────────────────────────────────────────
    async def _status(self, session: AsyncSession) -> str:
        mode = await get_global_mode(session)
        killed = await ks.is_engaged_db(session)
        active = (await session.execute(select(Strategy))).scalars().all()
        trading = [s for s in active if s.mode in ("paper", "live")]
        last_eq = await _last_equity(session)
        equity = f"{last_eq:.2f}" if last_eq is not None else "—"
        return (
            f"Global mode: {mode.upper()}\n"
            f"Kill switch: {'ENGAGED' if killed else 'clear'}\n"
            f"Strategies: {len(active)} ({len(trading)} switched on)\n"
            f"Equity: {equity}"
        )

    async def _pnl(self, session: AsyncSession) -> str:
        equity = await _last_equity(session)
        day_start = await _day_start_equity(session)
        realized = await _realized_pnl(session)
        if equity is None:
            return "No equity recorded yet."
        day = f"{(equity - day_start):+.2f}" if day_start else "—"
        return f"Equity: {equity:.2f}\nToday: {day}\nRealized (closed): {realized:+.2f}"

    async def _positions(self, session: AsyncSession) -> str:
        rows = (
            await session.execute(
                select(Trade).where(Trade.mode == "paper", Trade.status == "open")
            )
        ).scalars().all()
        if not rows:
            return "No open positions."
        lines = [
            f"{t.symbol} {t.side} ×{t.qty:.4f} @ {t.entry_price:.4f}" for t in rows
        ]
        return "Open positions (paper):\n" + "\n".join(lines)

    async def _mode(self, session: AsyncSession, args: list[str]) -> str:
        from app.bot.promotion import GateNotMet

        if not args:
            return "Usage: /mode paper|off|live [strategy_id]  (live needs the gate, §9.5)"
        target = args[0].lower()
        if target not in ("paper", "off", "live"):
            return "Usage: /mode paper|off|live [strategy_id]"

        rest = args[1:]
        confirm = bool(rest) and rest[-1].lower() == "confirm"
        if confirm:
            rest = rest[:-1]
        strategy_id = rest[0] if rest else None

        # LIVE is a deliberate, two-step action even before the numeric gate runs.
        if target == "live":
            if not live_enabled():
                return "Live trading is disabled server-side (LIVE_TRADING_ENABLED=false)."
            pend = f"mode:live:{strategy_id or 'global'}"
            if not confirm and self._pending.get(self.chat_id) != pend:
                self._pending[self.chat_id] = pend
                suffix = f"{strategy_id} " if strategy_id else ""
                scope = f"strategy {strategy_id[:8]}" if strategy_id else "global mode"
                return f"⚠️ Reply '/mode live {suffix}confirm' to switch {scope} to LIVE."

        try:
            if strategy_id:  # per-strategy switch
                await strategy_service.set_mode(session, strategy_id, target, actor="telegram")
                self._pending.pop(self.chat_id, None)
                return f"Strategy {strategy_id[:8]} → {target.upper()}"
            previous = await set_global_mode(session, target, actor="telegram")
            self._pending.pop(self.chat_id, None)
            return f"Global mode {previous.upper()} → {target.upper()}"
        except GateNotMet as exc:
            return f"⛔ Promotion gate not met (§9.5): {exc}"
        except Exception as exc:  # noqa: BLE001 - surface the reason to the operator
            return f"Could not set mode: {exc}"

    async def _kill(self, session: AsyncSession, args: list[str]) -> str:
        confirm = args and args[0].lower() == "confirm"
        if not confirm and self._pending.get(self.chat_id) != "kill":
            self._pending[self.chat_id] = "kill"
            return "⚠️ Reply '/kill confirm' to engage the KILL SWITCH."
        self._pending.pop(self.chat_id, None)
        await ks.engage(session, actor="telegram", reason="telegram /kill")
        return "🛑 KILL SWITCH engaged. New orders halted; positions left open."


# ── read helpers ─────────────────────────────────────────────────────────────
async def _last_equity(session: AsyncSession) -> float | None:
    row = (
        await session.execute(
            select(EquitySnapshot).where(EquitySnapshot.mode == "paper")
            .order_by(EquitySnapshot.ts.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return row.equity if row else None


async def _day_start_equity(session: AsyncSession) -> float | None:
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ms = int(midnight.timestamp() * 1000)
    row = (
        await session.execute(
            select(EquitySnapshot).where(
                EquitySnapshot.mode == "paper", EquitySnapshot.ts >= start_ms
            ).order_by(EquitySnapshot.ts.asc()).limit(1)
        )
    ).scalar_one_or_none()
    return row.equity if row else None


async def _realized_pnl(session: AsyncSession) -> float:
    rows = (
        await session.execute(
            select(Trade.pnl).where(Trade.mode == "paper", Trade.status == "closed")
        )
    ).scalars().all()
    return float(sum(p for p in rows if p is not None))


# ── real network sink + poller (operator step, token-gated) ─────────────────
class TelegramNotifier:
    """Sends notifications to the whitelisted chat via the Bot API (token-gated)."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    async def notify(self, text: str) -> None:  # pragma: no cover - network
        if not self._token:
            return
        import httpx

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"chat_id": self._chat_id, "text": text})
        except Exception as exc:
            logger.warning("telegram notify failed: %s", exc)


async def run_polling(  # pragma: no cover - network/operator step
    session_factory: async_sessionmaker[AsyncSession], stop: object
) -> None:
    """Long-poll getUpdates and dispatch commands (only when a token is set)."""
    if not (settings.telegram_enabled and settings.telegram_bot_token):
        return
    import asyncio

    import httpx

    bot = TelegramBot(session_factory, settings.telegram_chat_id)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    offset = 0
    async with httpx.AsyncClient(timeout=40) as client:
        while not (callable(stop) and stop()):
            try:
                resp = await client.get(
                    f"{base}/getUpdates", params={"offset": offset, "timeout": 30}
                )
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message") or {}
                    chat = str((msg.get("chat") or {}).get("id", ""))
                    reply = await bot.handle(msg.get("text", ""), chat)
                    if reply.accepted or str(chat) == str(settings.telegram_chat_id):
                        await notifier.notify(reply.text)
            except Exception as exc:
                logger.warning("telegram poll failed: %s", exc)
                await asyncio.sleep(5)
