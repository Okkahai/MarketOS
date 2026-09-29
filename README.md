<div align="center">

# MarketOS

**An AI financial-intelligence lab with a paper-trading portfolio.**
It reads market data and news, turns them into hypotheses, trades them with virtual money, and then checks whether it was right.

`simulation only` · `no broker` · `no real orders` · `free to run`

</div>

> **MarketOS never touches real money.** There is no broker integration. `TRADING_MODE` accepts one value: `paper`.

---

## What it does

```mermaid
flowchart LR
    A[Market data<br/>Tiingo, Coinbase] --> D[Point-in-time<br/>context]
    B[News<br/>Tiingo, SEC EDGAR, Fed] --> C[Events<br/>clustered and scored]
    C --> D
    D --> E[Analyst<br/>rules by default]
    E --> F[(Signal journal<br/>every signal stored)]
    F --> G[Risk engine]
    G --> H[Paper portfolio<br/>$10,000 virtual]
    F --> I[Evaluation<br/>1, 3, 7, 30 days later]
    H --> I
    F -.-> J[Backtests<br/>same engine, past window]
```

1. **Collects** daily prices for 10 US stocks, SPY, QQQ, BTC-USD and ETH-USD, plus financial news, SEC filings and Federal Reserve releases.
2. **Groups** articles into events and scores their importance.
3. **Analyses** each event with the current prices and the portfolio in view, and writes a structured signal (BUY, HOLD, SELL, ...) with confidence, stop and target.
4. **Trades** the signal in a simulated portfolio through deterministic risk rules (position size, sector cap, cooldown, drawdown breaker). Fills happen at the next bar's open, with slippage and fees.
5. **Judges itself.** Every signal, traded or not, is evaluated later against what actually happened and against a benchmark (SPY for stocks, BTC for crypto).
6. **Replays history.** The same engine can run over a past window in an isolated portfolio (backtest).

### Principles

| Principle | What it means in the code |
|---|---|
| Every recommendation is stored | The signal journal is append-only; nothing is deleted or edited. |
| No lookahead | Every query filters on `available_at <= as_of`. A late-arriving bar cannot leak into an earlier decision (tested). |
| History is never rewritten | Trades, the cash ledger, risk decisions and snapshots are protected by database triggers. |
| Money is exact | `Decimal` / `NUMERIC` everywhere, never floats. |
| Failures are visible | Missing data is recorded as missing. Nothing is fabricated. |
| Secrets stay in the environment | API keys come from environment variables only. |
| Web content is data | Article text never becomes instructions to the analyst. |

## The analyst is free

The default analyst (`AI_PROVIDER=rules`) is a set of fixed rules, **not a trained model and not a paid API**:

- reads the tone of headlines from positive and negative word lists,
- refuses to chase overbought prices (RSI, 5-day move) and reacts to bad news on held positions,
- sets confidence, stop and target from fixed formulas.

It is deterministic, so backtests are repeatable. Its limit is honest: a word list does not understand context, so treat it as a baseline. The Analytics page shows whether it actually beats the benchmark.

A paid Claude analyst exists as an option (`AI_PROVIDER=anthropic`, needs a key and `AI_MODEL_PRICES`). It is off by default and refused in backtests, because a model trained after the window would know what happened.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Foundation: backend, frontend, PostgreSQL, Redis, Docker, health checks | done |
| 2 | Market data: Tiingo stocks, Coinbase crypto, indicators | done. **Stocks verified live** on 2026-09-29 |
| 3 | News: Tiingo News, SEC EDGAR, Fed RSS, dedup | done, live check pending |
| 4 | Events: clustering, scoring, asset linking | done, threshold unproven on real headlines |
| 5 | AI analysis: context builder, signal journal, cost budget | done, free rules analyst by default |
| 6 | Paper trading: risk engine, fills, ledger, reconciliation | done |
| 7 | Dashboard: overview, signal trace | done |
| 8 | Analytics: signal evaluation, portfolio metrics vs benchmarks | done |
| 9 | Backtesting: replay in an isolated portfolio | done |
| 10 | Hardening: job health alerts, security headers, failure-injection tests | done |

**Not yet proven:** Coinbase crypto data (blocked by some internet providers, see Troubleshooting), the news and SEC feeds on real data, and whether the analyst's signals have any edge. The system is built to measure the last one; give it a few weeks of running.

## Pages

| Page | Shows |
|---|---|
| System status | Service readiness, job runs, **alerts** for failed, stale or stuck jobs |
| Overview | Portfolio value, recent signals and trades |
| News feed / Events | Collected articles and the events they were grouped into |
| Market | Prices and indicators per asset |
| Portfolio / Trades | Positions, cash, every simulated trade and risk verdict |
| AI journal | Every signal with its reasoning and the exact context it saw |
| Analytics | Hit rate per horizon, return vs benchmark, Sharpe, drawdown |
| Backtests | Replays of past windows with their own equity curve and trades |

The API documentation is at `/docs` on the backend. A signal can be traced end to end at `/api/v1/signals/{id}/trace`.

## Quick start

You need two free credentials:

| Setting | Where to get it |
|---|---|
| `TIINGO_API_KEY` | Free account at [tiingo.com](https://www.tiingo.com), token under Account > API. Enables stock prices and news. |
| `SEC_USER_AGENT` | No signup. Your name and email, e.g. `Jane Doe jane@example.com`. SEC asks who is calling. |

Without a key the related job shows as `skipped`. Nothing is invented.

### With Docker

```bash
cp .env.example .env        # then fill in the two values above
docker compose up --build
```

| Service | URL |
|---|---|
| Web | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Readiness | http://localhost:8000/health/ready |

Compose starts PostgreSQL, Redis, a one-shot migration and seed job, the API, a Celery worker, Celery beat and the web app. All ports bind to `127.0.0.1` only.

### Without Docker

Needs Python 3.11+, Node 22, PostgreSQL 16 and Redis 7 running.

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
python -m app.market.seed                                  # the 14-asset universe
uvicorn app.main:app --reload
celery -A app.jobs.celery_app worker -B --loglevel=INFO    # second terminal: jobs + schedule

# frontend
cd frontend
npm install
API_INTERNAL_URL=http://localhost:8000 npm run dev
```

The backend reads `backend/.env`.

### Run a backtest

```bash
docker compose exec api python -m app.backtest --start 2026-08-01 --end 2026-09-28
```

Windows must lie fully in the past, and only news that was actually collected can be replayed, so backtests become useful after the system has run for a while.

## Configuration

Everything lives in `.env` (see `.env.example` for every setting and its comment).

| Group | Examples |
|---|---|
| Paper portfolio | `PAPER_INITIAL_CAPITAL`, `PAPER_MAX_POSITION_PCT`, `PAPER_MAX_SECTOR_PCT`, `PAPER_DRAWDOWN_BREAKER_PCT` |
| Execution costs | `PAPER_SLIPPAGE_BPS_*`, `PAPER_FEE_BPS_*` |
| Analyst | `AI_PROVIDER` (`rules` or `anthropic`), `AI_DAILY_BUDGET_USD` (paid mode only) |
| Schedules | `SCHEDULE_*_SECONDS` for every job, including `SCHEDULE_HEALTH_SECONDS` |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Docker Desktop: "Virtualization support not detected" | Virtualization is off. Enable Intel VT-x or AMD SVM in the BIOS, and turn on Virtual Machine Platform in Windows features. Or run without Docker. |
| `ingest_crypto_*` fails with an SSL error | Some internet providers block `api.exchange.coinbase.com`. Try a VPN. Stock data is unaffected. |
| A job shows `skipped` | Its key is missing in `.env`. |
| Alerts card lists a stale job | The worker or beat is not running, or the provider failed. Check the run table below it. |

## Tests

```bash
# unit tests
cd backend && pytest

# plus integration tests against real PostgreSQL and Redis
TEST_DATABASE_URL=postgresql+psycopg://marketos:marketos@localhost:5432/marketos_test \
TEST_REDIS_URL=redis://localhost:6379/1 pytest

# frontend
cd frontend && npm run lint && npm run typecheck && npm test
```

CI runs the backend and frontend checks and builds the full Docker stack on every pull request.

## Project layout

```
backend/app/
  providers/   Tiingo, Coinbase, SEC, Fed adapters (retry, rate limit, failure records)
  market/ news/ events/    ingestion, indicators, clustering
  ai/          context builder, rules analyst, optional Claude client, signal journal
  trading/     risk rules, fills, ledger, reconciliation
  analytics/   evaluations and portfolio metrics
  backtest/    replay runner and CLI
  monitor.py   job health alerts
  jobs/        Celery app, schedule, tasks
frontend/src/app/    Next.js pages
docs/ARCHITECTURE.md the full design
```

## Design document

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the database schema, accounting rules, risk rules, provider choices, roadmap, and a "left out on purpose" list for each phase. Notable omissions: provider fallback, API login and a shared rate limiter, none of which matter while the app runs on your own machine.

## Data provider terms

Free tiers used by MarketOS are for personal, non-commercial use. Terms were checked on 2026-09-28 and are summarized in [docs/ARCHITECTURE.md §6](docs/ARCHITECTURE.md#6-data-and-news-providers). Check the providers' pages before relying on them.

## Disclaimer

MarketOS is a research and learning tool. Nothing it produces is financial advice, and paper results do not predict real results.
