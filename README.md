# MarketOS

An AI financial-intelligence and **paper trading** lab. MarketOS collects market data and financial news, groups news into events, asks an AI for structured investment hypotheses, runs approved hypotheses through deterministic risk rules into a simulated portfolio, and measures afterward whether each hypothesis was right.

**Simulation only.** MarketOS has no broker integration and never places real orders. `TRADING_MODE` accepts one value: `paper`.

The full design, including the database schema, provider choices, accounting rules and roadmap, is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Foundation: backend, frontend, PostgreSQL, Redis, Docker, config, health checks | done |
| 2 | Market data (Tiingo stocks, Coinbase crypto) | next |
| 3–10 | News, events, AI analysis, paper trading, dashboard, analytics, backtesting, hardening | planned |

## Run with Docker

```bash
cp .env.example .env        # optional: add API keys you have
docker compose up --build
```

| Service | URL |
|---|---|
| Web (system status page) | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Readiness | http://localhost:8000/health/ready |

Compose starts PostgreSQL, Redis, a one-shot migration job, the API, a Celery worker and Celery beat. Every service has a health check, and all ports bind to `127.0.0.1` only.

## Develop without Docker

Backend (Python 3.11+, needs PostgreSQL and Redis running):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.jobs.celery_app worker -B --loglevel=INFO   # worker + beat, for development
```

Frontend (Node 22):

```bash
cd frontend
npm install
API_INTERNAL_URL=http://localhost:8000 npm run dev
```

## Tests

```bash
# backend unit tests
cd backend && pytest
# plus integration tests against a real database and Redis
TEST_DATABASE_URL=postgresql+psycopg://marketos:marketos@localhost:5432/marketos_test \
TEST_REDIS_URL=redis://localhost:6379/1 pytest

# frontend
cd frontend && npm run lint && npm run typecheck && npm test
```

## Principles

- Every AI recommendation is stored, traded or not, and evaluated against what happened afterward.
- Decisions only see information that was available at the time (no lookahead).
- Trades and decisions are append-only; history is never rewritten.
- Money uses `Decimal` / `NUMERIC`, never floats.
- Missing data is recorded as missing; nothing is fabricated.
- API keys come from environment variables only.

## Data provider terms

Free tiers used by MarketOS are for personal, non-commercial use. Terms were checked on 2026-09-28 and are summarized in [docs/ARCHITECTURE.md §6](docs/ARCHITECTURE.md#6-data-and-news-providers); check the providers' pages before relying on them.
