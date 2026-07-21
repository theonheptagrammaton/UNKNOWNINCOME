"""Portföy düzeyi limitler (doc §24.5, §24.7 kabul kriterleri 3–5)."""

from __future__ import annotations

from app.portfolio.limits import (
    AddedLeg,
    PortfolioLimits,
    PortfolioPosition,
    PortfolioSnapshot,
    check_drawdown,
    check_open,
    warnings,
)

TS = 1_700_000_000_000


def _snap(equity=10_000.0, peak=10_000.0, day_start=10_000.0, positions=None, active=1):
    return PortfolioSnapshot(
        equity=equity, peak_equity=peak, day_start_equity=day_start,
        positions=positions or [], active_strategies=active,
    )


def test_portfolio_dd_trips_while_no_strategy_breaches_its_own_limit() -> None:
    """KABUL 3: portföy DD (%12) tetiklenir, strateji DD (%15) aşılmamışken."""
    limits = PortfolioLimits(max_dd_pct=12.0)
    # Equity 13% down: portfolio 12% breaches, strategy 15% would NOT.
    dec = check_drawdown(limits, _snap(equity=8_700.0, peak=10_000.0), TS)
    assert dec is not None and not dec.approved and dec.kill
    assert dec.events[0]["type"] == "portfolio_drawdown"
    # 10% down: neither limit breaches.
    assert check_drawdown(limits, _snap(equity=9_000.0, peak=10_000.0), TS) is None


def test_gross_leverage_over_3x_is_rejected() -> None:
    """KABUL 4: brüt kaldıraç 3x'i aşacak emir reddedilir + olay üretir."""
    limits = PortfolioLimits(gross_leverage_cap=3.0)
    existing = [PortfolioPosition("ETHUSDT", "long", 28_000.0)]  # 2.8x
    added = AddedLeg("BTCUSDT", "long", 2_500.0)  # → 3.05x
    dec = check_open(limits, _snap(positions=existing), added, TS)
    assert not dec.approved
    assert any(e["type"] == "gross_leverage" for e in dec.events)


def test_symbol_exposure_over_35pct_is_rejected() -> None:
    limits = PortfolioLimits()
    added = AddedLeg("BTCUSDT", "long", 4_000.0)  # 40% of 10k equity
    dec = check_open(limits, _snap(), added, TS)
    assert not dec.approved
    assert dec.events[0]["type"] == "symbol_exposure"


def test_portfolio_daily_loss_halts_new_entries() -> None:
    limits = PortfolioLimits(daily_loss_pct=3.0)
    snap = _snap(equity=9_600.0, day_start=10_000.0)  # −4% on the day
    dec = check_open(limits, snap, AddedLeg("BTCUSDT", "long", 1_000.0), TS)
    assert not dec.approved
    assert dec.events[0]["type"] == "portfolio_daily_loss"


def test_direction_concentration_restricts_same_side_only() -> None:
    """Net yönlü > %60 ⇒ aynı-yön girişi kısıtlanır; ters yön (çeşitlendirme) serbest."""
    limits = PortfolioLimits(direction_concentration_pct=60.0)
    snap = _snap(positions=[PortfolioPosition("ETHUSDT", "long", 5_800.0)])  # 58% net long
    # Add long → 68% net long → restricted.
    long_add = check_open(limits, snap, AddedLeg("BTCUSDT", "long", 1_000.0), TS)
    assert not long_add.approved
    assert long_add.events[0]["type"] == "direction_concentration"
    # Add short → nets down → allowed.
    short_add = check_open(limits, snap, AddedLeg("BTCUSDT", "short", 1_000.0), TS)
    assert short_add.approved


def test_first_position_is_not_blocked_by_concentration() -> None:
    """İlk pozisyon 'tek yön' diye bloke olmaz (net yönlü/equity ölçülür)."""
    dec = check_open(PortfolioLimits(), _snap(), AddedLeg("BTCUSDT", "long", 2_000.0), TS)
    assert dec.approved


def test_active_strategy_band_is_warning_only() -> None:
    limits = PortfolioLimits(min_active=3, max_active=8)
    assert warnings(limits, _snap(active=1), TS)[0]["detail"]["issue"] == "under_diversified"
    assert warnings(limits, _snap(active=9), TS)[0]["detail"]["issue"] == "unmonitorable"
    assert warnings(limits, _snap(active=5), TS) == []  # band içinde uyarı yok
