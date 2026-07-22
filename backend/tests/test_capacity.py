"""Capacity & participation (doc §26.2): the ratio maths, the strategy-card estimate,
and the risk wall rejecting any order over 1% of the signal-bar volume (KABUL #2)."""

from __future__ import annotations

from app.execution.base import Balance, OrderResult, Position
from app.execution.capacity import (
    capacity_from_samples,
    capacity_usd,
    exceeds_cap,
    participation,
)
from app.execution.risk import RiskLayer, RiskLimits, TradeIntent

DAY = 24 * 3600 * 1000


class StubAdapter:
    mode = "paper"

    def __init__(self, equity=10_000.0) -> None:
        self.equity = equity
        self.placed: list = []

    def get_balance(self) -> Balance:
        return Balance(equity=self.equity, cash=self.equity, unrealized_pnl=0.0)

    def get_positions(self) -> list[Position]:
        return []

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


# ── pure maths ────────────────────────────────────────────────────────────────
def test_participation_and_cap() -> None:
    assert participation(10.0, 1_000.0) == 0.01  # 1%
    assert participation(5.0, 0.0) is None  # unknown volume
    assert exceeds_cap(30.0, 1_000.0, cap_pct=1.0)  # 3% > 1%
    assert not exceeds_cap(5.0, 1_000.0, cap_pct=1.0)  # 0.5% ≤ 1%
    assert not exceeds_cap(30.0, 0.0, cap_pct=1.0)  # unknown volume ⇒ allowed


def test_capacity_usd_scales_with_cap() -> None:
    # At equity 10k an order of 25 coins is 1% of a 2,500-coin bar → already at the cap,
    # so capacity ≈ current equity.
    cap = capacity_usd(10_000.0, 25.0, 2_500.0, 100.0, cap_pct=1.0)
    assert cap is not None and abs(cap - 10_000.0) < 1e-6
    # Half the participation ⇒ double the carriable capital.
    cap2 = capacity_usd(10_000.0, 12.5, 2_500.0, 100.0, cap_pct=1.0)
    assert cap2 is not None and abs(cap2 - 20_000.0) < 1e-6
    assert capacity_usd(10_000.0, 5.0, 0.0, 100.0) is None


def test_capacity_from_samples_uses_median() -> None:
    samples = [(10.0, 1_000.0), (20.0, 1_000.0), (30.0, 1_000.0)]  # 1%, 2%, 3% → median 2%
    est = capacity_from_samples(10_000.0, samples, cap_pct=1.0)
    assert est is not None and abs(est - 5_000.0) < 1e-6  # 10k × 1% / 2%
    assert capacity_from_samples(10_000.0, [], cap_pct=1.0) is None


# ── risk-wall gate (KABUL #2) ─────────────────────────────────────────────────
def test_order_over_participation_cap_rejected_and_emits() -> None:
    # qty = risk 100 / stop 4 = 25 coins (as in test_execution_risk). Bar volume 1,000 ⇒
    # participation 2.5% > 1% cap → rejected with a capacity risk_event.
    layer = RiskLayer(StubAdapter(equity=10_000), RiskLimits(per_trade_pct=1.0))
    d = layer.evaluate(_intent(bar_volume=1_000.0))
    assert not d.approved
    ev = next(e for e in d.events if e["type"] == "capacity")
    assert ev["detail"]["cap_pct"] == 1.0
    assert ev["detail"]["participation_pct"] > 1.0


def test_order_within_cap_approved() -> None:
    layer = RiskLayer(StubAdapter(equity=10_000), RiskLimits(per_trade_pct=1.0))
    d = layer.evaluate(_intent(bar_volume=1_000_000.0))  # 25/1e6 = 0.0025%
    assert d.approved and d.qty > 0
    assert not any(e["type"] == "capacity" for e in d.events)


def test_missing_volume_does_not_gate() -> None:
    layer = RiskLayer(StubAdapter(equity=10_000), RiskLimits(per_trade_pct=1.0))
    d = layer.evaluate(_intent(bar_volume=None))  # unknown volume ⇒ gate skipped
    assert d.approved


def test_capacity_gate_blocks_the_order_via_submit() -> None:
    ad = StubAdapter(equity=10_000)
    layer = RiskLayer(ad, RiskLimits(per_trade_pct=1.0))
    decision, result = layer.submit(_intent(bar_volume=1_000.0))
    assert not decision.approved and result is None
    assert ad.placed == []  # the order never reached the adapter
