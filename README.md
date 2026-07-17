# UNKNOWNINCOME

Autonomous backtest & trading system — one engine with two faces:

- **Backtest Lab** (`/backtest`): scans 200+ technical indicators (single + combinations) over historical OHLCV, ranks strategies by a composite score, and validates survivors with walk-forward + out-of-sample.
- **Trade Deck** (`/trade`): runs validated strategies in paper trading first, then behind a numeric promotion gate into live, with a mandatory risk layer, kill switch, and full decision transparency.

Core engine is **asset-agnostic**; market-specific code lives only in `data/` and `execution/` adapters. First adapter: **Binance USDT-M perpetual futures** (long + short, funding-aware). Single-user by design. Full spec: [`docs/PROJE_DOKUMANI.md`](docs/PROJE_DOKUMANI.md). Progress: [`docs/PROGRESS.md`](docs/PROGRESS.md).

> Educational / personal research tool — **not investment advice** (doc §19).

## Stack
Python 3.11+ · FastAPI · arq + Redis · PostgreSQL · Parquet + DuckDB · vectorbt + backtesting.py · Optuna · TA-Lib + pandas-ta · Next.js 15 + TypeScript + Tailwind + lightweight-charts · Docker Compose.

## Getting started (skeleton)
```bash
# 1. Configure environment
cp .env.example .env          # then fill in real values (never commit .env)

# 2. Bring up all services (Phase 0+)
docker compose up --build     # frontend · api · worker · redis · postgres

# 3. Verify
curl http://localhost:8000/api/health   # expect 200

# 4. Local dev (optional, outside compose)
cd backend  && pytest && ruff check .    # backend tests + lint
cd frontend && pnpm install && pnpm dev  # UI at http://localhost:3000
```

> Build proceeds phase by phase (doc §15); acceptance criteria must pass before the next phase begins.
