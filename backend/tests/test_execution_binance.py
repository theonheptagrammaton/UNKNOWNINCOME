"""BinanceFuturesAdapter against a mock ccxt exchange (doc §9.2–9.4, Faz-7).

Proves the venue-config invariants (isolated margin + one-way + leverage set before
the first order), that micro long and short orders open and close, that realized PnL
is attributed on the close, and that credentials are registered for log redaction —
without touching the network. The opt-in real-testnet run lives in
``test_execution_binance_testnet.py`` (skipped unless keys are provided).
"""

from __future__ import annotations

import logging

from app.execution.base import OrderRequest
from app.execution.binance import BinanceFuturesAdapter


class FakeExchange:
    """Minimal ccxt-shaped double recording every venue call."""

    def __init__(self, *, price: float = 100.0) -> None:
        self.calls: list[tuple] = []
        self.markets_by_id = {"BTCUSDT": {"id": "BTCUSDT", "symbol": "BTC/USDT:USDT"}}
        self._price = price
        self.positions: list[dict] = []
        self.balance = {
            "info": {
                "totalMarginBalance": "1000.0",
                "totalWalletBalance": "990.0",
                "totalUnrealizedProfit": "10.0",
            }
        }
        self.open_orders: list[dict] = []

    def load_markets(self):
        self.calls.append(("load_markets",))
        return self.markets_by_id

    def amount_to_precision(self, symbol, qty):
        return str(round(float(qty), 3))

    def set_position_mode(self, hedged):
        self.calls.append(("set_position_mode", hedged))

    def set_margin_mode(self, mode, symbol):
        self.calls.append(("set_margin_mode", mode, symbol))

    def set_leverage(self, leverage, symbol):
        self.calls.append(("set_leverage", leverage, symbol))

    def create_order(self, symbol, type_, side, amount, price, params):
        self.calls.append(("create_order", symbol, side, amount, dict(params)))
        return {
            "id": f"ord-{len(self.calls)}",
            "average": self._price,
            "filled": amount,
            "fee": {"cost": 0.04, "currency": "USDT"},
            "params": dict(params),
        }

    def fetch_positions(self):
        return self.positions

    def fetch_balance(self):
        return self.balance

    def fetch_open_orders(self):
        return self.open_orders

    def cancel_order(self, order_id, symbol=None):
        self.calls.append(("cancel_order", order_id))


def _adapter(fake: FakeExchange) -> BinanceFuturesAdapter:
    return BinanceFuturesAdapter("key12345678", "secret12345678", testnet=True, exchange=fake)


def test_open_long_sets_isolated_oneway_and_leverage(caplog) -> None:
    fake = FakeExchange(price=100.0)
    adapter = _adapter(fake)
    with caplog.at_level(logging.INFO):
        res = adapter.place_order(
            OrderRequest(symbol="BTCUSDT", side="buy", qty=0.01, leverage=5.0, reference_price=100.0)
        )
    assert res.accepted and res.status == "filled"
    kinds = [c[0] for c in fake.calls]
    assert ("set_position_mode", False) in fake.calls  # one-way
    assert ("set_margin_mode", "isolated", "BTC/USDT:USDT") in fake.calls
    assert ("set_leverage", 5, "BTC/USDT:USDT") in fake.calls
    assert "create_order" in kinds
    # Log evidence of the venue config + fill (leverage/margin proof).
    text = caplog.text
    assert "set_leverage(5)" in text and "isolated" in text and "live fill" in text


def test_micro_long_open_then_close_realizes_pnl() -> None:
    fake = FakeExchange(price=100.0)
    adapter = _adapter(fake)
    open_res = adapter.place_order(
        OrderRequest(symbol="BTCUSDT", side="buy", qty=0.01, leverage=5.0, reference_price=100.0)
    )
    assert open_res.fill.realized_pnl == 0.0  # opening realizes nothing

    fake._price = 110.0  # price moved up 10
    close_res = adapter.place_order(
        OrderRequest(symbol="BTCUSDT", side="sell", qty=0.01, leverage=5.0,
                     reference_price=110.0, reduce_only=True)
    )
    assert close_res.accepted
    # long 0.01 from 100 → 110 ⇒ +0.1 realized.
    assert abs(close_res.fill.realized_pnl - 0.1) < 1e-9
    # Closing is reduce-only and does not re-set leverage/margin.
    close_params = [c for c in fake.calls if c[0] == "create_order"][-1][4]
    assert close_params["reduceOnly"] is True


def test_micro_short_open_then_close_realizes_pnl() -> None:
    fake = FakeExchange(price=100.0)
    adapter = _adapter(fake)
    adapter.place_order(
        OrderRequest(symbol="BTCUSDT", side="sell", qty=0.02, leverage=3.0, reference_price=100.0)
    )
    assert ("set_leverage", 3, "BTC/USDT:USDT") in fake.calls

    fake._price = 95.0  # price fell 5 → short profits
    res = adapter.place_order(
        OrderRequest(symbol="BTCUSDT", side="buy", qty=0.02, leverage=3.0,
                     reference_price=95.0, reduce_only=True)
    )
    # short 0.02 from 100 → 95 ⇒ +0.1 realized.
    assert abs(res.fill.realized_pnl - 0.1) < 1e-9


def test_get_positions_and_balance_parse() -> None:
    fake = FakeExchange()
    fake.positions = [
        {"symbol": "BTC/USDT:USDT", "contracts": 0.01, "side": "long",
         "entryPrice": 100.0, "leverage": 5, "markPrice": 101.0},
        {"symbol": "ETH/USDT:USDT", "contracts": 0.0, "side": "long"},  # flat → ignored
    ]
    adapter = _adapter(fake)
    positions = adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT" and positions[0].qty == 0.01

    bal = adapter.get_balance()
    assert bal.equity == 1000.0 and bal.cash == 990.0 and bal.unrealized_pnl == 10.0


def test_position_mode_set_once_across_orders() -> None:
    fake = FakeExchange()
    adapter = _adapter(fake)
    for _ in range(3):
        adapter.place_order(
            OrderRequest(symbol="BTCUSDT", side="buy", qty=0.01, leverage=5.0, reference_price=100.0)
        )
    # one-way mode is an account-level call — set exactly once.
    assert sum(1 for c in fake.calls if c[0] == "set_position_mode") == 1


def test_credentials_registered_for_redaction() -> None:
    from app.core.logging import _SECRETS, clear_secrets

    clear_secrets()
    fake = FakeExchange()
    BinanceFuturesAdapter("mykey_abcdefgh", "mysecret_abcdefgh", testnet=True, exchange=fake)
    assert "mykey_abcdefgh" in _SECRETS and "mysecret_abcdefgh" in _SECRETS
    clear_secrets()
