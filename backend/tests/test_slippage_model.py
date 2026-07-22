"""Learned slippage model (doc §26.1): buckets, trust threshold, artifact, and the
backtest actually pricing fills at the learned slippage — with the difference from the
fixed assumption reported (KABUL #1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.backtest.config import CapitalConfig, CostConfig, RunConfig
from app.backtest.engine import run_engine
from app.backtest.runner import learned_slippage_series
from app.execution.slippage_model import (
    FillObservation,
    adverse_slippage_bps,
    bucket_key,
    learn,
    load_model,
    materialize,
    worse_than_assumption,
)


def _obs(bps_offset: float, n: int, symbol="BTCUSDT", tf="1h") -> list[FillObservation]:
    """n fills in one bucket, each with a buy fill `bps_offset` bps above expected."""
    out = []
    expected = 100.0
    fill = expected * (1 + bps_offset / 1e4)
    for i in range(n):
        out.append(FillObservation(
            symbol=symbol, tf=tf, side="buy", expected_price=expected, fill_price=fill,
            order_notional=5_000.0, atr=0.8, ts=1_700_000_000_000 + i,
        ))
    return out


def test_adverse_slippage_sign() -> None:
    # Buy filled above expected → adverse (positive); sell below expected → also adverse.
    assert adverse_slippage_bps(100.0, 100.5, "buy") == 50.0
    assert adverse_slippage_bps(100.0, 99.5, "sell") == 50.0
    # A favourable fill is negative.
    assert adverse_slippage_bps(100.0, 99.5, "buy") == -50.0


def test_untrusted_until_min_samples() -> None:
    model = learn(_obs(30.0, 49), min_samples=50)
    key = bucket_key("BTCUSDT", "1h", 5_000.0, 0.8, 100.3)
    assert model.buckets[key].samples == 49
    assert not model.buckets[key].trusted
    # An untrusted bucket returns None → the caller falls back to the assumption.
    assert model.lookup_bps("BTCUSDT", "1h", 5_000.0, 0.8, 100.3) is None


def test_trusted_at_50_returns_learned_bps() -> None:
    model = learn(_obs(30.0, 50), min_samples=50)
    assert model.trusted_buckets == 1
    got = model.lookup_bps("BTCUSDT", "1h", 5_000.0, 0.8, 100.3)
    assert got is not None and abs(got - 30.0) < 1e-9


def test_materialize_load_roundtrip(tmp_path: Path) -> None:
    model = learn(_obs(12.0, 50), min_samples=50)
    path = tmp_path / "slippage_model.json"
    materialize(model, path)
    loaded = load_model(path)
    assert loaded is not None
    assert loaded.lookup_bps("BTCUSDT", "1h", 5_000.0, 0.8, 100.1) is not None
    assert load_model(tmp_path / "missing.json") is None


def test_worse_than_assumption_flags_only_worse_trusted_buckets() -> None:
    model = learn(_obs(9.0, 50), min_samples=50)  # 9 bps learned
    assert worse_than_assumption(model, assumed_bps=5.0)  # 9 > 5 → flagged
    assert not worse_than_assumption(model, assumed_bps=12.0)  # 9 < 12 → fine
    # Untrusted buckets never flag, however bad.
    cold = learn(_obs(50.0, 10), min_samples=50)
    assert not worse_than_assumption(cold, assumed_bps=5.0)


# ── Backtest integration: learned model priced the fills (KABUL #1) ────────────
def _ohlcv(n: int = 60) -> pd.DataFrame:
    ts = np.arange(n, dtype="int64") * 3_600_000
    price = np.full(n, 100.0)
    vol = np.full(n, 1_000_000.0)
    return pd.DataFrame({"ts": ts, "open": price, "high": price + 1,
                         "low": price - 1, "close": price, "volume": vol})


def _signals(n: int) -> dict[str, pd.Series]:
    le = np.zeros(n, dtype=bool)
    lx = np.zeros(n, dtype=bool)
    le[5] = True  # one round-trip
    lx[10] = True
    z = np.zeros(n, dtype=bool)
    return {"long_entry": pd.Series(le), "long_exit": pd.Series(lx),
            "short_entry": pd.Series(z), "short_exit": pd.Series(z)}


def test_engine_learned_series_differs_from_fixed_assumption() -> None:
    df = _ohlcv()
    n = len(df)
    sig = _signals(n)
    cap = CapitalConfig(sizing="fixed", size_pct=0.5, leverage=1.0)

    fixed = CostConfig(slippage_model="fixed_bps", slippage_bps=5.0, funding_enabled=False)
    r_fixed = run_engine(df, sig, fixed, cap)

    # Learned model prices this symbol/tf at 40 bps — much worse than the 5 bps guess.
    learned = CostConfig(slippage_model="learned", slippage_bps=5.0, funding_enabled=False)
    series = np.full(n, 40.0)
    r_learned = run_engine(df, sig, learned, cap, slippage_bps_series=series)

    assert r_fixed.cost_breakdown["slippage_source"] == "fixed_bps"
    assert r_learned.cost_breakdown["slippage_source"] == "learned"
    # Higher learned slippage ⇒ strictly more slippage cost than the assumption (the
    # reported "difference from the fixed assumption").
    assert r_learned.cost_breakdown["total_slippage"] > r_fixed.cost_breakdown["total_slippage"]


def test_runner_series_uses_learned_where_trusted_else_fallback() -> None:
    model = learn(_obs(25.0, 50), min_samples=50)  # bucket: notional tier 1, vol tier 1
    df = _ohlcv()
    # Constant true range 0.8 ⇒ Wilder ATR settles at 0.8 ⇒ vol tier 1 (0.008), matching
    # the observations; the representative notional (10k×0.5) lands in notional tier 1 too.
    df = df.assign(high=df["close"] + 0.4, low=df["close"] - 0.4)
    cfg = RunConfig(
        symbol="BTCUSDT", tf="1h",
        costs=CostConfig(slippage_model="learned", slippage_bps=5.0),
        capital=CapitalConfig(sizing="fixed", size_pct=0.5, leverage=1.0),
    )
    series = learned_slippage_series(cfg, df, model=model)
    assert series is not None
    # Warmed-up bars match the trusted bucket → 25 bps; ATR-warmup bars fall back to 5 bps.
    assert (series == 25.0).any()
    assert (series == 5.0).any()
