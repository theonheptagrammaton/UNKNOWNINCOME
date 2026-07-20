"""The risk wall enforces every §9.4 limit and can never be bypassed."""

from __future__ import annotations

from app.execution.base import Balance, OrderResult, Position
from app.execution.risk import RiskLayer, RiskLimits, TradeIntent

DAY = 24 * 3600 * 1000


class StubAdapter:
    """Minimal adapter for exercising the wall in isolation."""

    mode = "paper"

    def __init__(self, equity=10_000.0, positions=None) -> None:
        self.equity = equity
        self._positions = positions or []
        self.placed: list = []

    def get_balance(self) -> Balance:
        return Balance(equity=self.equity, cash=self.equity, unrealized_pnl=0.0)

    def get_positions(self) -> list[Position]:
        return list(self._positions)

    def place_order(self, order) -> OrderResult:
        self.placed.append(order)
        return OrderResult(accepted=True, order_id="stub", status="filled")

    def cancel_all(self) -> int:
        return 0


def _intent(**kw) -> TradeIntent:
    base = dict(
        strategy_version_id="v1", symbol="BTCUSDT", action="open_long",
        reference_price=100.0, ts=DAY, atr=2.0, leverage=5.0,
    )
    base.update(kw)
    return TradeIntent(**base)


def test_no_bypass_adapter_is_private() -> None:
    """The adapter is name-mangled private; the bot cannot reach place_order (doc §9.4)."""
    layer = RiskLayer(StubAdapter())
    assert not hasattr(layer, "adapter")
    assert not hasattr(layer, "_adapter")
    # It exists only under the mangled name, unreachable by ordinary attribute access.
    assert "_RiskLayer__adapter" in vars(layer)


def test_atr_sizing_positive_and_capped() -> None:
    layer = RiskLayer(StubAdapter(equity=10_000), RiskLimits(per_trade_pct=1.0))
    d = layer.evaluate(_intent(atr=2.0))
    assert d.approved and d.qty > 0
    # risk 100 / stop (2×ATR=4) = 25 coins; but margin cap = equity×lev/price = 500 → 25 wins.
    assert abs(d.qty - 25.0) < 1e-6


def test_max_concurrent_positions_blocks_and_emits() -> None:
    positions = [Position(symbol=f"S{i}", side="long", qty=1, entry_price=1) for i in range(5)]
    layer = RiskLayer(StubAdapter(positions=positions), RiskLimits(max_concurrent_positions=5))
    d = layer.evaluate(_intent(symbol="NEWUSDT"))
    assert not d.approved
    assert any(e["type"] == "max_positions" for e in d.events)


def test_daily_loss_halts_the_day() -> None:
    ad = StubAdapter(equity=10_000)
    layer = RiskLayer(ad, RiskLimits(max_daily_loss_pct=3.0))
    layer.evaluate(_intent(ts=DAY))  # anchors the day at 10_000
    ad.equity = 9_600  # −4% intraday
    d = layer.evaluate(_intent(ts=DAY + 3600_000))
    assert not d.approved and any(e["type"] == "daily_loss" for e in d.events)


def test_total_drawdown_requests_kill() -> None:
    ad = StubAdapter(equity=10_000)
    layer = RiskLayer(ad, RiskLimits(max_total_drawdown_pct=15.0))
    layer.evaluate(_intent(ts=DAY))  # sets peak 10_000
    ad.equity = 8_000  # −20% from peak
    d = layer.evaluate(_intent(ts=DAY + 3600_000))
    assert not d.approved and d.kill
    assert any(e["type"] == "max_drawdown" for e in d.events)


def test_price_deviation_guard() -> None:
    layer = RiskLayer(StubAdapter(), RiskLimits(price_deviation_pct=1.0))
    d = layer.evaluate(_intent(reference_price=105.0, last_price=100.0))  # +5%
    assert not d.approved and any(e["type"] == "price_guard" for e in d.events)


def test_cooldown_after_consecutive_losses() -> None:
    layer = RiskLayer(StubAdapter(), RiskLimits(consecutive_losses=4, cooldown_hours=12))
    for _ in range(4):
        layer.register_trade_result(-1.0, DAY)
    d = layer.evaluate(_intent(ts=DAY + 3600_000))  # within 12h window
    assert not d.approved and any(e["type"] == "cooldown" for e in d.events)


def test_liquidation_buffer_auto_delevers() -> None:
    # High requested leverage + wide ATR ⇒ liq too close ⇒ auto de-lever (rule #11).
    layer = RiskLayer(StubAdapter(), RiskLimits(leverage_cap=10.0, liq_buffer_atr_mult=3.0))
    d = layer.evaluate(_intent(leverage=10.0, atr=5.0, reference_price=100.0))
    assert d.approved
    assert d.leverage < 10.0
    assert any(e["type"] == "liq_buffer" for e in d.events)


def test_closing_intent_always_allowed() -> None:
    pos = [Position(symbol="BTCUSDT", side="long", qty=3.0, entry_price=100.0)]
    layer = RiskLayer(StubAdapter(positions=pos), RiskLimits(max_concurrent_positions=0))
    d = layer.evaluate(_intent(action="close_long"))
    assert d.approved and d.qty == 3.0  # closes the whole position despite the 0 cap


def test_submit_places_only_when_approved() -> None:
    ad = StubAdapter()
    layer = RiskLayer(ad, RiskLimits(price_deviation_pct=1.0))
    decision, result = layer.submit(_intent(reference_price=200.0, last_price=100.0))
    assert not decision.approved and result is None
    assert ad.placed == []  # nothing reached the adapter
