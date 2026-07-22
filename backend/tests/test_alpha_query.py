"""Alpha data access (Faz 11 §25.3): OI alignment, liquidation query + bar aggregation.

The liquidation stream (collected live since Faz 8) becomes queryable here and is folded
into a per-bar notional Parquet the ``liq_cascade`` primitive reads through DuckDB. These
tests cover the DB→Parquet aggregation and the lookahead-safe backward-as-of joins.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.alpha import (
    aggregate_liquidations,
    align_backward,
    liq_notional_aligned,
    open_interest_aligned,
    query_liquidations,
)
from app.data.collectors.liquidations import parse_force_order
from app.data.parquet_store import OPEN_INTEREST_COLUMNS, write_open_interest
from app.models.market import Liquidation

MKT = "binance_usdm"
SYM = "BTCUSDT"


def _liq_row(side: str, qty: str, price: str, t: int) -> dict:
    ev = parse_force_order(
        {
            "e": "forceOrder", "E": t,
            "o": {"s": SYM, "S": side, "o": "LIMIT", "f": "IOC",
                  "q": qty, "p": price, "ap": price, "X": "FILLED",
                  "l": qty, "z": qty, "T": t},
        },
        MKT,
    )
    assert ev is not None
    return ev.as_row()


# ── backward-as-of alignment ─────────────────────────────────────────────────
def test_align_backward_is_lookahead_safe() -> None:
    ts = pd.Series([0, 100, 200, 300])
    source = pd.DataFrame({"ts": [50, 250], "v": [1.0, 2.0]})
    out = align_backward(ts, source, ["v"])
    # bar 0 predates any obs → NaN; bars 100/200 carry obs@50; bar 300 carries obs@250.
    assert np.isnan(out["v"].iloc[0])
    assert out["v"].tolist()[1:] == [1.0, 1.0, 2.0]


def test_open_interest_aligned_reads_store(data_dir: Path) -> None:
    write_open_interest(
        MKT, SYM,
        pd.DataFrame(
            {
                "ts": [0, 300_000],
                "open_interest": [10.0, 20.0],
                "open_interest_value": [np.nan, np.nan],
            },
            columns=OPEN_INTEREST_COLUMNS,
        ),
    )
    aligned = open_interest_aligned(MKT, SYM, pd.Series([0, 150_000, 300_000, 450_000]))
    assert aligned.tolist() == [10.0, 10.0, 20.0, 20.0]


def test_open_interest_absent_is_all_nan(data_dir: Path) -> None:
    aligned = open_interest_aligned(MKT, "NOPEUSDT", pd.Series([0, 1, 2]))
    assert aligned.isna().all()


# ── liquidation query + aggregation ──────────────────────────────────────────
async def test_query_and_aggregate_liquidations(
    db_session: AsyncSession, data_dir: Path
) -> None:
    """Events are readable and fold into per-minute buy/sell notional buckets (§25.3)."""
    minute = 60_000
    rows = [
        _liq_row("SELL", "1", "100", 0),          # long liquidated, bucket 0
        _liq_row("SELL", "2", "100", 30_000),     # same minute bucket 0
        _liq_row("BUY", "1", "200", minute + 5),  # short liquidated, bucket 1
    ]
    db_session.add_all([Liquidation(**r) for r in rows])
    await db_session.commit()

    events = await query_liquidations(db_session, MKT, SYM)
    assert len(events) == 3

    buckets = await aggregate_liquidations(db_session, MKT, SYM)
    assert buckets == 2  # two distinct minute buckets

    # Bar grid at 1-minute: bucket 0 sell = 100·1 + 100·2 = 300, bucket 1 buy = 200·1.
    buy, sell = liq_notional_aligned(MKT, SYM, pd.Series([0, minute]), minute)
    assert sell.tolist() == [300.0, 0.0]
    assert buy.tolist() == [0.0, 200.0]


async def test_liq_notional_sums_into_coarser_bars(
    db_session: AsyncSession, data_dir: Path
) -> None:
    """Minute buckets sum into a coarser (e.g. 5-min) requested bar (§25.3)."""
    minute = 60_000
    db_session.add_all(
        [
            Liquidation(**_liq_row("SELL", "1", "100", 0)),
            Liquidation(**_liq_row("SELL", "1", "100", 2 * minute)),  # same 5-min bar
        ]
    )
    await db_session.commit()
    await aggregate_liquidations(db_session, MKT, SYM)

    buy, sell = liq_notional_aligned(MKT, SYM, pd.Series([0, 5 * minute]), 5 * minute)
    assert sell.tolist() == [200.0, 0.0]  # both minute buckets fall in the first 5-min bar
    assert buy.tolist() == [0.0, 0.0]


async def test_aggregate_no_events_writes_nothing(
    db_session: AsyncSession, data_dir: Path
) -> None:
    assert await aggregate_liquidations(db_session, MKT, "EMPTYUSDT") == 0
    buy, sell = liq_notional_aligned(MKT, "EMPTYUSDT", pd.Series([0, 60_000]), 60_000)
    assert buy.tolist() == [0.0, 0.0]
    assert sell.tolist() == [0.0, 0.0]
