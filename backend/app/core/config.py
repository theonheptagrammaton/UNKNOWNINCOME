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

    # CORS: allowed frontend origins. Both loopback forms are allowed for local
    # dev — a browser at 127.0.0.1:3000 sends that Origin, not "localhost".
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # ─── Market data (Phase 1) ────────────────────────────────────────────
    market: str = "binance_usdm"
    default_timeframes: list[str] = ["1m", "5m", "15m", "1h", "4h", "1d"]
    default_lookback_months: int = 24
    ohlcv_fetch_limit: int = 1500  # Binance futures klines page size

    # Binance USDT-M perpetual futures (public data needs no keys).
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = False

    # ─── Live execution (Phase 7, doc §9.2–9.5) ───────────────────────────
    # The whole live-order path is closed by default. Even with this on, an
    # effective-Live strategy only reaches the exchange once the promotion gate
    # (§9.5) passes — enforced at the API, mode and engine layers alike.
    live_trading_enabled: bool = False
    # Mainnet is a second, deliberate switch: testnet first (rule: "önce testnet,
    # config ile mainnet"). Live keys go to the testnet by default.
    live_use_mainnet: bool = False
    # Fernet master key for the encrypted API-key vault (doc §13). Empty ⇒ the
    # vault refuses to store/read keys (no plaintext fallback in the DB).
    secrets_key: str = ""
    # Isolated margin + one-way mode are pazarlıksız (rule #11); exposed only so
    # a test can assert the defaults, not to invite cross-margin.
    live_margin_mode: str = "isolated"
    live_position_mode: str = "oneway"
    # Exchange-resilience knobs (retry + circuit breaker, §9.2 dayanıklılık).
    live_max_retries: int = 3
    live_retry_backoff_seconds: float = 0.5
    live_circuit_breaker_threshold: int = 5  # consecutive failures ⇒ open
    live_circuit_breaker_cooldown_seconds: float = 60.0

    # Dynamic universe (doc §4.5).
    universe_size: int = 30
    universe_quote: str = "USDT"
    universe_prefilter_size: int = 60  # top-K by 24h volume before deep filter
    universe_min_median_volume_usd: float = 5_000_000.0
    universe_max_spread_bps: float = 5.0
    universe_volume_window_days: int = 30

    # ─── Trade bot (Phase 5) ──────────────────────────────────────────────
    # Whether the paper bot loop runs inside the worker.
    bot_enabled: bool = True
    bot_tick_seconds: float = 2.0  # strategy-evaluation cadence
    bot_killswitch_poll_seconds: float = 0.5  # kill-switch poll (≤2s response)
    bot_paper_initial_cash: float = 10_000.0
    # Kill-switch file flag (doc §9.4). Empty ⇒ ``<data_dir>/KILLSWITCH``.
    killswitch_file: str = ""

    # Telegram remote control (doc §10.3). Real polling runs only when a token
    # is set (operator step); the command/notification logic is pure + tested.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""  # single whitelisted chat id
    telegram_enabled: bool = False

    # ─── Self-improvement (Phase 6, doc §8.3–8.5) ─────────────────────────
    # Weekly WFO re-optimization + degradation-triggered regeneration.
    reopt_enabled: bool = True
    reopt_generator: str = "wfo_reopt"  # v1 producer (doc §8.3); genetic/rl reserved
    reopt_trials: int = 30  # Optuna budget per re-optimization
    reopt_train_days: int = 90  # walk-forward window (doc §6.5)
    reopt_test_days: int = 30
    reopt_step_days: int = 30
    reopt_monte_carlo_runs: int = 300
    reopt_plateau_ratio: float = 0.5  # neighbours must score ≥ ratio × best
    reopt_plateau_steps: int = 1

    # Degradation triggers (doc §8.5): rolling-N PF < floor OR realized drawdown
    # breaching the WFO 95% Monte-Carlo lower band → auto-pause + queue re-opt.
    degrade_rolling_window: int = 30  # last-N closed trades
    degrade_min_trades: int = 30  # need this many before the PF trigger can fire
    degrade_min_profit_factor: float = 1.0
    degrade_mc_drawdown_enabled: bool = True

    # Regime gating (doc §8.4): off | auto | trend | range | trend/high | …
    # ``off`` (default) = no gating (opt-in); ``auto`` = match the live market
    # regime; an explicit value = manual lock.
    regime_lock_default: str = "off"
    regime_adx_period: int = 14
    regime_adx_trend_threshold: float = 25.0
    regime_atr_period: int = 14
    regime_atr_high_pct: float = 0.5


settings = Settings()
