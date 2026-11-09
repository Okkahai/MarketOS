# MarketOS — verification

## CI (`.github/workflows/ci.yml`, on every PR and push to main)

1. **backend** (Python 3.12, Postgres 16 + Redis 7 services): `pip install -e '.[dev]'`,
   `ruff check .`, `ruff format --check .`, `alembic upgrade head && alembic check && alembic
   downgrade base`, `pytest -v` (unit + integration).
2. **frontend** (Node 22): `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` (vitest),
   `npm run build`.
3. **compose** (needs 1 and 2): `docker compose up --build -d` from `.env.example`, waits for
   `/health/ready`, checks the web page renders "System status", 14-asset watchlist, `BTC-USD` on
   `/market`, and that beat + worker record a `heartbeat` run.

Last green run on main: Actions run 42030043402 (commit `3232003`, 2026-11-05).

## Running locally

```bash
# PostgreSQL 16 and Redis must be running. Example without Docker:
initdb -D /var/tmp/pg -U marketos --auth=trust && pg_ctl -D /var/tmp/pg -o '-p 5432 -k /tmp' start
createdb -h /tmp -U marketos marketos_test && redis-server --daemonize yes
export TEST_DATABASE_URL=postgresql+psycopg://marketos@localhost:5432/marketos_test
export TEST_REDIS_URL=redis://localhost:6379/1
cd backend && pip install -e '.[dev]' && python -m pytest -q
cd ../frontend && npm ci && npm run lint && npm run typecheck && npm test
```

Integration tests are marked `integration` and skip without `TEST_DATABASE_URL`/`TEST_REDIS_URL`.
Use `python -m pytest` so the interpreter that has the deps runs the tests.

## Baseline re-verified for this handoff (2026-11-06, cloud sandbox, Python 3.13, commit `3232003`)

| Check | Result |
|---|---|
| ruff check / format | pass (130 files) |
| alembic upgrade / check / downgrade | pass, "No new upgrade operations detected" |
| pytest | **319 passed**, 694 warnings (SQLAlchemy DISTINCT ON deprecation, MOS-DEBT-1) |
| frontend lint, typecheck | pass |
| vitest | **21 passed** (3 files) |
| npm run build, docker compose | not run here (CI covers them; Docker Hub pulls are rate-limited in the sandbox) |

## What is verified and what is not

| Claim | Level |
|---|---|
| Phases 1–10 and M1 behave as tested | CI on synthetic data and fixtures |
| Tiingo stock daily prices | fetched live once, 2026-09-29 |
| Tiingo news, SEC EDGAR, Fed RSS, Coinbase on real data | **not verified** (cloud egress blocks these hosts; Coinbase blocked on Gün's ISP) |
| Event clustering threshold 0.30 on real headlines | **not verified** |
| Analyst edge / hit rates | **not meaningful** until M2 (F1) |
| Anthropic model IDs and prices | **not verified**, off by default |
| Hetzner deployment | **not done / unknown** |

## Rules for new work

- Every confirmed defect: a regression test that fails on the old commit and passes on the new one.
  Say in the PR which commit it was checked against.
- Never delete or weaken a test that codifies old behaviour; keep it for the old version
  (`risk-1`, `methodology_version` 1) and add the new one.
- Required edge cases from Gün's brief: order expiry, delayed data, holidays/weekends, missing bars,
  revised prices, same-bar stop+target, corporate actions, evaluation pagination, long-running
  portfolio state, strategy isolation, backtest chronology, repeated backtests identical.
- "Done" in `TASK_REGISTRY.md` means merged with green CI; "verified live" is a separate status that
  needs real provider data.
