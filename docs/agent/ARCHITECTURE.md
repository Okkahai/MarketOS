# MarketOS — architecture summary for agents

This is a map, not the design. The authoritative design is `docs/ARCHITECTURE.md` (schema, rules,
per-phase "left out on purpose" notes, audit section). The known defects and target architecture
are in `docs/audit/AUDIT-2026-11-05.md` (§A inventory, §B findings, §D target). If this file and
those disagree, those win; fix this file.

## Layers and code

| Layer | Code | Notes |
|---|---|---|
| Providers | `backend/app/providers/` (Tiingo EOD + news, Coinbase, SEC EDGAR, Fed RSS) | retry, rate limit, `provider_failures` |
| Market data | `backend/app/market/` (`ingest`, `repository`, `bars`, `indicators`, `compute`, `seed`) | append-only `market_prices` with revisions; 14-asset universe seeded by migration |
| News | `backend/app/news/` (`normalize`, `dedup`, `classify`, `entities`, `store`) | `available_at = max(published, collected)` |
| Events | `backend/app/events/` (`cluster`, `score`, `build.state_as_of`) | `events` row is a cache; point-in-time via `state_as_of` |
| Analyst | `backend/app/ai/` (`context`, `rules_llm` default, `llm` optional Claude, `validate`, `analyze`) | journal of analyses and signals |
| Risk + paper trading | `backend/app/trading/` (`risk`, `engine`, `execute`, `rules`, `state`, `reconcile`) | `ENGINE_VERSION = "risk-2"` in `trading/rules.py` |
| Evaluation + analytics | `backend/app/analytics/` (`evaluate` v1, `metrics`, `portfolio`) | v1 is biased (F1) until M2 |
| Backtest | `backend/app/backtest/` (`runner`, `__main__`) | replays stored data through the live engine, rules analyst only |
| Jobs | `backend/app/jobs/` (Celery beat, 13 jobs), `backend/app/monitor.py` | health alerts |
| API | `backend/app/api/routes/` FastAPI, GET only, `/api/v1/...`, `/health/ready` | no auth |
| Web | `frontend/src/app/*` Next.js 16 pages | overview, news, events, market, asset, portfolio, trades, journal, analytics, backtests, signals/[id] trace |
| DB | `backend/alembic/versions/0001..0008` | triggers enforce append-only |

## Lifecycle (one live cycle)

ingest bars (hourly) and news (15 min) → cluster events (10 min) → analysis (15 min): context as
of now, signals with `reference_price` = last close available → paper cycle (5 min): exits,
risk verdict per new signal, fill pending orders at next eligible open, snapshot → evaluate (hourly)
→ health check (5 min). Backtests replay the analysis + paper steps with a fixed clock.

## Invariants agents must keep

Point-in-time reads (`available_at <= as_of`); append-only history; versioning instead of
rewriting; Decimal money; paper only; no paid default. See `AGENTS.md` hard rules.

## Target evolution (audit §D, not built yet)

Strategy protocol + `strategies`/`strategy_runs` tables and per-strategy portfolios (M5);
`forecast_evaluations` v2 + session calendar (M2); execution-time columns (M3);
`corporate_actions` (M4); daily chain + `daily_reports` (M7); ML pipeline gated on data (M9).
Same stack, additive migrations, no new services.

## Runtime topology

`docker-compose.yml`: postgres, redis, migrate (alembic + seed), api (127.0.0.1:8000), worker
(celery, concurrency 2), beat, web (127.0.0.1:3000). All ports bound to localhost. Deployment guide:
`docs/DEPLOY.md` (Hetzner, SSH tunnel).
