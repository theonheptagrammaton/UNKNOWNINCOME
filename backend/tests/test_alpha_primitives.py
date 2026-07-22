"""Faz 11 §25.4 alpha primitives: correctness + lookahead safety (kural #1).

Each primitive is a normal custom indicator (it enters the registry and passes the Faz 9
gate like any other, §25.4). The lookahead proof reuses the Faz 2 property-test pattern:
rewrite every *future* bar and assert the *past* outputs are byte-for-byte unchanged, so a
signal computed now can never move when a later bar arrives.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators.custom.flow_imbalance import compute as flow_imbalance
from app.indicators.custom.flow_imbalance import per_bar_imbalance
from app.indicators.custom.funding_extreme import _expanding_pct_rank, extreme_activation
from app.indicators.custom.funding_extreme import compute as funding_extreme
from app.indicators.custom.liq_cascade import compute as liq_cascade
from app.indicators.custom.oi_divergence import compute as oi_divergence
from app.indicators.registry import get_indicator

CUT = 25


def _stable_past(base: pd.Series, after: pd.Series, cut: int = CUT) -> None:
    """Past bars (< cut) must be identical after any future rewrite (NaN-safe)."""
    a = base.iloc[:cut].to_numpy(dtype="float64")
    b = after.iloc[:cut].to_numpy(dtype="float64")
    assert np.allclose(np.nan_to_num(a, nan=-7.0), np.nan_to_num(b, nan=-7.0))


def _flow_df(n: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    vol = pd.Series(rng.uniform(100, 1000, n))
    return pd.DataFrame(
        {
            "ts": np.arange(n) * 3_600_000,
            "close": 100 + np.cumsum(rng.standard_normal(n)),
            "volume": vol,
            "taker_buy_base_volume": vol * rng.uniform(0.2, 0.8, n),
            "open_interest": 1e6 + np.cumsum(rng.standard_normal(n)) * 1e3,
            "liq_buy_notional": rng.uniform(0, 5e5, n),
            "liq_sell_notional": rng.uniform(0, 5e5, n),
        }
    )


# ── All four are registered as custom indicators (§25.4) ─────────────────────
@pytest.mark.parametrize(
    "iid,category,role_hint",
    [
        ("flow_imbalance", "momentum", "trigger"),
        ("oi_divergence", "volume", "filter"),
        ("funding_extreme", "statistic", "filter"),
        ("liq_cascade", "momentum", "trigger"),
    ],
)
def test_registered_as_normal_indicators(iid: str, category: str, role_hint: str) -> None:
    d = get_indicator(iid)
    assert d is not None and d.source == "custom"
    assert d.category == category
    assert d.outputs == [iid]
    assert d.params  # tunable knobs the discovery pipeline sweeps


# ── flow_imbalance ───────────────────────────────────────────────────────────
def test_flow_per_bar_imbalance_bounds() -> None:
    vol = pd.Series([100.0, 100.0, 100.0, 0.0])
    taker = pd.Series([100.0, 0.0, 50.0, 10.0])
    fi = per_bar_imbalance(taker, vol)
    assert fi.tolist() == [1.0, -1.0, 0.0, 0.0]  # all-buy / all-sell / neutral / no-volume


def test_flow_smoothing_threshold_and_direction() -> None:
    vol = pd.Series([100.0] * 4)
    taker = pd.Series([100.0, 100.0, 0.0, 0.0])  # per-bar imbalance = [1, 1, -1, -1]
    out = flow_imbalance(pd.DataFrame({"volume": vol, "taker_buy_base_volume": taker}), window=2)
    assert out.tolist() == [1.0, 1.0, 0.0, -1.0]  # rolling-2 mean
    # dir = -1 flips the sign; threshold zeroes weak bars.
    flipped = flow_imbalance(
        pd.DataFrame({"volume": vol, "taker_buy_base_volume": taker}), window=2, dir=-1
    )
    assert flipped.tolist() == [-1.0, -1.0, 0.0, 1.0]
    gated = flow_imbalance(
        pd.DataFrame({"volume": vol, "taker_buy_base_volume": taker}), window=2, threshold=0.5
    )
    assert gated.tolist() == [1.0, 1.0, 0.0, -1.0]  # |0| < 0.5 already 0, |1| kept


def test_flow_imbalance_ignores_future() -> None:
    df = _flow_df(50)
    base = flow_imbalance(df, window=5, dir=1)
    mutated = df.copy()
    mutated.loc[CUT:, ["taker_buy_base_volume", "volume"]] = 999.0
    _stable_past(base, flow_imbalance(mutated, window=5, dir=1))


# ── oi_divergence ────────────────────────────────────────────────────────────
def test_oi_divergence_matches_configured_pattern() -> None:
    # close: up,up,down ; oi: up,down,down
    df = pd.DataFrame(
        {
            "ts": np.arange(4) * 3_600_000,
            "close": [100.0, 101.0, 102.0, 101.0],
            "open_interest": [10.0, 11.0, 10.5, 10.0],
        }
    )
    up_up = oi_divergence(df, price_dir=1, oi_dir=1)
    assert up_up.tolist() == [0.0, 1.0, 0.0, 0.0]  # only bar 1: price↑ & OI↑
    up_down = oi_divergence(df, price_dir=1, oi_dir=-1)
    assert up_down.tolist() == [0.0, 0.0, 1.0, 0.0]  # bar 2: price↑ & OI↓ (short-cover)


def test_oi_divergence_absent_oi_is_zero() -> None:
    df = pd.DataFrame({"ts": np.arange(3) * 3_600_000, "close": [1.0, 2.0, 3.0]})
    # No open_interest column and no attrs context → no signal, never an error.
    assert oi_divergence(df, price_dir=1, oi_dir=1).tolist() == [0.0, 0.0, 0.0]


def test_oi_divergence_ignores_future() -> None:
    df = _flow_df(50)
    base = oi_divergence(df, price_dir=1, oi_dir=1)
    mutated = df.copy()
    mutated.loc[CUT:, ["close", "open_interest"]] = 999.0
    _stable_past(base, oi_divergence(mutated, price_dir=1, oi_dir=1))


# ── funding_extreme ──────────────────────────────────────────────────────────
def test_expanding_pct_rank_uses_only_the_past() -> None:
    x = pd.Series([1.0, 3.0, 2.0, 5.0])
    rank = _expanding_pct_rank(x)
    # i0: 1/1 ; i1: 3 is largest so far 2/2 ; i2: 2 ≤ {1,2} → 2/3 ; i3: 5 largest 4/4
    assert rank.tolist() == pytest.approx([1.0, 1.0, 2 / 3, 1.0])


def test_funding_extreme_flags_high_tail() -> None:
    funding = pd.Series([0.0, 5.0, 6.0, 6.5, 100.0])  # Δ = [nan,5,1,0.5,93.5]
    act = extreme_activation(funding, percentile=0.9, dir=1)
    assert act.tolist() == [0.0, 1.0, 0.0, 0.0, 1.0]  # ranks 1.0 at bars 1 & 4


def test_funding_extreme_column_path() -> None:
    df = pd.DataFrame({"ts": np.arange(5) * 3_600_000, "funding_rate": [0.0, 5.0, 6.0, 6.5, 100.0]})
    out = funding_extreme(df, percentile=0.9, dir=1)
    assert out.tolist() == [0.0, 1.0, 0.0, 0.0, 1.0]


def test_funding_extreme_ignores_future() -> None:
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {"ts": np.arange(50) * 3_600_000, "funding_rate": np.cumsum(rng.standard_normal(50)) * 1e-4}
    )
    base = funding_extreme(df, percentile=0.8, dir=0)
    mutated = df.copy()
    mutated.loc[CUT:, "funding_rate"] = 999.0
    _stable_past(base, funding_extreme(mutated, percentile=0.8, dir=0))


# ── liq_cascade ──────────────────────────────────────────────────────────────
def test_liq_cascade_net_and_threshold() -> None:
    df = pd.DataFrame(
        {
            "ts": np.arange(4) * 3_600_000,
            "liq_buy_notional": [0.0, 0.0, 100.0, 0.0],
            "liq_sell_notional": [0.0, 0.0, 0.0, 50.0],
        }
    )
    out = liq_cascade(df, window=2, usd_threshold=0.0)
    assert out.tolist() == [0.0, 0.0, 100.0, 50.0]  # trailing-2 net (buy − sell)
    gated = liq_cascade(df, window=2, usd_threshold=120.0)
    assert gated.tolist() == [0.0, 0.0, 0.0, 50.0]  # only the last bar clears 120 total


def test_liq_cascade_absent_data_is_zero() -> None:
    df = pd.DataFrame({"ts": np.arange(3) * 3_600_000, "close": [1.0, 2.0, 3.0]})
    assert liq_cascade(df, window=3).tolist() == [0.0, 0.0, 0.0]


def test_liq_cascade_ignores_future() -> None:
    df = _flow_df(50)
    base = liq_cascade(df, window=4)
    mutated = df.copy()
    mutated.loc[CUT:, ["liq_buy_notional", "liq_sell_notional"]] = 9e9
    _stable_past(base, liq_cascade(mutated, window=4))
