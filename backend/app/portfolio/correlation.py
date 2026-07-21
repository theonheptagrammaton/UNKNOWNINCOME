"""Strateji getiri korelasyonu (doc §24.2).

Korelasyon **getiri serileri** üzerinden ölçülür, equity seviyesi üzerinden değil:
farklı sermaye ile koşan iki strateji karşılaştırılabilir olmalı, bu yüzden her
stratejinin günlük PnL'i korelasyondan önce sermaye tabanına bölünür. Paper
stratejiler de matrise girer — canlı bir strateji ile 0.95 korele bir paper
strateji çeşitlendirici değil, bir uyarıdır. Pencere kayan 90 gündür (doc §24.2).

Saf: pandas/numpy dışında bağımlılık yok, DB yok. Servis katmanı ham işlemleri
buraya seri olarak verir; matris + kapı kararı buradan çıkar.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import numpy as np
import pandas as pd

WINDOW_DAYS = 90  # doc §24.2 — rolling correlation window


def daily_returns(pnl_by_ts: Iterable[tuple[int, float]], capital: float) -> pd.Series:
    """Günlük getiri serisi = (o UTC günündeki PnL toplamı) / sermaye.

    ``pnl_by_ts`` closed-trade ``(exit_ts_ms, pnl)`` çiftleridir. Sermayeye bölmek
    farklı büyüklükteki stratejileri aynı ölçeğe indirir (doc §24.2: equity değil,
    getiri). Boş girdi ⇒ boş seri; ``capital <= 0`` ⇒ boş seri (bölme yok).
    """
    rows = [(int(ts), float(pnl)) for ts, pnl in pnl_by_ts]
    if not rows or capital <= 0:
        return pd.Series(dtype="float64")
    df = pd.DataFrame(rows, columns=["ts", "pnl"])
    df["day"] = df["ts"].map(
        lambda ms: datetime.fromtimestamp(ms / 1000, tz=UTC).date()
    )
    by_day = df.groupby("day")["pnl"].sum() / capital
    by_day.index = pd.to_datetime(by_day.index)
    return by_day.sort_index()


def return_matrix(
    strategy_returns: dict[str, pd.Series], window_days: int = WINDOW_DAYS
) -> pd.DataFrame:
    """Stratejileri ortak günlük eksende hizala; son ``window_days`` günü tut.

    Bir stratejinin işlem yapmadığı gün getirisi 0'dır (o gün risk almadı), bu
    yüzden hizalamada eksik günler 0 ile doldurulur — NaN korelasyonu bozar.
    """
    if not strategy_returns:
        return pd.DataFrame()
    frame = pd.DataFrame(strategy_returns).sort_index().fillna(0.0)
    if window_days > 0 and not frame.empty:
        cutoff = frame.index.max() - pd.Timedelta(days=window_days)
        frame = frame.loc[frame.index >= cutoff]
    return frame


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    """Getiri matrisinin Pearson korelasyonu (köşegen 1, simetrik).

    Sabit (sıfır varyans) bir seri ile korelasyon tanımsızdır; pandas NaN döner,
    biz onu 0'a çekeriz (bilgi yok = korelasyon yok varsayımı; kapı yanlışlıkla
    ateşlemez). Tek strateji ⇒ 1x1 birim matris.
    """
    if returns.shape[1] == 0:
        return pd.DataFrame()
    corr = returns.corr(method="pearson").fillna(0.0)
    # Köşegeni 1'e sabitle (sabit-seri NaN'ları 0'a indi). Pandas 3.0 copy-on-write
    # ``.values``'ı salt-okunur yapar, bu yüzden yazılabilir bir kopyaya doldur.
    arr = corr.to_numpy(copy=True)
    np.fill_diagonal(arr, 1.0)
    return pd.DataFrame(arr, index=corr.index, columns=corr.columns)


def max_abs_correlation(
    candidate: str, corr: pd.DataFrame, pool: Iterable[str]
) -> tuple[str | None, float]:
    """``candidate`` ile ``pool`` içindeki stratejiler arasındaki en yüksek |ρ|.

    Kendisiyle karşılaştırma dışlanır. Kapı kararının girdisidir (doc §24.2:
    ``|ρ| > 0.70`` ⇒ tahsis kısıtı veya red). Matriste yoksa ``(None, 0.0)``.
    """
    if candidate not in corr.index:
        return None, 0.0
    best_id: str | None = None
    best = 0.0
    for other in pool:
        if other == candidate or other not in corr.columns:
            continue
        rho = abs(float(corr.at[candidate, other]))
        if rho > best:
            best, best_id = rho, other
    return best_id, best
