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


settings = Settings()
