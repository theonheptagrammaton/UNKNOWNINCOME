"""Open-interest collector (Faz 11 §25.3): grid write, gap scan, resilient poll.

The poll loop is driven with injected ``fetch``/``sleep``/``now_ms`` so it is exercised
deterministically — no network, no real time. Backs the acceptance: OI is written on a
5-minute grid, gap scanning uses the same discipline as OHLCV, and one symbol's failure
does not stop the loop.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.data.collectors.open_interest import oi_row, run_oi_collector, scan_gaps
from app.data.parquet_store import read_open_interest
from app.data.timeframes import OI_INTERVAL_MS

MKT = "binance_usdm"


def _oi(amount: float, value: float | None = None) -> dict:
    return {"openInterestAmount": amount, "openInterestValue": value}


def test_oi_row_aligns_to_grid_and_allows_missing_value() -> None:
    row = oi_row(_oi(1234.5), grid_ts=OI_INTERVAL_MS * 3 + 777)
    assert row["ts"] == OI_INTERVAL_MS * 3 + 777  # caller passes the floored grid ts
    assert row["open_interest"] == 1234.5
    assert row["open_interest_value"] != row["open_interest_value"]  # NaN when absent


async def test_poll_writes_on_five_minute_grid(data_dir: Path) -> None:
    """Three ticks 5 min apart → three rows on the OI grid, no gaps (§25.5)."""
    t0 = OI_INTERVAL_MS * 1000
    clock = {"t": t0}
    amounts = iter([100.0, 110.0, 120.0])

    async def fetch(_symbol: str) -> dict:
        return _oi(next(amounts))

    async def sleep(_s: float) -> None:
        clock["t"] += OI_INTERVAL_MS  # advance exactly one grid step per poll

    written = await run_oi_collector(
        fetch, [("BTC/USDT:USDT", "BTCUSDT")], market=MKT,
        poll_seconds=300.0, sleep=sleep, now_ms=lambda: clock["t"], max_polls=3,
    )
    assert written == 3
    df = read_open_interest(MKT, "BTCUSDT").sort_values("ts")
    assert list(df["open_interest"]) == [100.0, 110.0, 120.0]
    assert [int(t) for t in df["ts"]] == [t0, t0 + OI_INTERVAL_MS, t0 + 2 * OI_INTERVAL_MS]
    assert scan_gaps(MKT, "BTCUSDT") == []


async def test_missed_poll_shows_up_as_gap(data_dir: Path) -> None:
    """A skipped grid slot is a detectable interior gap, same rule as OHLCV."""
    t0 = OI_INTERVAL_MS * 2000
    # Poll times t0, t0+5m, then jump to t0+15m (t0+10m slot missed).
    times = iter([t0, t0 + OI_INTERVAL_MS, t0 + 3 * OI_INTERVAL_MS])
    clock = {"t": next(times)}

    async def fetch(_symbol: str) -> dict:
        return _oi(500.0)

    async def sleep(_s: float) -> None:
        clock["t"] = next(times, clock["t"])

    await run_oi_collector(
        fetch, [("BTC/USDT:USDT", "BTCUSDT")], market=MKT,
        sleep=sleep, now_ms=lambda: clock["t"], max_polls=3,
    )
    gaps = scan_gaps(MKT, "BTCUSDT")
    assert gaps == [(t0 + 2 * OI_INTERVAL_MS, t0 + 2 * OI_INTERVAL_MS)]


async def test_one_symbol_failure_does_not_stop_the_loop(
    data_dir: Path, caplog
) -> None:
    """A raising symbol is logged and skipped; healthy symbols still get written."""
    clock = {"t": OI_INTERVAL_MS * 3000}

    async def fetch(symbol: str) -> dict:
        if symbol == "BAD/USDT:USDT":
            raise ConnectionError("boom")
        return _oi(777.0)

    async def sleep(_s: float) -> None:
        clock["t"] += OI_INTERVAL_MS

    with caplog.at_level(logging.WARNING):
        written = await run_oi_collector(
            fetch,
            [("BAD/USDT:USDT", "BADUSDT"), ("BTC/USDT:USDT", "BTCUSDT")],
            market=MKT, sleep=sleep, now_ms=lambda: clock["t"], max_polls=2,
        )
    assert written == 2  # two good polls across two ticks, bad symbol skipped each time
    assert read_open_interest(MKT, "BADUSDT").empty
    assert len(read_open_interest(MKT, "BTCUSDT")) == 2
    assert any("OI poll failed" in r.message for r in caplog.records)
