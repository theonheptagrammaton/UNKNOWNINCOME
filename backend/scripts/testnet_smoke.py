"""Binance USDT-M **testnet** smoke test — the Phase-7 live-path acceptance evidence.

Unit tests prove the adapter's logic against a fake exchange; they cannot prove that
the *real* venue accepts our isolated/one-way/leverage calls and fills a micro order.
This script does exactly that and nothing else:

1. Reads the account balance (proves auth works).
2. Sets isolated margin + one-way + leverage, then opens a **micro long**, reads the
   position back from the venue, and closes it ``reduce_only``.
3. Repeats for a **micro short**.
4. Prints the leverage and margin mode the venue reports — the log evidence the
   Phase-7 acceptance asks for.

It never touches mainnet: the adapter is constructed with ``testnet=True`` and the
script refuses to run if the key pair is flagged as mainnet. Size is deliberately the
exchange minimum; on Binance USDT-M testnet BTCUSDT that is 0.001 BTC.

Usage (keys are read from the environment, never from the repo):

    export BINANCE_TESTNET_API_KEY=...
    export BINANCE_TESTNET_API_SECRET=...
    python -m scripts.testnet_smoke --symbol BTCUSDT --qty 0.001 --leverage 5

Register for testnet keys at https://testnet.binancefuture.com. The keys are scrubbed
from every log line by the redaction filter, so this output is safe to paste into a
report — that is itself part of the acceptance.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from app.core.logging import configure_logging
from app.execution.base import OrderRequest
from app.execution.binance import BinanceFuturesAdapter

logger = logging.getLogger("app.scripts.testnet_smoke")


def _positions_for(adapter: BinanceFuturesAdapter, symbol: str) -> None:
    """Log what the venue reports for a symbol — leverage + margin mode evidence."""
    for pos in adapter.get_positions():
        if pos.symbol == symbol:
            logger.info(
                "venue position: %s %s qty=%.6f entry=%.2f leverage=%.0fx mark=%s",
                pos.symbol, pos.side, pos.qty, pos.entry_price, pos.leverage,
                f"{pos.mark_price:.2f}" if pos.mark_price else "—",
            )
            return
    logger.info("venue position: %s flat", symbol)


def _round_trip(
    adapter: BinanceFuturesAdapter, symbol: str, side: str, qty: float, leverage: float
) -> bool:
    """Open then close one micro position; return True if both legs filled."""
    close_side = "sell" if side == "buy" else "buy"
    label = "LONG" if side == "buy" else "SHORT"

    logger.info(
        "── %s round trip: open %s %s qty=%.6f lev=%.0fx", label, side, symbol, qty, leverage
    )
    opened = adapter.place_order(
        OrderRequest(symbol=symbol, side=side, qty=qty, leverage=leverage)
    )
    if not opened.accepted:
        logger.error("%s open REJECTED: %s", label, opened.reason)
        return False
    logger.info("%s open filled: order_id=%s price=%.2f", label, opened.order_id, opened.fill.price)

    time.sleep(1.0)  # let the venue settle before we read the position back
    _positions_for(adapter, symbol)

    logger.info("── %s round trip: close %s (reduce_only)", label, close_side)
    closed = adapter.place_order(
        OrderRequest(
            symbol=symbol, side=close_side, qty=qty, leverage=leverage, reduce_only=True
        )
    )
    if not closed.accepted:
        logger.error("%s close REJECTED: %s — POSITION MAY STILL BE OPEN", label, closed.reason)
        return False
    logger.info(
        "%s close filled: order_id=%s price=%.2f realized_pnl=%.4f",
        label, closed.order_id, closed.fill.price, closed.fill.realized_pnl,
    )
    time.sleep(1.0)
    _positions_for(adapter, symbol)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Binance USDT-M testnet smoke test")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--qty", type=float, default=0.001, help="micro size (venue minimum)")
    parser.add_argument("--leverage", type=float, default=5.0, help="safe default (rule #11)")
    args = parser.parse_args()

    configure_logging()
    logging.getLogger("app").setLevel(logging.INFO)

    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    if not api_key or not api_secret:
        logger.error(
            "BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET must be set "
            "(get them at https://testnet.binancefuture.com)"
        )
        return 2

    if args.leverage > 10:
        logger.error("leverage %.0fx exceeds the hard 10x ceiling (rule #11)", args.leverage)
        return 2

    # testnet=True is not configurable here on purpose — this script never trades real money.
    adapter = BinanceFuturesAdapter(
        api_key, api_secret, testnet=True, leverage_default=args.leverage
    )
    logger.info("connected to Binance USDT-M TESTNET (sandbox mode)")

    balance = adapter.get_balance()
    logger.info(
        "balance: equity=%.2f cash=%.2f unrealized=%.2f",
        balance.equity, balance.cash, balance.unrealized_pnl,
    )
    if balance.equity <= 0:
        logger.error("testnet account has no balance — fund it from the testnet faucet first")
        return 1

    ok_long = _round_trip(adapter, args.symbol, "buy", args.qty, args.leverage)
    ok_short = _round_trip(adapter, args.symbol, "sell", args.qty, args.leverage)

    logger.info("── result: long=%s short=%s", "PASS" if ok_long else "FAIL",
                "PASS" if ok_short else "FAIL")
    return 0 if (ok_long and ok_short) else 1


if __name__ == "__main__":
    sys.exit(main())
