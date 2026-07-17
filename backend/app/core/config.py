"""Application configuration, sourced from environment variables.

All timestamps are UTC (doc §2 rule 5); the UI converts to Europe/Istanbul.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings. Missing ``.env`` falls back to defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    tz: str = "UTC"

    # PostgreSQL — application state only (market data lives in Parquet).
    database_url: str = (
        "postgresql+asyncpg://UNKNOWNINCOME:CHANGE_ME@postgres:5432/UNKNOWNINCOME"
    )
    # Redis — arq queue + cache.
    redis_url: str = "redis://redis:6379/0"
    # Parquet + DuckDB market-data store root.
    data_dir: str = "/data/parquet"

    # CORS: allowed frontend origins.
    cors_origins: list[str] = ["http://localhost:3000"]

    # ─── Market data (Phase 1) ────────────────────────────────────────────
    market: str = "binance_usdm"
    default_timeframes: list[str] = ["1m", "5m", "15m", "1h", "4h", "1d"]
    default_lookback_months: int = 24
    ohlcv_fetch_limit: int = 1500  # Binance futures klines page size

    # Binance USDT-M perpetual futures (public data needs no keys).
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = False

    # Dynamic universe (doc §4.5).
    universe_size: int = 30
    universe_quote: str = "USDT"
    universe_prefilter_size: int = 60  # top-K by 24h volume before deep filter
    universe_min_median_volume_usd: float = 5_000_000.0
    universe_max_spread_bps: float = 5.0
    universe_volume_window_days: int = 30


settings = Settings()
