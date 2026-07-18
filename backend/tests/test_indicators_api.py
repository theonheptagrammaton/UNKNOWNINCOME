"""Indicator API: list, detail, 404, and compute preview."""

from __future__ import annotations

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.data.parquet_store import ohlcv_rows_to_frame, write_ohlcv
from app.main import app
from fakes import make_wave_ohlcv


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_indicators() -> None:
    async with await _client() as client:
        resp = await client.get("/api/indicators")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] >= 200
        assert body["count"] == len(body["indicators"])


async def test_list_filtered_by_source() -> None:
    async with await _client() as client:
        resp = await client.get("/api/indicators", params={"source": "custom"})
        assert resp.status_code == 200
        ids = [d["id"] for d in resp.json()["indicators"]]
        assert "zscore" in ids


async def test_get_indicator_detail() -> None:
    async with await _client() as client:
        resp = await client.get("/api/indicators/rsi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "rsi"
        assert body["params"]["timeperiod"]["default"] == 14.0


async def test_get_unknown_indicator_404() -> None:
    async with await _client() as client:
        resp = await client.get("/api/indicators/not_a_real_indicator")
        assert resp.status_code == 404


async def test_compute_preview(data_dir: Path) -> None:
    write_ohlcv(
        "binance_usdm", "BTCUSDT", "1h", ohlcv_rows_to_frame(make_wave_ohlcv(120, "1h"))
    )
    async with await _client() as client:
        resp = await client.post(
            "/api/indicators/compute",
            json={
                "symbol": "BTCUSDT",
                "tf": "1h",
                "indicator_id": "rsi",
                "params": {"timeperiod": 14},
                "limit": 30,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["outputs"] == ["rsi"]
        assert body["params"]["timeperiod"] == 14.0
        assert body["count"] == 30
        last = body["series"][-1]
        assert "ts" in last and "rsi" in last
        assert last["rsi"] is not None


async def test_compute_unknown_indicator_404(data_dir: Path) -> None:
    async with await _client() as client:
        resp = await client.post(
            "/api/indicators/compute",
            json={"symbol": "BTCUSDT", "tf": "1h", "indicator_id": "nope"},
        )
        assert resp.status_code == 404
