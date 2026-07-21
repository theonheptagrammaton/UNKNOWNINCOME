"""Portföy düzeyi risk limitleri (doc §24.5).

Bu limitler **strateji limitlerinden ÖNCE** değerlendirilir (doc §24, RiskLayer
entegrasyonu): portföy reddi de ``risk_events``'e gerekçesiyle düşer. Beş strateji
tek başına limitini aşmasa bile portföy bir arada aşabilir — portföy DD tavanı
(%12) strateji DD tavanından (%15) **sıkıdır** ve önce ateşler.

Saf değerlendirici: bir anlık portföy görüntüsü + eklenmek istenen bacak alır,
karar + olay listesi döndürür. I/O yok; olay kalıcılığı çağırana (bot) aittir —
tıpkı :class:`app.execution.risk.RiskLayer` gibi.

| Limit | Varsayılan | Aşılırsa |
|---|---|---|
| Portföy günlük zarar | %3 | tüm yeni girişler durur |
| Portföy toplam DD | %12 | kill switch (strateji %15'ten sıkı) |
| Net sembol maruziyeti | equity'nin %35'i | yeni giriş reddedilir |
| Brüt kaldıraç | 3x | yeni giriş reddedilir |
| Tek yön yoğunlaşması | net ≤ %60 | uyarı + yeni aynı-yön girişi kısıtlanır |
| Aktif strateji sayısı | 3–8 | dışında uyarı (yalnızca) |
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


class PortfolioLimits(BaseModel):
    """Portföy düzeyi limitler (doc §24.5). Varsayılanlar doküman varsayılanı.

    Yapısal tavanlar (net sembol %35, brüt kaldıraç 3x) doc §24.3'e göre
    pazarlıksızdır; burada varsayılan olarak sabittir, gevşetmek kaynak değişikliği
    ister (config yalnızca sıkabilir, çünkü etkin tavan ``min`` alınır)."""

    daily_loss_pct: float = 3.0  # → tüm yeni girişleri durdur
    max_dd_pct: float = 12.0  # → kill switch (strateji %15'ten sıkı)
    max_symbol_exposure_pct: float = 35.0  # net, equity'ye oran
    gross_leverage_cap: float = 3.0  # toplam notional / equity
    direction_concentration_pct: float = 60.0  # net long|short ≤ bu
    min_active: int = 3  # altında "çeşitlendirme yok" uyarısı
    max_active: int = 8  # üstünde "izlenemez" uyarısı


@dataclass
class PortfolioPosition:
    """Görüntüdeki tek netleştirilmiş pozisyon (adaptörden okunur)."""

    symbol: str
    side: str  # long | short
    notional: float  # abs notional (qty × mark), ≥ 0


@dataclass
class PortfolioSnapshot:
    """Bir tikteki portföy durumu — RiskLayer adaptörden kurar."""

    equity: float
    peak_equity: float
    day_start_equity: float
    positions: list[PortfolioPosition] = field(default_factory=list)
    active_strategies: int = 0


@dataclass
class AddedLeg:
    """Değerlendirilen açılış: eklenmek istenen maruziyet bacağı."""

    symbol: str
    side: str  # long | short
    notional: float  # abs notional (qty × fiyat)
    strategy_version_id: str | None = None


@dataclass
class PortfolioDecision:
    """Portföy kapısının verdiği karar + kalıcılaştırılacak olaylar."""

    approved: bool
    reason: str | None = None
    events: list[dict] = field(default_factory=list)
    kill: bool = False


def _ev(event_type: str, symbol: str | None, svid: str | None, detail: dict, ts: int) -> dict:
    """Bot'un persistleyeceği bir ``risk_event`` yükü (RiskLayer ile aynı şekil)."""
    return {
        "type": event_type,
        "symbol": symbol,
        "strategy_version_id": svid,
        "detail": detail,
        "ts": ts,
    }


def check_drawdown(
    limits: PortfolioLimits, snap: PortfolioSnapshot, ts: int
) -> PortfolioDecision | None:
    """Portföy DD (%12) — her niyet için, strateji DD'sinden ÖNCE (doc §24.5).

    Aşılırsa kill switch talep eder (``kill=True``); bu, strateji %15 tavanına
    varmadan ateşleyebilir. Aşılmazsa ``None`` (devam et).
    """
    if snap.peak_equity <= 0:
        return None
    dd = snap.equity / snap.peak_equity - 1.0
    if dd <= -limits.max_dd_pct / 100.0:
        ev = _ev("portfolio_drawdown", None, None, {
            "drawdown_pct": round(dd * 100, 4),
            "limit_pct": limits.max_dd_pct,
        }, ts)
        return PortfolioDecision(False, reason="portfolio drawdown", events=[ev], kill=True)
    return None


def check_open(
    limits: PortfolioLimits, snap: PortfolioSnapshot, added: AddedLeg, ts: int
) -> PortfolioDecision:
    """Açılış niyeti için portföy kapıları (doc §24.5), strateji kapılarından önce.

    Sıra: günlük zarar → sembol maruziyeti → brüt kaldıraç → yön yoğunlaşması.
    İlk aşılan reddeder ve olayı üretir. Aktif-strateji bandı yalnızca uyarıdır
    (reddetmez) ve ``warnings()`` ile ayrıca raporlanır.
    """
    svid = added.strategy_version_id
    eq = snap.equity if snap.equity > 0 else 1.0

    # Portföy günlük zarar → tüm yeni girişleri durdur (doc §24.5).
    if snap.day_start_equity > 0:
        day_pnl = snap.equity / snap.day_start_equity - 1.0
        if day_pnl <= -limits.daily_loss_pct / 100.0:
            ev = _ev("portfolio_daily_loss", added.symbol, svid, {
                "day_pnl_pct": round(day_pnl * 100, 4),
                "limit_pct": limits.daily_loss_pct,
            }, ts)
            return PortfolioDecision(False, reason="portfolio daily loss", events=[ev])

    # Net sembol maruziyeti (eklemeden sonra) ≤ %35.
    net_symbol = _net_symbol_after(snap, added)
    symbol_pct = net_symbol / eq * 100.0
    if symbol_pct > limits.max_symbol_exposure_pct + 1e-9:
        ev = _ev("symbol_exposure", added.symbol, svid, {
            "net_exposure_pct": round(symbol_pct, 4),
            "cap_pct": limits.max_symbol_exposure_pct,
        }, ts)
        return PortfolioDecision(False, reason="symbol exposure cap", events=[ev])

    # Brüt kaldıraç (eklemeden sonra) ≤ 3x.
    gross = (sum(p.notional for p in snap.positions) + added.notional) / eq
    if gross > limits.gross_leverage_cap + 1e-9:
        ev = _ev("gross_leverage", added.symbol, svid, {
            "gross_leverage": round(gross, 4),
            "cap": limits.gross_leverage_cap,
        }, ts)
        return PortfolioDecision(False, reason="gross leverage cap", events=[ev])

    # Tek yön yoğunlaşması: net yönlü maruziyet (|long−short|) equity'nin %60'ını
    # aşıyor ve eklenen bacak baskın yöndeyse aynı-yön girişi kısıtlanır (doc §24.5).
    # Net yönlü / equity ölçülür — tek pozisyon "yüzde yüz tek yön" değildir, aksi
    # halde ilk işlem bile bloke olurdu.
    conc, conc_side = _direction_concentration_after(snap, added, eq)
    if (
        conc > limits.direction_concentration_pct / 100.0 + 1e-9
        and added.side == conc_side
    ):
        ev = _ev("direction_concentration", added.symbol, svid, {
            "net_directional_pct": round(conc * 100, 4),
            "cap_pct": limits.direction_concentration_pct,
            "side": conc_side,
        }, ts)
        return PortfolioDecision(False, reason="direction concentration", events=[ev])

    return PortfolioDecision(True)


def warnings(limits: PortfolioLimits, snap: PortfolioSnapshot, ts: int) -> list[dict]:
    """Reddetmeyen uyarılar: aktif-strateji bandı (doc §24.5, 3–8).

    <3 ⇒ "çeşitlendirme yok", >8 ⇒ "izlenemez". Servis/UI bunları düz cümleye
    çevirir; ``risk_events``'e uyarı olarak da düşebilir.
    """
    out: list[dict] = []
    n = snap.active_strategies
    if n and n < limits.min_active:
        out.append(_ev("active_strategies", None, None, {
            "active": n, "min": limits.min_active, "issue": "under_diversified",
        }, ts))
    elif n > limits.max_active:
        out.append(_ev("active_strategies", None, None, {
            "active": n, "max": limits.max_active, "issue": "unmonitorable",
        }, ts))
    return out


# ── internals ────────────────────────────────────────────────────────────────
def _net_symbol_after(snap: PortfolioSnapshot, added: AddedLeg) -> float:
    """Eklenen bacaktan sonra ``added.symbol`` için net (imzalı) maruziyet."""
    signed = 0.0
    for p in snap.positions:
        if p.symbol == added.symbol:
            signed += p.notional if p.side == "long" else -p.notional
    signed += added.notional if added.side == "long" else -added.notional
    return abs(signed)


def _direction_concentration_after(
    snap: PortfolioSnapshot, added: AddedLeg, equity: float
) -> tuple[float, str]:
    """Eklemeden sonra net yönlü maruziyet / equity ve baskın yön.

    Net yönlü = |Σlong − Σshort|; equity'ye oranlanır. Tek pozisyon bunu %60'a
    kolayca çıkarmaz (20% notional ⇒ 20% net yönlü), böylece ilk işlem bloke olmaz;
    yalnızca portföy gerçekten tek yöne yaslandığında yeni aynı-yön girişi kısılır.
    """
    long_n = sum(p.notional for p in snap.positions if p.side == "long")
    short_n = sum(p.notional for p in snap.positions if p.side == "short")
    if added.side == "long":
        long_n += added.notional
    else:
        short_n += added.notional
    net = long_n - short_n
    conc = abs(net) / equity
    side = "long" if net >= 0 else "short"
    return conc, side
