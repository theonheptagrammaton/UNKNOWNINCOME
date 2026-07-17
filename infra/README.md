# infra

Deployment notes for VDS · Docker · Coolify (doc §14).

## Services (`docker-compose.yml`)

| Service    | Role                    | Health signal                          |
| ---------- | ----------------------- | -------------------------------------- |
| `frontend` | Next.js UI              | `wget --spider http://localhost:3000/` |
| `api`      | FastAPI                 | `GET /api/health` → 200                |
| `worker`   | arq consumer            | Redis heartbeat key freshness          |
| `redis`    | queue + cache           | `redis-cli ping`                       |
| `postgres` | application state       | `pg_isready`                           |
| —          | `/data/parquet` volume  | market data + indicator cache          |

Coolify watches these healthchecks. `depends_on: condition: service_healthy`
enforces startup order (postgres/redis → api → frontend).

## Build metadata

`api` and `worker` accept a `GIT_SHA` build arg surfaced at `/api/health`.
Pass the short sha when building for a real value:

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose up --build
```

Without it, the sha falls back to `unknown` (no `.git` inside the image).

## Scheduled jobs (worker cron — later phases)

TF-close data sync · nightly discovery scan (optional) · weekly WFO
re-optimisation · daily Parquet/DB backup (doc §14). Defined in
`backend/app/workers/` as phases land here.
