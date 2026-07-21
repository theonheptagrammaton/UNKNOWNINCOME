"""Portföy orkestrasyonu (doc §24.1 ``service.py``).

İki katman: (1) **saf çekirdek** ``build_snapshot`` — önceden yüklenmiş veriden
tahsis + korelasyon + katkı + uyarıları hesaplar, DB'siz, test edilebilir; (2)
**async yükleyici** ``portfolio_snapshot`` — stratejileri, kapalı işlemleri ve son
equity'yi DB'den okur ve çekirdeği besler. UI paneli ve ``/api/bot/portfolio``
bu görüntüyü tüketir.

Korelasyon kapısı burada uygulanır: canlı havuza girecek bir strateji mevcut canlı
biriyle ``|ρ| > 0.70`` ise tahsisi korelasyonla orantılı kısılır (varsayılan) —
:func:`app.portfolio.allocation.correlation_gate_factor`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import EquitySnapshot, Trade
from app.portfolio import allocation as alloc
from app.portfolio import correlation as corr
from app.portfolio.limits import PortfolioLimits, PortfolioPosition


@dataclass
class StrategyStat:
    """Bir stratejinin tahsis + korelasyon için özet istatistiği."""

    strategy_id: str
    name: str
    mode: str  # off | paper | live
    returns: pd.Series
    symbol: str | None = None
    direction: int = 0
    locked_weight: float | None = None

    @property
    def vol(self) -> float:
        return float(self.returns.std(ddof=1)) if len(self.returns) > 1 else 0.0

    @property
    def edge(self) -> float:
        return float(self.returns.mean()) if len(self.returns) else 0.0


def build_snapshot(
    stats: list[StrategyStat],
    positions: list[PortfolioPosition],
    equity: float,
    *,
    method: str = "equal_risk",
    corr_threshold: float = alloc.CORRELATION_GATE,
    limits: PortfolioLimits | None = None,
    target_vol: float = alloc.DEFAULT_TARGET_VOL,
) -> dict:
    """Saf çekirdek: tahsis halkası + korelasyon matrisi + katkı + uyarılar.

    ``stats`` canlı **ve** paper stratejileri içerir (korelasyon her ikisini de
    kapsar, doc §24.2). Tahsis ve korelasyon kapısı yalnızca canlı havuza
    uygulanır; paper stratejiler matriste görünür ama tahsis almaz.
    """
    limits = limits or PortfolioLimits()
    ret_mat = corr.return_matrix({s.strategy_id: s.returns for s in stats})
    corr_mat = corr.correlation_matrix(ret_mat)

    live = [s for s in stats if s.mode == "live"]
    live_ids = [s.strategy_id for s in live]

    # Tahsis (yalnızca canlı havuz).
    inputs = [
        alloc.StrategyAlloc(
            strategy_id=s.strategy_id, vol=s.vol, edge=s.edge,
            symbol=s.symbol, direction=s.direction, locked_weight=s.locked_weight,
        )
        for s in live
    ]
    targets = alloc.allocate(inputs, corr_mat, method=method, target_vol=target_vol)

    # Korelasyon kapısı: her canlı stratejinin mevcut havuzla en yüksek |ρ|'sine
    # göre tahsis çarpanı (doc §24.2, varsayılan kısıt).
    gate_rows = []
    for s in live:
        other, rho = corr.max_abs_correlation(
            s.strategy_id, corr_mat, [x for x in live_ids if x != s.strategy_id]
        )
        factor = alloc.correlation_gate_factor(rho, corr_threshold)
        if factor < 1.0:
            targets[s.strategy_id] = targets.get(s.strategy_id, 0.0) * factor
        gate_rows.append({
            "strategy_id": s.strategy_id, "name": s.name,
            "peer": other, "rho": round(rho, 4),
            "gated": factor < 1.0, "factor": round(factor, 4),
        })

    total_target = sum(targets.values()) or 1.0
    allocations = [
        {
            "strategy_id": s.strategy_id, "name": s.name,
            "target": round(targets.get(s.strategy_id, 0.0), 4),
            "target_share": round(targets.get(s.strategy_id, 0.0) / total_target, 4),
        }
        for s in live
    ]

    net_exposure = _net_exposure(positions, equity, limits)
    contributions = _contributions(stats, targets)
    concentration = _concentration_warnings(positions, stats, limits, equity)

    return {
        "method": method,
        "equity": equity,
        "allocations": allocations,
        "correlation": _corr_payload(corr_mat, stats),
        "correlation_gate": {"threshold": corr_threshold, "rows": gate_rows},
        "net_exposure": net_exposure,
        "contributions": contributions,
        "concentration_warnings": concentration,
        "caps": {
            "max_strategy_allocation": alloc.MAX_STRATEGY_WEIGHT,
            "max_symbol_exposure_pct": limits.max_symbol_exposure_pct,
            "gross_leverage_cap": limits.gross_leverage_cap,
            "direction_concentration_pct": limits.direction_concentration_pct,
        },
    }


async def portfolio_snapshot(session: AsyncSession, *, mode: str = "paper") -> dict:
    """DB'den yükle + çekirdeği besle. ``/api/bot/portfolio`` bunu çağırır."""
    strategies = (await session.execute(select(Strategy))).scalars().all()
    version_symbol = await _active_symbols(session, strategies)
    stats: list[StrategyStat] = []
    for strat in strategies:
        trades = (
            await session.execute(
                select(Trade).where(
                    Trade.strategy_id == strat.id, Trade.mode == mode,
                    Trade.status == "closed",
                ).order_by(Trade.exit_ts)
            )
        ).scalars().all()
        pnl_by_ts = [(t.exit_ts, t.pnl) for t in trades if t.exit_ts and t.pnl is not None]
        returns = corr.daily_returns(pnl_by_ts, settings.bot_paper_initial_cash)
        stats.append(StrategyStat(
            strategy_id=strat.id, name=strat.name, mode=strat.mode,
            returns=returns, symbol=version_symbol.get(strat.id),
        ))

    open_trades = (
        await session.execute(
            select(Trade).where(Trade.mode == mode, Trade.status == "open")
        )
    ).scalars().all()
    positions = [
        PortfolioPosition(
            symbol=t.symbol, side=t.side,
            notional=abs(t.qty) * (t.entry_price or 0.0),
        )
        for t in open_trades
    ]
    last_eq = (
        await session.execute(
            select(EquitySnapshot).where(EquitySnapshot.mode == mode)
            .order_by(EquitySnapshot.ts.desc()).limit(1)
        )
    ).scalar_one_or_none()
    equity = last_eq.equity if last_eq else settings.bot_paper_initial_cash

    limits = PortfolioLimits(
        daily_loss_pct=settings.portfolio_daily_loss_pct,
        max_dd_pct=settings.portfolio_max_dd_pct,
        max_symbol_exposure_pct=settings.portfolio_max_symbol_exposure_pct,
        gross_leverage_cap=settings.portfolio_gross_leverage_cap,
        direction_concentration_pct=settings.portfolio_direction_concentration_pct,
    )
    return build_snapshot(
        stats, positions, equity,
        method=settings.portfolio_allocation_method,
        corr_threshold=settings.portfolio_correlation_gate,
        limits=limits,
    )


# ── internals ────────────────────────────────────────────────────────────────
async def _active_symbols(
    session: AsyncSession, strategies: list[Strategy]
) -> dict[str, str | None]:
    """Her stratejinin aktif versiyonunun genome sembolü (korelasyon meta'sı)."""
    out: dict[str, str | None] = {}
    for strat in strategies:
        if strat.active_version_id is None:
            out[strat.id] = None
            continue
        version = await session.get(StrategyVersion, strat.active_version_id)
        genome = version.genome if version else {}
        out[strat.id] = (genome or {}).get("symbol")
    return out


def _net_exposure(
    positions: list[PortfolioPosition], equity: float, limits: PortfolioLimits
) -> list[dict]:
    """Sembol bazında net long/short maruziyet + tavan çizgisi (UI çubuğu)."""
    eq = equity if equity > 0 else 1.0
    by_symbol: dict[str, float] = {}
    for p in positions:
        signed = p.notional if p.side == "long" else -p.notional
        by_symbol[p.symbol] = by_symbol.get(p.symbol, 0.0) + signed
    return [
        {
            "symbol": sym,
            "net_pct": round(signed / eq * 100.0, 4),
            "side": "long" if signed >= 0 else "short",
            "cap_pct": limits.max_symbol_exposure_pct,
        }
        for sym, signed in sorted(by_symbol.items())
    ]


def _contributions(stats: list[StrategyStat], targets: dict[str, float]) -> list[dict]:
    """Her stratejinin portföy getirisine ve riskine katkısı (doc §24.6)."""
    out = []
    for s in stats:
        w = targets.get(s.strategy_id, 0.0)
        out.append({
            "strategy_id": s.strategy_id, "name": s.name, "mode": s.mode,
            "weight": round(w, 4),
            "return_contribution": round(w * s.edge, 6),
            "risk_contribution": round(w * s.vol, 6),
            "vol": round(s.vol, 6),
        })
    return out


def _concentration_warnings(
    positions: list[PortfolioPosition],
    stats: list[StrategyStat],
    limits: PortfolioLimits,
    equity: float,
) -> list[str]:
    """Düz cümleli yoğunlaşma uyarıları (doc §24.6, İngilizce UI dili)."""
    out: list[str] = []
    eq = equity if equity > 0 else 1.0
    long_n = sum(p.notional for p in positions if p.side == "long")
    short_n = sum(p.notional for p in positions if p.side == "short")
    net = long_n - short_n
    conc_pct = abs(net) / eq * 100.0
    side = "long" if net >= 0 else "short"
    if conc_pct > limits.direction_concentration_pct:
        out.append(
            f"{conc_pct:.0f}% of your equity is net {side} — above the "
            f"{limits.direction_concentration_pct:.0f}% concentration limit."
        )
    n_live = sum(1 for s in stats if s.mode == "live")
    if 0 < n_live < limits.min_active:
        out.append(
            f"Only {n_live} live strategy(ies) — below the {limits.min_active} "
            "diversification floor."
        )
    elif n_live > limits.max_active:
        out.append(
            f"{n_live} live strategies — above the {limits.max_active} "
            "monitorable ceiling."
        )
    return out


def _corr_payload(corr_mat: pd.DataFrame, stats: list[StrategyStat]) -> dict:
    """Korelasyon ısı haritası için etiketli matris (0.70 üstü UI'da kırmızı)."""
    if corr_mat.empty:
        return {"labels": [], "matrix": []}
    name_by_id = {s.strategy_id: s.name for s in stats}
    labels = [name_by_id.get(sid, sid) for sid in corr_mat.index]
    matrix = [[round(float(v), 4) for v in row] for row in corr_mat.values]
    return {"labels": labels, "ids": list(corr_mat.index), "matrix": matrix}
