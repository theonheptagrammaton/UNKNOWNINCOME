"""Portföy kapısı RiskLayer içinde — strateji limitlerinden ÖNCE (doc §24, §24.7).

RiskLayer'a enjekte edilen :class:`PortfolioLimits`, strateji kapılarından önce
değerlendirilir; portföy reddi ``decision.events``'e düşer (bot bunu ``risk_events``'e
persistler — mevcut ``_evaluate`` yolu, test_bot_engine kapsamında).
"""

from __future__ import annotations

from app.execution.base import Balance, OrderResult, Position
from app.execution.risk import RiskLayer, RiskLimits, TradeIntent
from app.portfolio.limits import PortfolioLimits

DAY = 24 * 3600 * 1000


class StubAdapter:
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


def test_gross_leverage_over_3x_rejected_and_emits_event() -> None:
    """KABUL 4: brüt kaldıraç 3x'i aşacak emir reddedilir + risk_events; borsaya
    hiçbir emir gitmez."""
    existing = [Position(symbol="ETHUSDT", side="long", qty=280, entry_price=100, mark_price=100)]
    adapter = StubAdapter(positions=existing)  # 28_000 notional = 2.8x
    layer = RiskLayer(adapter, RiskLimits(), portfolio=PortfolioLimits(gross_leverage_cap=3.0))
    decision, result = layer.submit(_intent())  # +2_500 → 3.05x
    assert not decision.approved and result is None
    assert adapter.placed == []  # duvar emri geçirmedi
    assert any(e["type"] == "gross_leverage" for e in decision.events)


def test_portfolio_dd_kills_before_strategy_dd() -> None:
    """KABUL 3: portföy DD (%12) kill'i, strateji DD (%15) tetiklenmeden ateşler —
    portföy limiti strateji limitinden ÖNCE."""
    adapter = StubAdapter(equity=8_700.0)  # 13% down from a 10k peak
    layer = RiskLayer(
        adapter, RiskLimits(max_total_drawdown_pct=15.0),
        portfolio=PortfolioLimits(max_dd_pct=12.0),
    )
    layer.seed_state(peak_equity=10_000.0)
    decision = layer.evaluate(_intent())
    assert not decision.approved and decision.kill
    types = {e["type"] for e in decision.events}
    assert "portfolio_drawdown" in types
    assert "max_drawdown" not in types  # strateji DD ateşlemedi (13% < 15%)


def test_portfolio_gate_absent_preserves_legacy_behaviour() -> None:
    """portfolio=None ⇒ portföy kapısı yok (Faz-10 öncesi davranış korunur)."""
    layer = RiskLayer(StubAdapter(), RiskLimits())
    decision = layer.evaluate(_intent())
    assert decision.approved  # portföy kapısı devrede değil
