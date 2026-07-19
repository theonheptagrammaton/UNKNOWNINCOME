"""Operator CLI for Phase 1 data operations.

Examples:
    python -m app.data.cli universe
    python -m app.data.cli backfill --symbols BTCUSDT ETHUSDT --months 24
    python -m app.data.cli backfill              # top-10 of latest universe
    python -m app.data.cli status
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal, init_models


async def _universe(size: int) -> None:
    from app.data.adapters.binance_usdm import BinanceUsdmAdapter
    from app.data.universe import build_universe

    await init_models()
    adapter = BinanceUsdmAdapter()
    try:
        async with SessionLocal() as session:
            snapshot = await build_universe(adapter, session, size=size)
            print(f"universe {snapshot.as_of_date}: {len(snapshot.symbols)} symbols")
            print(", ".join(snapshot.symbols))
    finally:
        await adapter.close()


async def _backfill(
    symbols: list[str] | None, timeframes: list[str], months: float, funding: bool
) -> None:
    from app.data.adapters.binance_usdm import BinanceUsdmAdapter
    from app.data.sync import resolve_market_infos, sync_symbol
    from app.data.universe import latest_universe_symbols

    await init_models()
    adapter = BinanceUsdmAdapter()
    try:
        async with SessionLocal() as session:
            if not symbols:
                symbols = (await latest_universe_symbols(session, adapter.market))[:10]
            infos = await resolve_market_infos(adapter, symbols)
            print(
                f"backfilling {len(infos)} symbols × {len(timeframes)} tf × "
                f"{months}mo (funding={funding})"
            )
            for info in infos:
                results = await sync_symbol(
                    adapter,
                    session,
                    info,
                    timeframes,
                    months,
                    funding,
                    settings.ohlcv_fetch_limit,
                )
                for r in results:
                    print(f"  {r.symbol} {r.tf}: rows={r.total_rows} missing={r.residual_missing}")
    finally:
        await adapter.close()


async def _devseed(symbols: list[str], tf: str, bars: int, seed: int) -> None:
    """Write deterministic *synthetic* OHLCV + funding for local/UI verification.

    This is NOT market data — it is a self-contained fixture so a backtest can be
    run end-to-end without the 24-month Binance backfill (that stays the operator
    plan-B, docs/RUNBOOK-faz1-veri.md). The series is trend + cycle + noise so
    EMA crosses (and thus trades) occur.
    """
    from datetime import UTC, datetime

    import numpy as np
    import pandas as pd

    from app.data.parquet_store import ohlcv_rows_to_frame, write_funding, write_ohlcv
    from app.data.timeframes import FUNDING_INTERVAL_MS, tf_to_ms
    from app.models.market import CandleSyncState

    await init_models()
    step = tf_to_ms(tf)
    now = int(datetime.now(UTC).timestamp() * 1000)
    end = (now // step) * step - step  # last fully closed bar
    start = end - (bars - 1) * step

    async with SessionLocal() as session:
        for si, symbol in enumerate(symbols):
            rng = np.random.default_rng(seed + si)
            drift = np.cumsum(rng.standard_normal(bars)) * 0.5
            cycle = np.sin(np.linspace(0, 12 * np.pi, bars)) * 15
            close = 100.0 + drift + cycle
            close = np.abs(close) + 10.0
            rows: list[list[float]] = []
            for i in range(bars):
                c = float(close[i])
                o = c + float(rng.standard_normal()) * 0.3
                h = max(o, c) + abs(float(rng.standard_normal())) * 0.5
                low = min(o, c) - abs(float(rng.standard_normal())) * 0.5
                v = float(rng.random()) * 1000 + 100
                rows.append([start + i * step, o, h, low, c, v])
            n = write_ohlcv(settings.market, symbol, tf, ohlcv_rows_to_frame(rows))

            f_rows: list[dict] = []
            f = ((start // FUNDING_INTERVAL_MS) + 1) * FUNDING_INTERVAL_MS
            while f <= end:
                f_rows.append({"ts": f, "funding_rate": float(rng.normal(1e-4, 3e-4))})
                f += FUNDING_INTERVAL_MS
            write_funding(
                settings.market, symbol,
                pd.DataFrame(f_rows, columns=["ts", "funding_rate"]),
            )

            existing = (
                await session.execute(
                    select(CandleSyncState).where(
                        CandleSyncState.market == settings.market,
                        CandleSyncState.symbol == symbol,
                        CandleSyncState.tf == tf,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.first_ts, existing.last_ts, existing.gaps = start, end, []
            else:
                session.add(
                    CandleSyncState(
                        market=settings.market, symbol=symbol, tf=tf,
                        first_ts=start, last_ts=end, gaps=[],
                    )
                )
            print(f"devseed {symbol} {tf}: {n} bars, {len(f_rows)} funding rows (SYNTHETIC)")
        await session.commit()


async def _status() -> None:
    from app.data.duckdb_query import count_ohlcv
    from app.models.market import CandleSyncState

    await init_models()
    async with SessionLocal() as session:
        stmt = select(CandleSyncState).order_by(CandleSyncState.symbol, CandleSyncState.tf)
        rows = (await session.execute(stmt)).scalars().all()
        for r in rows:
            rows_n = count_ohlcv(r.market, r.symbol, r.tf)
            print(
                f"{r.symbol} {r.tf}: rows={rows_n} gaps={len(r.gaps or [])} "
                f"first={r.first_ts} last={r.last_ts}"
            )
        print(f"total series: {len(rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.data.cli", description="UNKNOWNINCOME data ops")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_uni = sub.add_parser("universe", help="build the dynamic universe + dated snapshot")
    p_uni.add_argument("--size", type=int, default=settings.universe_size)

    p_bf = sub.add_parser("backfill", help="download OHLCV (+ funding) history")
    p_bf.add_argument("--symbols", nargs="*", default=None)
    p_bf.add_argument("--timeframes", nargs="*", default=settings.default_timeframes)
    p_bf.add_argument("--months", type=float, default=settings.default_lookback_months)
    p_bf.add_argument("--no-funding", action="store_true", help="skip funding history")

    sub.add_parser("status", help="print coverage per symbol × timeframe")

    p_seed = sub.add_parser("devseed", help="write SYNTHETIC data for local/UI verification")
    p_seed.add_argument("--symbols", nargs="*", default=["BTCUSDT"])
    p_seed.add_argument("--tf", default="1h")
    p_seed.add_argument("--bars", type=int, default=1500)
    p_seed.add_argument("--seed", type=int, default=7)

    args = parser.parse_args()
    if args.cmd == "universe":
        asyncio.run(_universe(args.size))
    elif args.cmd == "backfill":
        asyncio.run(_backfill(args.symbols, args.timeframes, args.months, not args.no_funding))
    elif args.cmd == "status":
        asyncio.run(_status())
    elif args.cmd == "devseed":
        asyncio.run(_devseed(args.symbols, args.tf, args.bars, args.seed))


if __name__ == "__main__":
    main()
