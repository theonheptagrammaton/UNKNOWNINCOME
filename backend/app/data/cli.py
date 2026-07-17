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

    args = parser.parse_args()
    if args.cmd == "universe":
        asyncio.run(_universe(args.size))
    elif args.cmd == "backfill":
        asyncio.run(_backfill(args.symbols, args.timeframes, args.months, not args.no_funding))
    elif args.cmd == "status":
        asyncio.run(_status())


if __name__ == "__main__":
    main()
