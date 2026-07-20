"""Paper fill simulator: commission, slippage, netting pnl, funding (doc §9.1)."""

from __future__ import annotations

from app.execution.base import OrderRequest
from app.execution.paper import PaperAdapter


def _buy(symbol="BTCUSDT", qty=1.0, price=100.0, **kw):
    return OrderRequest(symbol=symbol, side="buy", qty=qty, reference_price=price, **kw)


def _sell(symbol="BTCUSDT", qty=1.0, price=100.0, **kw):
    return OrderRequest(symbol=symbol, side="sell", qty=qty, reference_price=price, **kw)


def test_slippage_and_commission_applied() -> None:
    ad = PaperAdapter(10_000, commission_bps=4.0, slippage_bps=5.0)
    res = ad.place_order(_buy(price=100.0))
    assert res.accepted and res.status == "filled"
    # Buy fills adversely high: 100 + 5bps = 100.05.
    assert abs(res.fill.price - 100.05) < 1e-9
    # Commission = 4bps × qty × fill.
    assert abs(res.fill.commission - 0.0004 * 1.0 * 100.05) < 1e-9
    bal = ad.get_balance()
    assert abs(bal.cash - (10_000 - res.fill.commission)) < 1e-9


def test_long_round_trip_realizes_pnl() -> None:
    ad = PaperAdapter(10_000, commission_bps=0.0, slippage_bps=0.0)
    ad.place_order(_buy(price=100.0))
    ad.mark("BTCUSDT", 110.0)
    assert abs(ad.get_balance().unrealized_pnl - 10.0) < 1e-9  # 1 × (110−100)
    res = ad.place_order(_sell(price=110.0))
    assert abs(res.fill.realized_pnl - 10.0) < 1e-9
    assert ad.get_positions() == []
    assert abs(ad.get_balance().equity - 10_010.0) < 1e-9


def test_short_round_trip_realizes_pnl() -> None:
    ad = PaperAdapter(10_000, commission_bps=0.0, slippage_bps=0.0)
    ad.place_order(_sell(price=100.0))  # open short
    res = ad.place_order(_buy(price=90.0))  # cover lower → profit
    assert abs(res.fill.realized_pnl - 10.0) < 1e-9  # short 1 × (100−90)
    assert ad.get_balance().equity > 10_000


def test_add_to_position_weighted_average_entry() -> None:
    ad = PaperAdapter(10_000, commission_bps=0.0, slippage_bps=0.0)
    ad.place_order(_buy(qty=1.0, price=100.0))
    ad.place_order(_buy(qty=1.0, price=120.0))
    pos = ad.get_positions()[0]
    assert pos.qty == 2.0
    assert abs(pos.entry_price - 110.0) < 1e-9


def test_funding_accrual_long_pays_positive_rate() -> None:
    ad = PaperAdapter(10_000, commission_bps=0.0, slippage_bps=0.0)
    ad.place_order(_buy(qty=1.0, price=100.0))
    pay = ad.accrue_funding("BTCUSDT", 0.0001)  # long pays when rate > 0
    assert pay < 0
    assert abs(pay - (-1.0 * 100.0 * 0.0001)) < 1e-9
    assert ad.get_balance().cash < 10_000


def test_per_order_cost_override() -> None:
    ad = PaperAdapter(10_000, commission_bps=4.0, slippage_bps=5.0)
    res = ad.place_order(_buy(price=100.0, commission_bps=0.0, slippage_bps=0.0))
    assert abs(res.fill.price - 100.0) < 1e-9  # override → no slippage
    assert res.fill.commission == 0.0
