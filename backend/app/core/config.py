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

    # ─── Liquidation collector (Faz 8, forward-collect for Faz 11) ────────
    # !forceOrder@arr websocket → `liquidations` table. Off by default; the
    # worker launches it when on, or run `python -m app.data.collectors.liquidations`.
    # This data cannot be backfilled, so start it as early as possible.
    liquidation_collector_enabled: bool = False
    liquidation_batch_rows: int = 500  # flush after this many buffered events
    liquidation_batch_seconds: float = 5.0  # …or this many seconds, whichever first

    # ─── Open-interest collector (Faz 11, §25.3) ──────────────────────────
    # Polls current OI every `open_interest_poll_seconds` on a 5-min grid. Like
    # liquidations, OI history is not backfillable past ~30 days, so collect forward.
    open_interest_collector_enabled: bool = False
    open_interest_poll_seconds: float = 300.0  # 5-minute REST poll

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

    # ── Portfolio layer (doc §24, Faz 10) ────────────────────────────────────
    # Allocation method (§28.2 Kuşak 2). equal_risk | inverse_vol | kelly | manual.
    portfolio_allocation_method: str = "equal_risk"
    # New-strategy correlation gate (§28.2 Kuşak 3). |ρ| above → allocation cut.
    portfolio_correlation_gate: float = 0.70
    # Portfolio-level risk limits (§24.5). Structural caps (symbol 35%, gross 3x)
    # are non-negotiable ceilings; config may only tighten them.
    portfolio_daily_loss_pct: float = 3.0  # → halt all new entries
    portfolio_max_dd_pct: float = 12.0  # → kill switch (stricter than strategy 15%)
    portfolio_max_symbol_exposure_pct: float = 35.0  # net, share of equity
    portfolio_gross_leverage_cap: float = 3.0  # total notional / equity
    portfolio_direction_concentration_pct: float = 60.0  # net long|short ≤ this

    # ── Execution quality & capacity (doc §26, Faz 12) ───────────────────────
    # Learned slippage (§26.1): a bucket is trusted once it holds this many real fills;
    # below it the backtest keeps the fixed-bps assumption.
    slippage_learn_min_samples: int = 50
    # How much worse-than-assumed (bps) a trusted bucket may be before the reconciler
    # re-runs affected backtests. 0 = re-run on any regression (doc §26.1).
    slippage_reconcile_tolerance_bps: float = 0.0
    # Limit-entry path (§26.3) — opt-in, OFF by default; carries a separate report tag.
    limit_entry_enabled: bool = False
    limit_timeout_s: float = 5.0  # seconds a limit rests before the market fallback
    maker_fee_bps: float = 2.0  # maker fee for a filled limit (vs 4 bps taker)


settings = Settings()
