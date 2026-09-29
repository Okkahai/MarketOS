# MarketOS Architecture

MarketOS is an AI financial-intelligence and **paper trading** platform. It never places real orders and never touches real money. Its purpose is to answer one question honestly:

> Why did the system make this decision, and what happened afterward?

Status: design baseline, written 2026-09-28. Phases 1 (foundation) and 2 (market data) are implemented; sections they changed say so. Later phases will update the sections they touch.

Contents

1. [Requirements analysis](#1-requirements-analysis)
2. [System architecture](#2-system-architecture)
3. [Repository structure](#3-repository-structure)
4. [Database schema](#4-database-schema)
5. [Data flow](#5-data-flow)
6. [Data and news providers](#6-data-and-news-providers)
7. [Paper trading accounting rules](#7-paper-trading-accounting-rules)
8. [AI structured-output schemas](#8-ai-structured-output-schemas)
9. [MVP risk rules](#9-mvp-risk-rules)
10. [MVP acceptance criteria](#10-mvp-acceptance-criteria)
11. [Implementation roadmap](#11-implementation-roadmap)

---

## 1. Requirements analysis

### What the system must do

| Capability | Core requirement | Why it is hard |
|---|---|---|
| Ingestion | Pull news, filings, macro data and prices from several providers | Providers fail, rate-limit, revise data and change terms |
| Normalization | One schema for every article, one schema for every bar | Sources disagree on timestamps, tickers and formats |
| Event detection | Many articles become one event | Needs dedup and clustering without an LLM for every article |
| AI analysis | Structured, validated hypotheses with evidence | LLM output is untrusted; inputs contain untrusted web text |
| Risk + execution | Deterministic rules decide; the LLM only proposes | Must be reproducible in backtest and in live paper mode |
| Accounting | Cash, positions, P&L, fees, slippage | Decimal precision, immutability, no rewriting history |
| Evaluation | Score every recommendation, traded or not | Must use only prices that arrived after the decision |
| Analytics | Returns, risk metrics, benchmarks, breakdowns | Must show losses as prominently as wins |
| Dashboard | Explain every decision from source to outcome | Traceability across ten tables |

### Non-negotiable properties

1. **Point-in-time correctness.** Every fact carries the time it became *knowable* to the system, not just the time it describes. Decisions and evaluations only read data knowable at the decision time. This is the property that makes the whole project meaningful; everything else is secondary to it.
2. **Append-only history.** Trades, journal entries, AI outputs and risk decisions are never updated or deleted. Corrections are new rows that reference the old ones.
3. **Deterministic execution.** Given the same signal, portfolio state, prices and config, the risk engine and trade engine produce the same result. No LLM call sits on that path.
4. **Explicit failure.** A missing price is recorded as missing. A provider outage is recorded as a failed run. Nothing is interpolated or invented to fill a chart.
5. **Decimal money.** Prices, quantities, cash, fees and P&L are `Decimal` in Python and `NUMERIC` in PostgreSQL. Floats are allowed only for statistics that are inherently approximate (Sharpe, volatility, correlations) and never flow back into balances.

### Stack evaluation

The suggested stack fits the requirements, so it is kept:

| Layer | Choice | Reason |
|---|---|---|
| Backend | Python 3.12 (3.11+ supported) + FastAPI | Python owns the data/quant ecosystem (pandas, numpy); FastAPI gives typed request/response models via Pydantic, which we also use for LLM output validation |
| ORM / migrations | SQLAlchemy 2.x + Alembic | Mature, explicit, supports PostgreSQL features we rely on (NUMERIC, JSONB, partial indexes, triggers) |
| Database | PostgreSQL 16 | Transactions, NUMERIC, JSONB for snapshots, triggers to enforce append-only tables. TimescaleDB can be added later for price hypertables without a schema rewrite |
| Jobs | Celery + Redis | Periodic jobs (beat), retries with backoff, per-queue workers. Redis doubles as the HTTP/LLM response cache and rate-limit store |
| Frontend | Next.js (App Router) + TypeScript | Server components for data-heavy pages, typed API client |
| Charts | TradingView Lightweight Charts (price/equity) + Recharts (bars, breakdowns) | Lightweight Charts is purpose-built for financial time series and is Apache-2.0 |
| LLM | Anthropic Claude API behind a provider interface | Structured output via tool/JSON schemas; interface allows other models later |
| Containers | Docker Compose | One command to run Postgres, Redis, API, worker, beat and web |

Celery was chosen over lighter options (APScheduler, RQ, Dramatiq) because the scheduling needs are periodic, the jobs need retries and routing to separate queues (cheap ingestion vs. expensive AI), and Celery beat covers that without another component. If job volume stays small, this can be revisited; the job functions themselves are plain Python and do not depend on Celery.

---

## 2. System architecture

### Layers

```
 ┌────────────────────────────────────────────────────────────────────┐
 │ Providers (Tiingo, Coinbase, SEC EDGAR, Fed RSS, FRED, ...)        │
 └──────────────┬────────────────────────────────┬────────────────────┘
                │ adapters (retry, rate limit,   │
                │ cache, raw payload archive)    │
 ┌──────────────▼─────────────┐   ┌──────────────▼─────────────┐
 │ 1. News ingestion          │   │ 4. Market data ingestion   │
 │ 2. Normalization + dedup   │   │    raw bars (market_prices)│
 │ 3. Event detection         │   │    derived indicators      │
 └──────────────┬─────────────┘   └──────────────┬─────────────┘
                └───────────────┬────────────────┘
                   ┌────────────▼─────────────┐
                   │ Context builder          │  point-in-time snapshot
                   │ (as_of = decision time)  │  of everything knowable
                   └────────────┬─────────────┘
                   ┌────────────▼─────────────┐
                   │ 5. AI analyst            │  LLM proposes, schema-validated
                   └────────────┬─────────────┘
                   ┌────────────▼─────────────┐
                   │ 6. Signal generation     │  normalized, journaled always
                   └────────────┬─────────────┘
                   ┌────────────▼─────────────┐
                   │ 7. Risk engine           │  deterministic approve/resize/reject
                   └────────────┬─────────────┘
                   ┌────────────▼─────────────┐
                   │ 8. Paper trading engine  │  fills, fees, slippage, ledger
                   └────────────┬─────────────┘
                   ┌────────────▼─────────────┐
                   │ 9. Portfolio + snapshots │
                   └────────────┬─────────────┘
                   ┌────────────▼─────────────┐
                   │ 10. Evaluation+analytics │  forward returns, MFE/MAE, metrics
                   └────────────┬─────────────┘
                   ┌────────────▼─────────────┐
                   │ 11. API  →  Dashboard    │
                   └──────────────────────────┘
```

### Module boundaries

Each layer is a Python package under `backend/app/` with a narrow public interface. Layers communicate through database rows and typed domain objects, never by importing each other's internals.

| Package | Owns | Reads | Must not |
|---|---|---|---|
| `providers/` | HTTP clients, auth, rate limiting, retries, raw payloads | env config | know about events, signals or portfolios |
| `news/` | articles, dedup, source registry | providers | call an LLM for every article |
| `events/` | clustering, importance scoring, asset linking | articles, assets | trade |
| `market/` | assets, bars, indicators | providers | use bars before they are closed |
| `context/` | point-in-time snapshot builder | everything, filtered by `as_of` | read anything with `available_at > as_of` |
| `ai/` | prompts, LLM client, schema validation, cost tracking, cache | context snapshots | write to portfolios, positions or trades |
| `signals/` | signal normalization, journal | AI analyses | execute |
| `risk/` | deterministic rules, risk decisions | signals, portfolio state, config | call an LLM |
| `trading/` | fills, trades, positions, cash ledger | approved risk decisions, prices | modify history |
| `analytics/` | snapshots, evaluations, metrics, benchmarks | trades, prices | alter anything it measures |
| `jobs/` | Celery tasks, schedules, `system_runs` bookkeeping | all | contain business logic (tasks call service functions) |
| `api/` | HTTP routes, response models | services | contain business logic |

### Clock abstraction (live vs. backtest)

Every service receives a `Clock` instead of calling `datetime.now()`. `LiveClock` returns wall time; `ReplayClock` returns the simulated time during a backtest. Every query for "latest" data takes an explicit `as_of` and filters on `available_at <= as_of`. This single rule is what lets the same signal, risk and trade code run in live paper mode and in historical backtest mode (Section 11, Phase 9).

---

## 3. Repository structure

```
MarketOS/
├── README.md
├── docker-compose.yml             # postgres, redis, api, worker, beat, web
├── .env.example                   # every setting, no secrets
├── .github/workflows/ci.yml       # backend + frontend checks
├── docs/
│   ├── ARCHITECTURE.md            # this document
│   └── adr/                       # architecture decision records (added as decisions change)
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/          # migrations, one per schema change
│   ├── app/
│   │   ├── main.py                # FastAPI app factory
│   │   ├── core/                  # config, logging, clock, money (Decimal) helpers
│   │   ├── db/                    # engine, session, declarative base
│   │   ├── models/                # SQLAlchemy models, one module per aggregate
│   │   ├── schemas/               # Pydantic API + domain schemas
│   │   ├── api/routes/            # health, system, market, news, events, signals, portfolio, ...
│   │   ├── providers/             # base adapter + one module per provider
│   │   ├── news/                  # normalization, dedup
│   │   ├── events/                # clustering, scoring, asset linking
│   │   ├── market/                # bars, indicators
│   │   ├── context/               # point-in-time snapshot builder
│   │   ├── ai/                    # llm client, prompts, output schemas, cost tracking
│   │   ├── signals/
│   │   ├── risk/
│   │   ├── trading/
│   │   ├── analytics/
│   │   ├── backtest/
│   │   └── jobs/                  # celery app, beat schedule, tasks
│   └── tests/
│       ├── unit/
│       └── integration/           # run against a real PostgreSQL
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── src/app/                   # Next.js App Router pages
    │   ├── page.tsx               # Overview
    │   ├── news/  market/  asset/[symbol]/  portfolio/  trades/  journal/  analytics/  system/
    ├── src/components/
    └── src/lib/                   # typed API client, formatters
```

Packages that have no code yet are created in the phase that fills them, so the tree never contains empty placeholders.

---

## 4. Database schema

### Timestamp conventions

All timestamps are `TIMESTAMPTZ` stored in UTC.

| Column | Meaning |
|---|---|
| `published_at` | When the source says the item was published (source claim, may be wrong) |
| `collected_at` | When MarketOS fetched it |
| `available_at` | When MarketOS may *use* it. For news: `collected_at` in live mode; in backtests, `max(published_at, collected_at)` of the earliest honest record, never earlier than `published_at`. For bars: bar close time (`ts + interval`), never bar open |
| `created_at` | Row insert time |

Point-in-time queries always filter on `available_at <= as_of`.

### Numeric conventions

| Kind | Type |
|---|---|
| Prices | `NUMERIC(24, 10)` |
| Quantities | `NUMERIC(28, 12)` |
| Cash, values, P&L, fees | `NUMERIC(24, 8)` |
| Ratios, weights, confidence | `NUMERIC(9, 6)` |
| Basis points config | `INTEGER` |

### Entity relationship overview

```
news_sources 1─* news_articles *─* events (via event_sources)
events *─* assets (via event_assets)
assets 1─* market_prices
assets 1─* indicator_values
ai_analyses *─* events (via analysis_events)      ai_analyses 1─1 context_snapshots
ai_analyses 1─* signals
signals 1─1 risk_decisions
risk_decisions 0..1─* trades
portfolios 1─* trades, positions, portfolio_snapshots, cash_ledger
positions 1─* trades
signals 1─* performance_evaluations
system_runs 1─* (any row produced by a job, via run_id)
```

### Tables

Only columns that carry meaning are listed; every table also has `id` (UUID v7, time-ordered) and `created_at`.

**assets**

| column | type | notes |
|---|---|---|
| symbol | text | globally unique (`AAPL`, `BTC-USD`; crypto pairs carry the quote currency so they cannot collide with a stock ticker) |
| asset_class | text + check constraint | `stock`, `etf`, `crypto`; later `index`, `fx`, `commodity`, `bond` (a check constraint instead of a PostgreSQL enum, so adding a class is a simple migration) |
| name, exchange, currency | text | |
| sector, industry | text null | used by sector risk limits |
| provider_symbols | jsonb | `{"tiingo": "AAPL"}` or `{"coinbase": "BTC-USD"}` |
| is_active, is_benchmark | bool | benchmarks (SPY, QQQ, BTC-USD) are ordinary assets whose bars are collected the same way |

**market_prices** (raw bars, append-only; a correction is a new row with a higher `revision`). Implemented in Phase 2; the database rejects `UPDATE` and `DELETE` with a trigger.

| column | type | notes |
|---|---|---|
| asset_id | fk | |
| interval | text + check | `1m`, `5m`, `1h`, `1d` |
| ts | timestamptz | bar start. Stocks' daily bars are labelled with the trading date at 00:00 UTC (the provider gives a date, not an open time) |
| open, high, low, close | numeric | check constraint: `low > 0`, `high >= low`, open and close inside the range |
| adj_close | numeric null | provider adjusted close, stocks only |
| volume | numeric | |
| provider | text | |
| available_at | timestamptz | when the bar may be used (see below) |
| revision | int | 0 for first observation |
| run_id | fk system_runs | |

Unique `(asset_id, interval, ts, provider, revision)`. Index `(asset_id, interval, available_at)`.

`available_at` rules (Phase 2):

- Stock daily bar: 20:00 America/New_York on the trading date. Tiingo says most US prices are available at 5:30 PM ET and that exchanges may send corrections until 8 PM ET, so bars are used only after the corrections window. This is conservative on early-close days.
- Crypto bar: bar close plus 5 seconds, because exchange candles can receive late trades just after the close.
- A revision's `available_at` is the moment it was fetched (`max(now, nominal)`), because the corrected value was not knowable earlier.
- A bar whose `available_at` is still in the future is never stored. This is what keeps in-progress candles and provisional end-of-day prints out.
- `get_bars(as_of)` returns, per `ts`, the highest revision with `available_at <= as_of`.

**indicator_values** (derived, recomputable, separate from raw data). Implemented in Phase 2.

`asset_id, interval, ts, name (rsi_14, sma_50, atr_14, ...), value numeric, params jsonb, computed_from_available_at, code_version`. Unique `(asset_id, interval, ts, name, code_version)`, upserted. Never read by accounting. Only daily indicators are stored, and only the newest `INDICATOR_STORE_BARS` per asset. Decisions and backtests must compute indicators from `get_bars(as_of)` instead of reading this table, which is a dashboard cache.

**news_sources**

`key (unique, e.g. sec_edgar_8k), name, kind (api|rss|filing|macro), base_url, reliability_weight numeric, is_enabled, terms_note text`.

**news_articles**

| column | type | notes |
|---|---|---|
| source_id | fk | |
| external_id | text | provider id if any |
| url, canonical_url | text | |
| title, summary | text | summary is provider-supplied or extractive, not LLM by default |
| published_at, collected_at, available_at | timestamptz | |
| category | enum | `company`, `earnings`, `central_bank`, `filing`, `macro`, `commodities`, `geopolitics`, `crypto`, `other` |
| countries, companies, tickers | text[] | extracted deterministically first |
| title_norm | text | lowercased words of the title; what dedup compares |
| content_hash | text | sha256 of `title_norm` |
| duplicate_of_id, dedup_reason | fk self null, text null | set on insert when a copy is found (`same_url`, `same_title`, `similar_title`); the row is kept |
| sentiment, importance | numeric null | null until computed; never defaulted |
| raw_payload | jsonb | original provider payload, for audit |
| run_id | fk | |

Unique `(source_id, external_id)` and unique `(source_id, canonical_url)`. Check constraints: `available_at >= collected_at`, and a `dedup_reason` needs a `duplicate_of_id`. `body_excerpt`, `language` and `simhash` from the first design were dropped: no source supplies a body we may store, all three sources are English, and title Jaccard was enough (see Phase 3 notes).

**events**

`title, summary, category, importance numeric(0..1), confidence numeric(0..1), countries text[], sectors text[], horizon enum (intraday|days|weeks|months), first_seen_at, last_updated_at, available_at, status (open|closed), method (rule|embedding|llm), method_version, score_details jsonb, run_id`. Check constraints on every enum and range, and `available_at <= last_updated_at`.

The row is the state as of the newest article. It is a cache for the dashboard, not a point-in-time record: `first_seen_at` is the earliest `published_at` of its articles, `available_at` the earliest `available_at`, `last_updated_at` the latest. Anything that must know the event as of an earlier time (the Phase 5 context builder, backtests) calls `state_as_of(event_id, as_of)`, which rebuilds it from `event_sources` joined to `news_articles.available_at <= as_of`. The events API does the same when given `as_of`.

**event_sources** `event_id, article_id, added_at, similarity numeric` (PK on both ids, plus a unique index on `article_id`: an article belongs to one event). Duplicate copies of an article (Phase 3) join the event of their original, because a copy from another outlet is corroboration.

**event_assets** `event_id, asset_id, relevance numeric (share of the event's articles tagged with the asset), direction_hint (up|down|mixed|unknown), linked_by (rule|llm), rationale`. Derived and rebuilt whenever the event changes. `direction_hint` is always `unknown` until Phase 5 supplies sentiment.

**context_snapshots** (the exact information the AI saw)

`as_of timestamptz, payload jsonb, payload_sha256, builder_version`. Immutable (a database trigger rejects UPDATE and DELETE). The payload lists every article id, event id, bar and indicator value included, with their `available_at`, so a reviewer can prove nothing came from the future.

**ai_analyses**

| column | type | notes |
|---|---|---|
| context_snapshot_id, event_id | fk | one snapshot per model call |
| stage | enum | `triage` or `analysis` |
| as_of | timestamptz | decision time |
| model, model_version, prompt_version | text | |
| request_hash | text | cache key |
| raw_output | jsonb | exactly what the model returned |
| parsed_output | jsonb null | after schema validation |
| validation_status | enum | `valid`, `invalid`, `refused`, `error` |
| validation_errors | jsonb null | |
| input_tokens, output_tokens | int | |
| estimated_cost_usd | numeric(12,6) | from the operator's `AI_MODEL_PRICES`; 0 for a call that failed before the model answered |
| latency_ms | int | |
| run_id | fk | |

Append-only, like the snapshots. A repeated identical request is not stored again: it is answered from the earlier row (see Phase 5 notes), so there is no `cache_hit` column. `analysis_events` was dropped because every analysis is about exactly one event (`event_id`).

**signals** (the decision journal; one row per asset recommendation, stored whether or not anything trades)

| column | type | notes |
|---|---|---|
| analysis_id | fk | |
| asset_id | fk | |
| generated_at | timestamptz | = analysis `as_of` |
| action | enum | `STRONG_BUY`, `BUY`, `HOLD`, `REDUCE`, `SELL`, `AVOID` |
| direction | enum | derived: `long`, `flat`, `exit` |
| confidence | numeric | |
| time_horizon | text | `1d`, `3d`, `7d`, `30d` |
| reference_price | numeric | last price available at `generated_at` |
| reference_price_ts | timestamptz | its bar close |
| thesis, bull_case, bear_case | text | |
| key_catalysts, risks, invalidation_conditions | jsonb | |
| supporting_event_ids | uuid[] | |
| suggested_position_size_pct, suggested_stop_loss_pct, suggested_take_profit_pct | numeric | |
| portfolio_context | jsonb | cash, positions and exposure at decision time |
| mode | enum | `live_paper`, `backtest` |
| backtest_run_id | fk null | |

**risk_decisions**

`signal_id (unique), decided_at, outcome (approved|resized|rejected|no_action), approved_notional numeric, approved_quantity numeric, rules_evaluated jsonb (each rule: name, input values, limit, pass/fail), rejection_reasons text[], config_snapshot jsonb, engine_version`.

**portfolios**

`name, mode, base_currency, initial_capital, risk_config jsonb, started_at, backtest_run_id null`. Multiple portfolios are supported by the schema from day one even though the MVP uses one.

**trades** (append-only, enforced by a trigger that rejects `UPDATE` and `DELETE`)

| column | type | notes |
|---|---|---|
| portfolio_id, asset_id, position_id | fk | |
| risk_decision_id | fk null | null only for rule exits (stop-loss, take-profit) |
| trigger | enum | `signal`, `stop_loss`, `take_profit`, `rebalance`, `manual_sim` |
| side | enum | `BUY`, `SELL` |
| quantity | numeric | |
| reference_price | numeric | price before slippage |
| execution_price | numeric | after slippage |
| price_ts, price_source | | which bar/quote was used |
| gross_value | numeric | quantity × execution_price |
| fee | numeric | |
| slippage_cost | numeric | quantity × abs(execution − reference) |
| realized_pnl | numeric null | sells only |
| cash_after | numeric | |
| executed_at | timestamptz | simulated fill time |
| reason | text | |
| confidence | numeric null | copied from signal for audit convenience |

**cash_ledger** (append-only) `portfolio_id, ts, amount (signed), balance_after, kind (deposit|trade|fee), trade_id null`. Cash is the sum of this ledger; `portfolios` stores no mutable cash column.

**positions** (the only mutable accounting table; its state must always be reproducible from `trades`)

`portfolio_id, asset_id, status (open|closed), opened_at, closed_at, quantity, avg_cost, cost_basis, realized_pnl, stop_loss_price, take_profit_price, opening_signal_id`. One open position per (portfolio, asset), enforced by a partial unique index.

**portfolio_snapshots**

`portfolio_id, ts, cash, positions_value, total_value, invested_cost, realized_pnl_cum, unrealized_pnl, fees_cum, holdings jsonb (per asset: qty, price, price_ts, value), price_staleness jsonb, is_complete bool`. If any holding lacks a fresh price, `is_complete = false` and the missing symbols are listed; the value is not estimated.

**performance_evaluations** (append-only; one row per signal per horizon)

`signal_id, horizon (1d|3d|7d|30d), evaluated_at, start_price, start_price_ts, end_price, end_price_ts, return_pct, mfe_pct, mae_pct, benchmark_return_pct, excess_return_pct, direction_correct bool null, status (complete|insufficient_data|pending)`. Only bars with `available_at > signal.generated_at` and `ts <= generated_at + horizon` are used.

**system_runs** (every job execution, success or failure)

`job_name, started_at, finished_at, status (running|succeeded|partial|failed|skipped), provider, items_fetched, items_written, error_type, error_message, details jsonb`.

**provider_failures** `run_id, provider, endpoint (path only, never the query string), subject (e.g. the symbol), http_status, error_type, error, retry_count, occurred_at`. A failed fetch leaves a row here and nothing in the data tables. Bars rejected by validation are recorded here too, with `error_type = RejectedBars`. Implemented in Phase 2.

### Traceability chain

```
news_sources → news_articles → event_sources → events → analysis_events → ai_analyses
  → context_snapshots (what the AI saw) → signals → risk_decisions → trades → positions
  → portfolio_snapshots, performance_evaluations
```

The API exposes `GET /api/v1/signals/{id}/trace` which walks this chain in one call; the asset and journal pages are built on it.

---

## 5. Data flow

### Live paper mode (per scheduled cycle)

1. **Prices job** fetches bars for active assets. Each provider call is a `system_runs` row. Bars are inserted with `available_at = bar close`. Failures go to `provider_failures`; no bar is written.
2. **Indicators job** recomputes indicators for assets with new bars. Pure functions over pandas; results written to `indicator_values`.
3. **News job** fetches each enabled source, normalizes, computes `content_hash` and `simhash`, drops exact duplicates, links near-duplicates via `duplicate_of_id`, extracts tickers deterministically (cashtags, company-name dictionary, SEC CIK map).
4. **Event job** clusters non-duplicate articles from a rolling window: first by shared tickers + time proximity + title similarity (deterministic), later with embeddings. Scores importance from source reliability, source count, category weight and ticker relevance to the watchlist.
5. **Analysis job** selects events with `importance >= AI_MIN_EVENT_IMPORTANCE` that have not been analyzed at their current version, respecting the daily AI budget. For each, the context builder produces a snapshot `as_of = now`. A cheap model triages; only events that pass go to the main model. Output is validated; invalid output is stored with errors and produces no signal.
6. **Signal step** writes one `signals` row per asset in the validated output, including HOLD and AVOID.
7. **Risk step** evaluates each signal against the portfolio state at `as_of` and writes a `risk_decisions` row for every signal.
8. **Trade step** fills approved decisions at the next available price (Section 7), writes `trades`, `cash_ledger`, and updates `positions` in one database transaction.
9. **Exit job** checks open positions against stop-loss and take-profit using closed bars only.
10. **Snapshot job** values the portfolio and writes `portfolio_snapshots`.
11. **Evaluation job** finds signals whose horizons have elapsed and writes `performance_evaluations`.
12. **Daily report job** aggregates metrics for the dashboard.

Every job runs through a `run_job()` wrapper that opens a `system_runs` row, catches and records exceptions, and marks the run `partial` when some providers failed but others succeeded.

### Untrusted content boundary

Article text and filing text are data. Before reaching the LLM they are truncated, stripped of markup, and placed inside clearly delimited fields of a JSON payload. The system prompt tells the model that instructions inside those fields must be ignored. More importantly, the model has no tools and no write access: the worst a prompt injection can do is produce a bad signal, which the risk engine still bounds and the journal still records.

### Backtest mode

A backtest replays a historical window with a `ReplayClock`. At each step it runs steps 4–11 using only rows whose `available_at <= clock.now()`. Signals, risk decisions and trades are written with `mode = backtest` and a `backtest_run_id`, into their own portfolio. For historical AI analysis the cached analysis for the same `request_hash` is reused when it exists; otherwise the run records that analysis was unavailable instead of calling a model with hindsight. Macro series use ALFRED vintages so that revised figures are not seen before they were published.

---

## 6. Data and news providers

Terms and limits below were checked on 2026-09-28 against the providers' own pricing and documentation pages. Free tiers change often, so each adapter reads its limits from config, and the README links to the source pages.

All free tiers listed are for personal, non-commercial use. That fits a private paper-trading lab. If MarketOS is ever offered to other people, every provider below needs a commercial plan first.

### Market data

| Role | Provider | Free-tier terms (as checked) | Why |
|---|---|---|---|
| **Stocks, primary** | [Tiingo](https://www.tiingo.com/about/pricing) | 50 requests/hour, 1,000/day, 500 unique symbols/month, 1 GB/month, 30+ years of EOD history; internal personal use only | Clean adjusted daily bars with a long history, which matters for evaluation and backtests. 12 symbols per day is far inside the limit |
| Stocks, fallback | [Alpha Vantage](https://www.alphavantage.co/premium/) | 25 requests/day free | Independent second source for cross-checks and outages. Too limited to be primary |
| **Crypto, primary** | [Coinbase Exchange public API](https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits) | Public market-data endpoints need no key; 10 requests/second per IP, bursts to 15 | Real exchange candles for BTC-USD and ETH-USD at 1m to 1d, no key to manage |
| Crypto, fallback | [CoinGecko Demo API](https://www.coingecko.com/en/api/pricing) | 100 calls/minute, 10,000 call credits/month, 1 year of daily history; attribution required; non-commercial | Aggregated price across exchanges; used when Coinbase fails and for cross-checks. Attribution goes in the dashboard footer when it is enabled |
| Benchmarks | Tiingo (SPY, QQQ) and Coinbase (BTC-USD) | as above | SPY and QQQ are tradable proxies for the S&P 500 and NASDAQ-100 and have adjusted closes (dividends included). Index levels themselves are not freely licensed |

Daily bars are the MVP's decision interval for stocks. Intraday bars are supported by the schema and adapters but not required for the MVP.

### News and information

| Role | Provider | Terms (as checked) | Why |
|---|---|---|---|
| **Company and market news** | Tiingo News API | Included with the Tiingo key; 3 months of queryable history on the free plan | Ticker-tagged articles with publish times from many outlets, one key shared with prices |
| **Regulatory filings** | [SEC EDGAR](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) | Free, no key; max 10 requests/second; a `User-Agent` header with a name and contact email is required | Primary-source 8-K, 10-Q and 10-K filings with exact acceptance timestamps. Highest reliability weight |
| **Central bank** | Federal Reserve press-release RSS feeds | Free public RSS | Primary source for FOMC statements and policy decisions |
| **Macro indicators** | FRED / ALFRED (St. Louis Fed) | Free with an API key; ALFRED exposes vintage dates for every revision | CPI, unemployment, GDP, rates. ALFRED vintages make macro data lookahead-safe |
| Company news, optional | Finnhub | Free tier around 60 calls/minute with company news; non-commercial | Second news source for cross-source confirmation once the pipeline is stable |

Deliberately not used: scraping publisher websites (fragile and often against terms), unofficial Yahoo Finance wrappers (no license for this use), and social media (deferred to the future-features list).

This build environment cannot reach these hosts (its network policy blocks them), so endpoint behaviour will be verified against live responses at the start of Phases 2 and 3, and adapters will record any difference from the table above.

---

## 7. Paper trading accounting rules

1. **Simulation only.** No broker integration exists in the codebase. The trading package has no network access.
2. **Initial capital** is a configurable deposit (default 10,000 USD) written as the first `cash_ledger` row.
3. **Long-only, cash-only in the MVP.** No short selling, no leverage, no margin, no derivatives. `SELL` and `REDUCE` only act on existing positions. Cash can never go negative; a trade that would make it negative is rejected by the risk engine and, as a second guard, by a database check.
4. **Fill price.** A signal generated at time *t* fills at the first price that becomes available *after* *t*:
   - Stocks (daily bars): the open of the next trading session.
   - Crypto: the open of the next 1-minute bar in live mode, next daily open in daily backtests.
   - The bar used (`price_ts`, `price_source`) is stored on the trade. If no such price exists yet, the order waits as pending (up to a configurable expiry) and expires without a fill if none arrives. It is never filled at a guessed price.
5. **Slippage** is adverse and configurable in basis points per asset class: `execution = reference × (1 + bps/10,000)` for buys and `× (1 − bps/10,000)` for sells. Defaults: 5 bps stocks, 10 bps crypto.
6. **Fees**: `fee = max(min_fee, gross_value × fee_bps / 10,000)`. Defaults: stocks 0 bps with 0 minimum (typical commission-free broker) plus slippage; crypto 40 bps. All configurable.
7. **Quantity**: fractional quantities are allowed (stocks to 6 decimals, crypto to 8) so that a 10,000 USD portfolio can hold small, correctly sized positions. Quantity is rounded *down*, never up.
8. **Cost basis** uses the average-cost method:
   - Buy: `new_avg = (old_qty × old_avg + buy_qty × exec_price + fee) / (old_qty + buy_qty)`. Buy fees are capitalized into cost basis.
   - Sell: `realized = sell_qty × exec_price − fee − sell_qty × avg_cost`. `avg_cost` is unchanged by sells.
9. **Unrealized P&L** = `qty × mark_price − qty × avg_cost`, where `mark_price` is the latest close with `available_at <= as_of`. Stale marks (older than a configurable limit) are flagged, not replaced.
10. **Total value** = cash + Σ(qty × mark). Invested capital = Σ cost basis of open positions.
11. **Rounding**: calculations use `Decimal` with 28 significant digits; stored money is quantized to 8 decimals with `ROUND_HALF_EVEN`; display rounds to cents.
12. **Atomicity**: trade row, cash ledger rows and position update commit in one transaction or not at all.
13. **Immutability**: `trades`, `cash_ledger`, `signals`, `risk_decisions`, `ai_analyses`, `context_snapshots` and `performance_evaluations` reject `UPDATE` and `DELETE` via triggers. A mistaken trade is corrected by a new, explicitly labelled reversing trade, never by editing.
14. **Reconciliation**: a job rebuilds positions and cash from the append-only tables and alerts on any mismatch with the `positions` table.
15. **Stop-loss / take-profit**: evaluated on closed bars. If a bar's low crosses the stop, the exit fills at the stop price or the bar's open if it gapped through (the worse of the two). The same rule applies symmetrically to take-profit using the better of target and open only when the open gapped past the target.

---

## 8. AI structured-output schemas

All schemas are Pydantic models; the JSON Schema sent to the model is generated from them, and the model's output is validated against the same model. Anything that fails validation is stored with its errors and produces no signal.

### Input (built by the context builder, never raw web pages)

```json
{
  "as_of": "2026-09-28T14:30:00Z",
  "event": {
    "id": "…", "title": "…", "category": "central_bank", "importance": 0.82,
    "first_seen_at": "…",
    "sources": [{"source": "federal_reserve_rss", "published_at": "…", "title": "…", "excerpt": "…"}]
  },
  "candidate_assets": [
    {
      "symbol": "QQQ", "asset_class": "etf",
      "last_close": "512.34", "last_close_ts": "…",
      "returns": {"1d": "0.0041", "5d": "-0.012", "20d": "0.034"},
      "indicators": {"rsi_14": "58.2", "atr_14_pct": "0.013", "sma_50_gap_pct": "0.021"},
      "realized_vol_20d": "0.18"
    }
  ],
  "portfolio": {"cash_pct": "0.62", "positions": [{"symbol": "NVDA", "weight": "0.08", "unrealized_pct": "0.031"}]},
  "related_past_events": [{"title": "…", "date": "…", "asset_moves_after": {"QQQ_5d": "0.018"}}],
  "market_regime": {"spy_above_sma200": true, "vix_proxy": null}
}
```

Unknown values are `null`, never estimated.

### Output: `AnalysisResult`

```json
{
  "event_id": "uuid",
  "event_assessment": {
    "summary": "string, ≤ 600 chars",
    "market_relevance": "high | medium | low | none",
    "expected_horizon": "intraday | days | weeks | months"
  },
  "signals": [
    {
      "asset": "QQQ",
      "action": "STRONG_BUY | BUY | HOLD | REDUCE | SELL | AVOID",
      "confidence": 0.72,
      "time_horizon": "1d | 3d | 7d | 30d",
      "thesis": "string",
      "bull_case": "string",
      "bear_case": "string",
      "key_catalysts": ["string"],
      "risks": ["string"],
      "supporting_events": ["uuid"],
      "evidence": [{"source_article_id": "uuid", "quote_or_fact": "string"}],
      "invalidation_conditions": ["string"],
      "suggested_position_size_pct": 4,
      "suggested_stop_loss_pct": 5,
      "suggested_take_profit_pct": 10
    }
  ],
  "no_trade_reason": "string | null"
}
```

Validation rules beyond types:

- `asset` must be one of the `candidate_assets` symbols (the model cannot invent tickers).
- `supporting_events` and `evidence[].source_article_id` must be ids present in the input.
- `confidence` in [0, 1]; percentages in [0, 100]; `suggested_stop_loss_pct` > 0 when action is a buy.
- `thesis`, `bear_case` and `invalidation_conditions` are required for every non-HOLD action.
- At most `AI_MAX_SIGNALS_PER_ANALYSIS` signals.
- Numbers in the output are advisory; the risk engine applies its own caps regardless.

### Triage output (cheap model)

```json
{"event_id": "uuid", "relevant": true, "reason": "string ≤ 200 chars", "candidate_symbols": ["QQQ", "SPY"]}
```

### Cost tracking

Each call writes model, prompt version, input/output tokens, estimated cost (from a price table in config, since prices change), latency and cache hit to `ai_analyses`. A daily budget (`AI_DAILY_BUDGET_USD`) stops non-essential analysis when reached, and the stop is itself recorded as a skipped run.

---

## 9. MVP risk rules

The risk engine is a list of pure functions `rule(signal, portfolio_state, market_state, config) -> RuleResult`. Every rule's inputs and result are stored in `risk_decisions.rules_evaluated`, so a rejection can always be explained. Defaults below are configuration, not code.

| # | Rule | Default | Effect |
|---|---|---|---|
| 1 | Action filter | only `BUY`/`STRONG_BUY` open or add; `SELL` closes; `REDUCE` sells 50%; `HOLD`/`AVOID` never trade | no_action |
| 2 | Minimum confidence | 0.60 (`STRONG_BUY` needs 0.75) | reject |
| 3 | Signal freshness | price used must be ≤ 1 trading day old for stocks, ≤ 15 min for crypto live | reject |
| 4 | Max allocation per asset | 10% of total value | resize down |
| 5 | Max allocation per sector | 30% | resize down / reject |
| 6 | Max crypto exposure | 25% | resize down / reject |
| 7 | Minimum cash reserve | 10% | resize down / reject |
| 8 | Max open positions | 8 | reject new opens |
| 9 | Position size | `min(signal suggested %, rule 4 cap)`; minimum trade 50 USD | reject if below minimum |
| 10 | Cooldown | 24 h between trades in the same asset, both directions | reject |
| 11 | Max new trades per day | 5 | reject |
| 12 | Stop-loss | required on every entry; `min(signal %, 10%)`, default 8% | set on position |
| 13 | Take-profit | optional; signal % capped at 30% | set on position |
| 14 | Drawdown circuit breaker | if portfolio is 20% below its peak, stop new entries (exits still allowed) | reject |
| 15 | Data completeness | reject if the last snapshot is incomplete or any required price is missing | reject |

Order: filters that reject (1, 2, 3, 8, 10, 11, 14, 15) run first, then sizing rules (4 to 7, 9) take the minimum allowed size, then 12 and 13 attach exits.

---

## 10. MVP acceptance criteria

The MVP is accepted when all of these are demonstrably true on a running Docker Compose stack.

**Universe and data**

- [ ] 12 assets tracked: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, AMD, NFLX, BTC-USD, ETH-USD, plus benchmarks SPY, QQQ.
- [ ] Daily bars for all stocks and daily + 1-minute bars for crypto are collected on schedule, with `available_at` set to bar close.
- [ ] Stopping one provider (e.g. invalid key) produces failed `system_runs` rows and a visible warning, while other providers keep working. No data is invented for the failed provider.

**News and events**

- [ ] At least three sources ingest on schedule (Tiingo News, SEC EDGAR, Fed RSS).
- [ ] Re-ingesting the same window creates zero new articles (dedup test).
- [ ] Articles about the same event from different sources end up in one event.

**AI and signals**

- [ ] Only events above the importance threshold reach the main model; triage and cost per call are recorded.
- [ ] Every analysis stores its context snapshot; the snapshot contains nothing with `available_at > as_of` (automated test).
- [ ] Invalid model output is stored and produces no signal.
- [ ] Every signal, including HOLD and AVOID, is in the journal with a risk decision.

**Paper trading**

- [ ] Starting capital 10,000 USD; cash, positions, fees and slippage reconcile exactly with the trade history (reconciliation job reports zero drift).
- [ ] Attempts to update or delete a trade fail at the database level.
- [ ] Each rule in Section 9 has a test that shows it rejecting or resizing a signal.

**Evaluation and analytics**

- [ ] Every signal older than its horizon has 1d/3d/7d evaluations with MFE/MAE, or an explicit `insufficient_data` status.
- [ ] Dashboard shows portfolio vs. SPY vs. BTC vs. cash, win rate, profit factor, max drawdown, Sharpe and Sortino, and shows losing trades and wrong predictions in the same lists as winning ones.

**Explainability**

- [ ] From any position, the UI reaches the signal, the thesis, the evidence articles, the risk decision and the evaluation in at most two clicks.

---

## 11. Implementation roadmap

Each phase ends with passing tests, a PR, and an update to this document if a decision changed.

| Phase | Scope | Key deliverables | Exit check |
|---|---|---|---|
| **1. Foundation** | Repo, backend, frontend, Postgres, Redis, Docker, config, health | FastAPI app with `/health/live` and `/health/ready` (checks DB and Redis), settings via env with validation, structured JSON logging, Alembic baseline with `system_runs`, Celery worker + beat skeleton, Next.js shell with navigation and a live system status page, CI | `docker compose up` brings every service to healthy; tests pass in CI |
| **2. Market data** (done) | Tiingo + Coinbase adapters, assets, bars, indicators | provider base (retry, rate limit, failure recording), `assets`, `market_prices`, `indicator_values`, `provider_failures`, seed of the 14 assets, market page and price chart | bars stored with correct `available_at`; indicator tests against known values |
| **3. News** (done) | Tiingo News, SEC EDGAR, Fed RSS | normalization, `content_hash` + title-similarity dedup, ticker extraction, news page | dedup and timestamp tests |
| **4. Events** (done) | clustering, scoring, asset linking | `events`, `event_sources`, `event_assets`, events page | clustering tests on fixture articles |
| **5. AI analysis** (done) | context builder, LLM client, schemas | `context_snapshots`, `ai_analyses`, `signals`, triage + main model, cost tracking, cache | lookahead test on snapshots; schema rejection tests |
| **6. Paper trading** | risk engine, fills, ledger, positions | `risk_decisions`, `trades`, `cash_ledger`, `positions`, immutability triggers, reconciliation | accounting, sizing and risk-rule tests |
| **7. Dashboard** | overview, portfolio, trades, journal, asset detail | signal trace endpoint and the pages listed in the product brief | every position explainable in two clicks |
| **8. Analytics** | snapshots, evaluations, metrics, benchmarks | `portfolio_snapshots`, `performance_evaluations`, analytics page | metric tests against hand-computed fixtures |
| **9. Backtesting** | replay clock, historical runs | `ReplayClock`, backtest runner, isolated portfolios | chronology tests: no row read with `available_at > clock` |
| **10. Hardening** | resilience and ops | provider fallback, monitoring page, alerting, security review, load of 6 months of history | failure-injection tests |

Everything from Phase 5 onward depends on Phases 2, 3 and 4.

### Phase 2 notes: what was built and what was left out

Built: Tiingo daily stock bars and Coinbase candles (1d and 1m) behind one HTTP client with retries, exponential backoff, `Retry-After` handling, typed errors and a sliding-window rate limiter; the append-only `market_prices` table with revisions; the 14-asset seed (run by the compose `migrate` service); scheduled ingestion jobs that record every run; 19 indicators computed in pure Python (RSI matches StockCharts' published worked example, MACD is checked against a closed form); a read-only market API; and the Market and asset pages.

Behaviour worth knowing:

- A provider without credentials produces a `skipped` run with the reason. A provider that fails produces a `failed` or `partial` run plus `provider_failures` rows, and no bars. An authentication or rate-limit error stops the run instead of retrying every symbol.
- Prices are parsed straight from JSON text into `Decimal` (`parse_float=Decimal`), so they never pass through a binary float.
- Every run re-fetches a short overlap (`MARKET_OVERLAP_DAYS`, default 5) so provider corrections are detected and stored as new revisions.
- Gaps are gaps. Coinbase publishes no candle for a minute without trades, and nothing fills it.

Left out on purpose, with the phase that should pick each up:

- **Alpha Vantage and CoinGecko fallbacks** are not implemented (Phase 10). The single-provider path is the one that matters until analysis exists.
- **Corporate actions.** Only `adj_close` is stored. Tiingo also returns `divCash` and `splitFactor`, which Phase 8 will likely need to evaluate signals that span a split. `adj_close` is as of fetch time, so for bars older than the overlap window it goes stale after a later dividend or split. Phase 8 must add a full-history refresh or store the corporate actions.
- **Staleness.** The Market page shows each bar's date and when it became usable, but there is no "stale" flag, because that needs an exchange calendar (weekends and holidays are not errors).
- **The rate limiter is per process.** If several workers ever share a provider, move the window into Redis.
- **HTTP response caching.** Ingestion is idempotent and stays far under the free-tier limits, so it was skipped.
- **Live verification.** This build environment cannot reach the providers, so the adapters were tested against mocked responses that follow the providers' documented shapes, not recorded live responses. The first run against real endpoints may reveal differences; the failure paths above are designed to make that visible rather than silent.

### Phase 3 notes: what was built and what was left out

Built: three source adapters (Tiingo News by tracked ticker, SEC EDGAR 8-K/10-K/10-Q per company, Federal Reserve press and speech RSS) that all produce one `RawArticle`; a normaliser that cleans text, canonicalises URLs, extracts tickers, companies and countries, assigns a rule-based category and sets the three timestamps; a store that marks duplicates instead of dropping them; one scheduled job per source (`SCHEDULE_NEWS_SECONDS`, default 900) with the same run and failure recording as market data; `GET /api/v1/news/articles` and `/sources`; and the News feed page.

Behaviour worth knowing:

- `published_at` is the source's claim (for a filing, SEC's `acceptanceDateTime`). `available_at` is the later of `published_at` and our `collected_at`, so a backfilled item is never visible to a decision made before we had it. `GET /news/articles?as_of=` applies that rule. Items dated more than 10 minutes in the future or without a timezone are rejected.
- Duplicates are stored and point at the first copy we collected. Two articles are duplicates when their canonical URL matches, their normalised titles match (3+ words), or their title word sets overlap by 80% or more (5+ words each), within `NEWS_DEDUP_WINDOW_HOURS` (default 48). Paraphrases of one event are deliberately not merged; grouping those is the events layer (Phase 4). Filings are compared by URL only, because two 8-Ks from one company can share a title.
- Feed text is untrusted: HTML removed, control characters and NUL stripped, lengths capped, non-http(s) links rejected, XML parsed with `defusedxml` (entity bombs and external entities refused). The UI re-checks links and opens them with `noopener noreferrer nofollow`. Article text is data and never reaches a prompt except through the Phase 5 context builder.
- Missing credentials give a `skipped` run (`TIINGO_API_KEY` for news, `SEC_USER_AGENT` for filings; the Fed feeds need none). A failed call is a `provider_failures` row and stores nothing. One company failing does not hide the others (`partial`), and an auth or rate-limit error stops the source.
- `sentiment` and `importance` stay null. Phase 5 fills them.

Left out on purpose:

- **Simhash.** Title Jaccard over a 48-hour window is exact, explainable and cheap at MVP volume. Revisit if body text is ever stored.
- **Article bodies.** Not fetched or stored: terms vary and headlines plus summaries are enough for triage. The `url` is kept for the reader.
- **Crypto news coverage.** Tiingo news is queried for stock and ETF tickers only. Whether Tiingo tags `btcusd` and `ethusd` on the free plan is unverified, so crypto headlines currently arrive only when they mention a tracked stock or when a Fed item is classed as crypto by keyword.
- **Other SEC forms.** Form 4, 13F and the rest are skipped as noise. Only companies with a stock asset in the universe are queried; the ticker-to-CIK map is fetched from SEC's `company_tickers.json` and cached for a day.
- **Entity extraction is a dictionary** for the 14 assets and 8 countries, not NER. It misses companies outside the universe by design.
- **A Redis-shared rate limiter.** The limiter is still per process. Tiingo prices and news share one budget within a worker process, but two worker processes each keep their own, so a burst could still hit Tiingo's limit; that surfaces as a recorded `ProviderRateLimited`, not silent loss.
- **Live verification.** As in Phase 2, adapters were tested against payloads that follow the documented shapes, not live responses. The SEC `company_tickers.json` and `submissions` shapes and Tiingo's `/tiingo/news` fields are the most likely places to differ; parse failures are recorded as rejected rows so a mismatch is visible on the status page.

### Phase 4 notes: what was built and what was left out

Built: a scheduled job (`SCHEDULE_EVENTS_SECONDS`, default 600) that groups new, not-yet-clustered articles into events by rules, scores each event, links it to tracked assets and closes events with no new article for `EVENT_WINDOW_HOURS` (default 48); `GET /api/v1/events` with ticker, category, status and `as_of` filters, each event returned with the articles it was built from; and the Events page.

Behaviour worth knowing:

- **Clustering rule.** An article joins the best open event when they share a ticker (or, with no tickers on either side, the same category and a country), their headlines share at least two words and overlap by 30% or more (Jaccard), and their publication times are within the window. Filings never join or accept anything: each filing is its own event. Tickered and ticker-less items never mix.
- **Score.** `importance` = category base (central bank 0.60, earnings 0.55, macro 0.50, geopolitics 0.45, filing 0.35, commodities and crypto 0.35, company 0.30, other 0.10) + 0.10 per extra outlet (max 3) + 0.05 per extra article (max 3), capped at 1. `confidence` = 0.7 × best source reliability + 0.15 per corroborating outlet (max 2). "Outlet" is the publisher Tiingo names in the payload, else the source key. The components are stored in `score_details`. These weights are starting judgements, not measured; Phase 8 replaces them with hit rates.
- **Point in time.** Nothing in an event is visible before the article that created it is available, and `state_as_of` never includes later articles. A test builds an event from articles that arrive three hours apart and checks that the earlier view has one article and a lower score.
- **Market-wide events** (Fed, macro, geopolitics) carry no tickers and so link to no asset. The Phase 5 context builder should include them by category and country, not through `event_assets`.
- The job handles up to 2000 unclustered articles per run; a larger backlog is finished by the next runs.

Left out on purpose:

- **Embeddings and LLM clustering.** `method` and `method_version` exist so they can be added beside the rules and compared. Rules were enough for headline-level grouping and are fully explainable.
- **Merging events.** Two events that later turn out to be the same story are not merged, and an article is never moved between events. Splitting a story across two events is the failure mode to watch on the first real data.
- **Cross-source linking of ticker-less items.** Tiingo news arrives tagged with tickers and Fed items with none, so a Tiingo article about a Fed decision will not join the Fed event. Fixing that needs topic tags rather than tickers.
- **Direction and impact.** No sentiment, no price-reaction measurement. Both belong to Phase 5 and Phase 8.
- **Live verification.** As before, only fixture headlines and synthetic articles were used. The 0.30 threshold is unproven on real headlines.

### Phase 5 notes: what was built and what was left out

Built: a context builder that assembles, as of one moment, the event and its articles, the price context of the candidate assets and the market regime; a two-stage job (cheap triage model, then the analysis model for relevant events) run every `SCHEDULE_AI_SECONDS`; Pydantic schemas whose JSON Schema is sent to the model as a forced tool call and against which the reply is validated; a decision journal (`signals`) that keeps every recommendation, HOLDs included; append-only `context_snapshots`, `ai_analyses` and `signals` tables; `GET /api/v1/signals`, `/ai/analyses`, `/ai/analyses/{id}` and `/ai/usage`; and the AI journal page.

Behaviour worth knowing:

- **No lookahead.** `build_context(event, as_of)` uses `state_as_of` for the event and `get_bars(as_of)` for prices, and returns nothing for an event whose first article was not yet available. Tests check that a bar not yet usable and an article not yet available are absent.
- **Untrusted text.** Articles reach the model only inside a `<data>` block, and the system prompt says that block is untrusted, must not be obeyed, and that null means unknown. Beyond the prompt, the reply is checked: the asset must be one of the candidates, cited events and articles must exist in the input, non-HOLD signals need a thesis, bear case and invalidation conditions, and a buy needs a stop loss. A reply that fails is stored with its errors and makes no signal. Model output can never place an order; Phase 6's risk engine applies its own limits.
- **Cost control.** Events must exceed `AI_MIN_EVENT_IMPORTANCE`; at most `AI_MAX_EVENTS_PER_RUN` per run; one analysis per event per `AI_REANALYZE_HOURS`; an identical request (same model, prompt version and facts, `as_of` ignored) is never repeated, and a cached triage answer is reused; nothing is called once today's estimated spend reaches `AI_DAILY_BUDGET_USD`, and the run says why it stopped. Prices are per million tokens and come only from `AI_MODEL_PRICES`. MarketOS does not guess them, and a model without a price is never called, so the budget can always be enforced.
- **Failures.** No key or no price is a `skipped` run. An auth or rate-limit error stops the run; other provider errors are recorded (`provider_failures` plus an `ai_analyses` row with status `error`) and the run continues. A refusal, a truncated reply or a reply without the tool call is stored as `refused` or `invalid`.
- `signals.reference_price` is the last close the model was shown and `reference_price_ts` its bar, so Phase 8 can evaluate each signal against what the model actually saw. `portfolio_context` stays null until Phase 6.

Left out on purpose:

- **Model defaults are unverified.** `AI_TRIAGE_MODEL` defaults to `claude-haiku-4-5-20251001` and `AI_ANALYSIS_MODEL` to `claude-sonnet-5-5`. This build environment cannot reach the API, so the client was tested against mocked responses that follow the documented Messages API (forced `tool_use`). The first live run is the check.
- **Prompt caching and batching.** Not used; volume is a few events per run.
- **`analysis_events`.** One event per analysis, so the FK on `ai_analyses` is enough.
- **Retrying invalid replies.** An invalid triage or analysis is retried on a later run only while the event still qualifies; there is no per-event retry cap beyond the daily budget.
- **Related past events are shallow:** same category and a shared ticker, with the 5-day move of the first shared asset when its bars are available. It is context, not a base rate.
- **Portfolio in the prompt** arrives with Phase 6; `vix_proxy` stays null.

### Future extension points (not in the MVP)

Multiple AI agents and models side by side, fundamentals and earnings-transcript analysis, deeper SEC filing analysis, social sentiment, portfolio optimization, strategy comparison across multiple portfolios, alternative risk profiles, and human approval before paper trades. The schema already supports multiple portfolios, multiple models per analysis and a `trigger` field on trades, so these add rows and services rather than restructure tables.
