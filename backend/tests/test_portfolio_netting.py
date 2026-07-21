"""Sembol netleştirme + PnL atfı (doc §24.4, §24.7 kabul kriteri 2)."""

from __future__ import annotations

import pytest

from app.portfolio.netting import Leg, attribute_pnl, net_by_symbol, net_position


def test_two_strategies_same_symbol_and_side_net_to_one_position() -> None:
    """İki strateji aynı sembolde aynı yönde → TEK pozisyon, risk BİR KEZ (doc §24.4)."""
    legs = [
        Leg("stratA", "BTCUSDT", "long", 1000.0),
        Leg("stratB", "BTCUSDT", "long", 3000.0),
    ]
    nets = net_by_symbol(legs)
    assert set(nets) == {"BTCUSDT"}  # borsada tek sembol pozisyonu
    net = nets["BTCUSDT"]
    assert net.net_side == "long"
    # Risk bir kez: net maruziyet 4000 (1000+3000), 8000 değil.
    assert net.net_notional == pytest.approx(4000.0)
    assert net.gross_notional == pytest.approx(4000.0)


def test_pnl_attributed_proportionally() -> None:
    """Netleştirilmiş pozisyonun PnL'i bacaklara orantılı atfedilir (doc §24.4)."""
    legs = [
        Leg("stratA", "BTCUSDT", "long", 1000.0),
        Leg("stratB", "BTCUSDT", "long", 3000.0),
    ]
    attr = attribute_pnl(400.0, legs)
    assert attr["stratA"] == pytest.approx(100.0)  # 1000/4000 payı
    assert attr["stratB"] == pytest.approx(300.0)  # 3000/4000 payı
    assert sum(attr.values()) == pytest.approx(400.0)  # toplam korunur


def test_single_strategy_gets_full_pnl() -> None:
    attr = attribute_pnl(250.0, [Leg("solo", "ETHUSDT", "long", 500.0)])
    assert attr == {"solo": pytest.approx(250.0)}


def test_opposite_sides_net_down() -> None:
    """Ters yönlü bacaklar net maruziyeti düşürür (tam hedge ⇒ flat)."""
    legs = [
        Leg("stratA", "BTCUSDT", "long", 2000.0),
        Leg("stratB", "BTCUSDT", "short", 500.0),
    ]
    net = net_position(legs)
    assert net.net_side == "long"
    assert net.net_notional == pytest.approx(1500.0)  # 2000 − 500
    assert net.gross_notional == pytest.approx(2500.0)
