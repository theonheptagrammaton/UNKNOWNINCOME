"""Registry integrity: 200+ entries, coherent metadata, all three sources."""

from __future__ import annotations

from app.indicators.registry import (
    CATEGORIES,
    OHLCV_INPUTS,
    get_indicator,
    get_registry,
    list_indicators,
)


def test_registry_has_200_plus_entries() -> None:
    assert len(get_registry()) >= 200


def test_all_three_sources_present() -> None:
    sources = {d.source for d in get_registry().values()}
    assert {"talib", "pandas_ta", "custom"} <= sources


def test_every_definition_is_well_formed() -> None:
    for d in get_registry().values():
        assert d.id and d.name
        assert d.category in CATEGORIES
        assert d.source in ("talib", "pandas_ta", "custom")
        assert d.outputs, f"{d.id} has no outputs"
        assert d.inputs and set(d.inputs) <= set(OHLCV_INPUTS)
        assert d.signal_templates, f"{d.id} has no signal templates"
        for name, spec in d.params.items():
            assert spec.default is not None, f"{d.id}.{name} missing default"


def test_ids_unique_and_listing_sorted() -> None:
    defs = list_indicators()
    ids = [d.id for d in defs]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)


def test_filter_by_category_and_source() -> None:
    momentum = list_indicators(category="momentum")
    assert momentum and all(d.category == "momentum" for d in momentum)
    pta = list_indicators(source="pandas_ta")
    assert pta and all(d.source == "pandas_ta" for d in pta)


def test_core_indicators_present() -> None:
    for iid in ("sma", "ema", "rsi", "macd", "bbands", "atr", "stoch", "obv", "cdldoji"):
        assert get_indicator(iid) is not None, f"{iid} missing from registry"


def test_custom_zscore_registered() -> None:
    d = get_indicator("zscore")
    assert d is not None
    assert d.source == "custom"
    assert d.outputs == ["zscore"]
    assert "length" in d.params
