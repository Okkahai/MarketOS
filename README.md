# MarketOS

An AI financial-intelligence and **paper trading** lab. MarketOS collects market data and financial news, groups news into events, asks an AI for structured investment hypotheses, runs approved hypotheses through deterministic risk rules into a simulated portfolio, and measures afterward whether each hypothesis was right.

**Simulation only.** MarketOS has no broker integration and never places real orders. `TRADING_MODE` accepts one value: `paper`.

The full design, including the database schema, provider choices, accounting rules and roadmap, is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Foundation: backend, frontend, PostgreSQL, Redis, Docker, config, health checks | done |
| 2 | Market data (Tiingo stocks, Coinbase crypto), indicators, Market and asset pages | done, needs live verification with a Tiingo key |
| 3 | News (Tiingo News, SEC EDGAR, Fed RSS), dedup, News feed page | done, needs live verification with `TIINGO_API_KEY` and `SEC_USER_AGENT` |
| 4 | Events: rule-based clustering, scoring, asset linking, Events page | done, threshold unproven on real headlines |
| 5 | AI analysis: context builder, triage + analysis, validated signals journal, cost budget, AI journal page | done. Default analyst is free and rule-based (`AI_PROVIDER=rules`); Claude is optional (`AI_PROVIDER=anthropic`, paid, needs a key and `AI_MODEL_PRICES`) |
| 6 | Paper trading: risk engine, fills, ledger, positions, reconciliation, Portfolio and Trades pages | done, simulation only |
| 7 | Dashboard: Overview page, signal trace (signal to risk verdict to trades), links everywhere | done |
| 8 | Analytics: signal evaluations, portfolio metrics against SPY, BTC and cash, Analytics page | done |
| 9–10 | Backtesting, hardening | planned |

## Run with Docker

```bash
cp .env.example .env        # optional: add API keys you have
docker compose up --build
```

| Service | URL |
|---|---|
| Web (system status, market, asset, news, events, AI journal pages) | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Readiness | http://localhost:8000/health/ready |

Compose starts PostgreSQL, Redis, a one-shot migration job, the API, a Celery worker and Celery beat. Every service has a health check, and all ports bind to `127.0.0.1` only.

Stock data and stock news need `TIINGO_API_KEY` in `.env` (free plan, personal use). SEC filings need `SEC_USER_AGENT` (your name and email); Federal Reserve feeds need nothing. Crypto candles come from Coinbase's public API and need no key. Without a key the stock job is recorded as `skipped` on the System status page; nothing is invented.

## Develop without Docker

Backend (Python 3.11+, needs PostgreSQL and Redis running):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
python -m app.market.seed      # the 14-asset MVP universe
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
