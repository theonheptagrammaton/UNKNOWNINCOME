"""Binance USDT-M liquidation collector — the ``!forceOrder@arr`` stream (Faz 8).

**Why this exists in a phase that ships no features.** Liquidation data *cannot be
backfilled*: Binance only pushes forced-liquidation orders live, over a websocket.
If we don't start collecting today, a year from now we have a year-long hole. So the
Phase-8 note (v2 §22 / §25) has us start now even though **nothing reads this yet** —
Faz 11 turns it into the ``liq_cascade`` primitive. Until then it only accumulates.

Design (three testable pieces):

* :func:`parse_force_order` — pure ``forceOrder`` JSON → :class:`LiquidationEvent`,
  including a ``dedup_key`` that uniquely identifies the event.
* :class:`LiquidationBuffer` — buffers events and flushes on **≥500 rows OR ≥5 s**,
  inserting with ``ON CONFLICT (dedup_key) DO NOTHING`` so a reconnect that replays
  recent events never double-writes.
* :func:`run_collector` — the resilient consume loop: reconnect with capped
  exponential backoff; every drop **and** every reconnect is logged (the Phase-8
  acceptance wants at least one drop + auto-reconnect in the log).

Run standalone (operator / systemd):

    python -m app.data.collectors.liquidations

or let the arq worker start it (``LIQUIDATION_COLLECTOR_ENABLED=true``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.market import Liquidation

logger = logging.getLogger(__name__)

# All-market forced-liquidation stream. Mainnet vs testnet base host differs; the
# stream path is identical. No per-symbol subscription — ``@arr`` delivers all.
MAINNET_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
TESTNET_URL = "wss://stream.binancefuture.com/ws/!forceOrder@arr"

BATCH_ROWS = 500
BATCH_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 60.0

SessionFactory = async_sessionmaker[AsyncSession]


def stream_url(*, testnet: bool | None = None) -> str:
    """The websocket URL for the current venue (mainnet unless testnet)."""
    use_testnet = settings.binance_testnet if testnet is None else testnet
    return TESTNET_URL if use_testnet else MAINNET_URL


@dataclass(frozen=True)
class LiquidationEvent:
    """One forced-liquidation order, ready to persist."""

    market: str
    symbol: str
    side: str
    price: float
    avg_price: float
    orig_qty: float
    filled_qty: float
    quote_qty: float
    order_status: str
    event_time: int
    trade_time: int
    dedup_key: str

    def as_row(self) -> dict[str, Any]:
        """Column mapping for a bulk ``insert``."""
        return {
            "market": self.market,
            "symbol": self.symbol,
            "side": self.side,
            "price": self.price,
            "avg_price": self.avg_price,
            "orig_qty": self.orig_qty,
            "filled_qty": self.filled_qty,
            "quote_qty": self.quote_qty,
            "order_status": self.order_status,
            "event_time": self.event_time,
            "trade_time": self.trade_time,
            "dedup_key": self.dedup_key,
        }


def parse_force_order(raw: dict[str, Any], market: str) -> LiquidationEvent | None:
    """Parse a ``forceOrder`` payload; return ``None`` if it is not one / is malformed.

    Binance payload shape (both ``<symbol>@forceOrder`` and ``!forceOrder@arr``)::

        {"e":"forceOrder","E":1568014460893,
         "o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"0.014",
              "p":"9910","ap":"9910","X":"FILLED","l":"0.014","z":"0.014",
              "T":1568014460893}}
    """
    if raw.get("e") != "forceOrder":
        return None
    o = raw.get("o")
    if not isinstance(o, dict):
        return None
    try:
        symbol = str(o["s"])
        side = str(o["S"])
        price = float(o["p"])
        avg_price = float(o["ap"])
        orig_qty = float(o["q"])
        filled_qty = float(o["z"])
        order_status = str(o["X"])
        event_time = int(raw["E"])
        trade_time = int(o["T"])
    except (KeyError, TypeError, ValueError):
        return None

    # ``ap`` (average fill price) is 0 for a not-yet-filled order; fall back to ``p``.
    ref_price = avg_price if avg_price > 0 else price
    quote_qty = ref_price * filled_qty
    # symbol · trade-time · side · avg-price · filled-qty uniquely identifies an event.
    dedup_key = f"{symbol}|{trade_time}|{side}|{avg_price}|{filled_qty}"
    return LiquidationEvent(
        market=market,
        symbol=symbol,
        side=side,
        price=price,
        avg_price=avg_price,
        orig_qty=orig_qty,
        filled_qty=filled_qty,
        quote_qty=quote_qty,
        order_status=order_status,
        event_time=event_time,
        trade_time=trade_time,
        dedup_key=dedup_key,
    )


async def _insert_ignore(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Bulk insert, skipping rows whose ``dedup_key`` already exists.

    Uses the dialect-native ``ON CONFLICT DO NOTHING`` (both PostgreSQL and SQLite
    support it), so a reconnect that replays events is idempotent. Returns the number
    of rows actually inserted where the driver reports it.
    """
    if not rows:
        return 0
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert
    stmt = _insert(Liquidation).values(rows).on_conflict_do_nothing(
        index_elements=["dedup_key"]
    )
    result = await session.execute(stmt)
    return result.rowcount if result.rowcount and result.rowcount > 0 else 0


class LiquidationBuffer:
    """Buffers events and flushes on **≥batch_rows OR ≥batch_seconds** (doc §22)."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        batch_rows: int = BATCH_ROWS,
        batch_seconds: float = BATCH_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._batch_rows = batch_rows
        self._batch_seconds = batch_seconds
        self._clock = clock
        self._buf: list[LiquidationEvent] = []
        self._last_flush = clock()
        self.total_written = 0

    def add(self, event: LiquidationEvent) -> None:
        self._buf.append(event)

    @property
    def pending(self) -> int:
        return len(self._buf)

    def seconds_until_deadline(self) -> float:
        """Seconds until the time-based flush is due (0 if already due / empty)."""
        if not self._buf:
            return self._batch_seconds
        return max(0.0, self._batch_seconds - (self._clock() - self._last_flush))

    def is_due(self) -> bool:
        if not self._buf:
            return False
        return (
            len(self._buf) >= self._batch_rows
            or self._clock() - self._last_flush >= self._batch_seconds
        )

    async def flush(self) -> int:
        """Persist the buffer (dedup-safe) and reset the timer. Returns rows written."""
        if not self._buf:
            self._last_flush = self._clock()
            return 0
        rows = [e.as_row() for e in self._buf]
        written = 0
        try:
            async with self._session_factory() as session:
                written = await _insert_ignore(session, rows)
                await session.commit()
        except Exception:  # noqa: BLE001 - never lose the loop over one bad flush
            logger.exception("liquidation flush failed (%d buffered rows dropped)", len(rows))
        self.total_written += written
        self._buf.clear()
        self._last_flush = self._clock()
        return written


# An async context manager yielding an object with ``async recv() -> str``.
ConnectFactory = Callable[[str], Any]


async def run_collector(
    session_factory: SessionFactory,
    *,
    connect: ConnectFactory | None = None,
    stop: Callable[[], bool] = lambda: False,
    url: str | None = None,
    market: str | None = None,
    batch_rows: int = BATCH_ROWS,
    batch_seconds: float = BATCH_SECONDS,
    max_backoff: float = MAX_BACKOFF_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> LiquidationBuffer:
    """Consume ``!forceOrder@arr`` until ``stop()``; persist in dedup-safe batches.

    Reconnects with capped exponential backoff on any transport error, logging every
    drop and reconnect. ``connect``/``sleep``/``clock`` are injectable so the loop is
    unit-tested without a real socket. Returns the buffer (for its ``total_written``).
    """
    if connect is None:
        import websockets

        connect = websockets.connect  # type: ignore[assignment]
    target = url or stream_url()
    mkt = market or settings.market
    buffer = LiquidationBuffer(
        session_factory, batch_rows=batch_rows, batch_seconds=batch_seconds, clock=clock
    )
    backoff = 1.0

    while not stop():
        try:
            async with connect(target) as ws:
                logger.info("liquidation WS connected: %s", target)
                backoff = 1.0  # a successful connect resets backoff
                while not stop():
                    timeout = buffer.seconds_until_deadline() or batch_seconds
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except TimeoutError:
                        await buffer.flush()  # time-based flush; keep the socket open
                        continue
                    event = parse_force_order(_loads(raw), mkt)
                    if event is not None:
                        buffer.add(event)
                    if buffer.is_due():
                        await buffer.flush()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport error ⇒ reconnect
            await buffer.flush()  # don't lose buffered rows across a reconnect
            if stop():
                break
            logger.warning(
                "liquidation WS dropped (%s: %s); reconnecting in %.1fs",
                type(exc).__name__, exc, backoff,
            )
            await sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    await buffer.flush()  # final flush on a clean stop
    logger.info("liquidation collector stopped (total written=%d)", buffer.total_written)
    return buffer


def _loads(raw: str | bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:  # pragma: no cover - operator entry point
    """Standalone runner (systemd-friendly): collect until Ctrl-C."""
    from app.core.db import SessionLocal, init_models
    from app.core.logging import configure_logging

    configure_logging()
    logging.getLogger("app").setLevel(logging.INFO)

    stop_flag = {"v": False}

    async def _run() -> None:
        await init_models()
        await run_collector(SessionLocal, stop=lambda: stop_flag["v"])

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        stop_flag["v"] = True
        logger.info("liquidation collector interrupted; flushing and exiting")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
