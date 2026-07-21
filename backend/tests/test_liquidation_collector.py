"""Liquidation collector (Faz 8): parse + dedup + batch flush + reconnect.

The websocket is faked so the resilient loop is exercised deterministically — no
real socket, no sleeping. The acceptance this backs: ``dedup_key UNIQUE`` blocks
double writes, batches flush on size/time, and a drop triggers an auto-reconnect
that is logged.
"""

from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import func, select

from app.data.collectors.liquidations import (
    LiquidationBuffer,
    parse_force_order,
    run_collector,
)
from app.models.market import Liquidation

MARKET = "binance_usdm"


def _evt(symbol: str, side: str, qty: str, price: str, t: int) -> dict:
    """A ``forceOrder`` payload as a dict (what :func:`parse_force_order` takes)."""
    return {
        "e": "forceOrder",
        "E": t,
        "o": {
            "s": symbol, "S": side, "o": "LIMIT", "f": "IOC",
            "q": qty, "p": price, "ap": price, "X": "FILLED",
            "l": qty, "z": qty, "T": t,
        },
    }


def _msg(symbol: str, side: str, qty: str, price: str, t: int) -> str:
    """The same payload as a JSON frame (what the websocket delivers)."""
    return json.dumps(_evt(symbol, side, qty, price, t))


class _FakeWS:
    """Yields queued frames; raises the queued exceptions to simulate a drop."""

    def __init__(self, frames: list[object]) -> None:
        self._frames = list(frames)

    async def __aenter__(self) -> _FakeWS:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def recv(self) -> str:
        if not self._frames:
            raise ConnectionError("stream exhausted")
        item = self._frames.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


# ── Pure parse ────────────────────────────────────────────────────────────────
def test_parse_force_order_maps_fields() -> None:
    ev = parse_force_order(
        {
            "e": "forceOrder", "E": 1568014460893,
            "o": {"s": "BTCUSDT", "S": "SELL", "o": "LIMIT", "f": "IOC",
                  "q": "0.014", "p": "9910", "ap": "9905", "X": "FILLED",
                  "l": "0.014", "z": "0.014", "T": 1568014460900},
        },
        MARKET,
    )
    assert ev is not None
    assert ev.symbol == "BTCUSDT"
    assert ev.side == "SELL"
    assert ev.filled_qty == pytest.approx(0.014)
    assert ev.quote_qty == pytest.approx(9905 * 0.014)  # uses avg price
    assert ev.event_time == 1568014460893
    assert ev.trade_time == 1568014460900
    assert ev.dedup_key == "BTCUSDT|1568014460900|SELL|9905.0|0.014"


@pytest.mark.parametrize(
    "raw",
    [{"e": "aggTrade"}, {"e": "forceOrder"}, {"e": "forceOrder", "o": "nope"}, {}],
)
def test_parse_force_order_rejects_non_liquidations(raw: dict) -> None:
    assert parse_force_order(raw, MARKET) is None


# ── Buffer: size + time flush ──────────────────────────────────────────────────
async def test_buffer_flushes_on_row_count(db_session_factory) -> None:
    buf = LiquidationBuffer(db_session_factory, batch_rows=3, batch_seconds=999.0)
    for i in range(2):
        buf.add(parse_force_order(_evt("BTCUSDT", "SELL", "0.1", str(100 + i), 1000 + i), MARKET))
    assert not buf.is_due()  # only 2 < 3 and time not elapsed
    buf.add(parse_force_order(_evt("BTCUSDT", "SELL", "0.1", "200", 2000), MARKET))
    assert buf.is_due()
    written = await buf.flush()
    assert written == 3
    assert buf.pending == 0


async def test_buffer_flushes_on_time(db_session_factory) -> None:
    clock = {"t": 0.0}
    buf = LiquidationBuffer(
        db_session_factory, batch_rows=999, batch_seconds=5.0, clock=lambda: clock["t"]
    )
    buf.add(parse_force_order(_evt("ETHUSDT", "BUY", "1", "50", 1000), MARKET))
    assert not buf.is_due()
    clock["t"] = 5.0
    assert buf.is_due()  # time deadline reached even though row count is tiny
    assert await buf.flush() == 1


# ── Dedup: UNIQUE dedup_key blocks double writes ───────────────────────────────
async def test_duplicate_events_are_deduped(db_session, db_session_factory) -> None:
    buf = LiquidationBuffer(db_session_factory, batch_rows=1, batch_seconds=999.0)
    dup = _evt("BTCUSDT", "SELL", "0.5", "30000", 111)
    for _ in range(3):  # same event three times (e.g. a reconnect replay)
        buf.add(parse_force_order(dup, MARKET))
    await buf.flush()
    total = (await db_session.execute(select(func.count()).select_from(Liquidation))).scalar()
    assert total == 1  # dedup_key UNIQUE kept exactly one


# ── Resilient loop: drop → auto-reconnect (logged) ─────────────────────────────
async def test_loop_reconnects_after_drop_and_is_logged(
    db_session, db_session_factory, caplog
) -> None:
    # Session 1 delivers one event then drops; session 2 delivers another then ends.
    sockets = [
        _FakeWS([_msg("BTCUSDT", "SELL", "0.1", "100", 1), ConnectionError("boom")]),
        _FakeWS([_msg("ETHUSDT", "BUY", "0.2", "200", 2)]),
    ]
    calls = {"n": 0}
    slept: list[float] = []

    def connect(_url: str) -> _FakeWS:
        i = min(calls["n"], len(sockets) - 1)
        calls["n"] += 1
        return sockets[i]

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    # Stop after the loop has reconnected once and drained the second socket.
    def stop() -> bool:
        return calls["n"] >= 3

    with caplog.at_level(logging.WARNING):
        buf = await run_collector(
            db_session_factory,
            connect=connect,
            stop=stop,
            url="ws://fake",
            batch_rows=1,
            batch_seconds=999.0,
            sleep=fake_sleep,
        )

    # Both events persisted across the reconnect.
    total = (await db_session.execute(select(func.count()).select_from(Liquidation))).scalar()
    assert total == 2
    assert buf.total_written == 2
    # The drop was logged and a backoff sleep happened → auto-reconnect proven.
    assert any("WS dropped" in r.message for r in caplog.records)
    assert slept and slept[0] == 1.0
