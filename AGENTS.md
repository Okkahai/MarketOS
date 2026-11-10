# AGENTS.md — MarketOS

Provider-neutral instructions for any coding agent (Claude Code, Codex CLI, others) working in
this repository. Claude-specific notes are in `CLAUDE.md`; everything here applies to Claude too.

**Start here:** read `docs/agent/HANDOFF.md`, then `docs/agent/TASK_REGISTRY.md`.

## What this project is

MarketOS is a financial research lab and **paper trading** platform: it collects news and market
data, groups news into events, produces signals with a deterministic analyst, simulates trades with
virtual capital under a deterministic risk engine, and measures whether the signals worked.
Stack: FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16, Celery + Redis, Next.js 16 + TypeScript,
Docker Compose. Details: `docs/agent/ARCHITECTURE.md` (summary) and `docs/ARCHITECTURE.md` (full).

## Hard rules (never break these)

1. **Simulation only.** No real-money trading, no broker integration, no order routing.
   `TRADING_MODE` accepts only `paper`.
2. **$0 cost.** No paid service may become a default or a requirement. Default analyst is the free
   rules analyst (`AI_PROVIDER=rules`). The Anthropic backend stays optional and off by default.
   Data providers: free tiers only. Any new dependency must be free and open-source.
3. **Never rewrite history.** Tables for prices, context snapshots, analyses, signals, trades, cash
   ledger, risk decisions, portfolio snapshots and evaluations are append-only (DB triggers enforce
   it). If a past result is wrong, add a **versioned** replacement (new table/version column, new
   `ENGINE_VERSION`, `methodology_version`), keep the old rows and label them.
4. **Point-in-time integrity.** Every read used for a decision filters on `available_at <= as_of`.
   Nothing from the future may reach a strategy, live or in a backtest.
5. **Additive migrations only.** New tables and nullable columns; no destructive migrations.
   `alembic check` must pass (models match migrations).
6. **Do not weaken or delete tests to make CI pass.** If an existing test codifies a defect, keep it
   for the old version (e.g. `risk-1`) and add a new test for the new version.
7. **Every confirmed defect gets a regression test** that fails on the old code and passes after.
8. **Do not start a roadmap milestone without Gün's explicit approval** (see below).

## Approval gates (ask the user, Gün, first)

- Starting any milestone M2..M10 or any other new feature work.
- Pushing, merging, force-pushing, deleting branches, closing PRs.
- Anything outside paper trading, anything that costs money, anything that exposes ports
  3000/8000 to the internet (there is no login yet).
- Changing stored history, risk defaults, or the cost rule.

Past permission to self-merge (2026-09-29) was given to the previous Claude coordinator; treat it as
**not transferred** until Gün confirms it in the new environment (see `docs/agent/DECISIONS.md` D-14).

## Workflow

- One milestone = one branch = one PR into `main`, tests first, CI green before merge.
- Branch from fresh `origin/main`. With worktrees: `git worktree add ../mos-<task-id> -b <task-id>/<slug> origin/main`.
- Update `docs/ARCHITECTURE.md` sections your change touches, keep the "left out on purpose" lists,
  and update `docs/agent/TASK_REGISTRY.md` status in the same PR.
- Comment shortcuts in code as `shortcut: <limit>, <when to upgrade>`.
- Independent review: a reviewer agent that did not write the change reads the diff against the
  task's acceptance criteria in `TASK_REGISTRY.md` and the audit finding it fixes.

## Checks to run before pushing (same as CI)

```bash
# backend (needs PostgreSQL 16 + Redis; see docs/agent/VERIFICATION.md)
cd backend && pip install -e '.[dev]'
ruff check . && ruff format --check .
DATABASE_URL=$TEST_DATABASE_URL alembic upgrade head && alembic check && alembic downgrade base
pytest -v
# frontend
cd frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build
```

## Documentation map

| File | Purpose |
|---|---|
| `docs/agent/HANDOFF.md` | how to resume work, first steps for a new coordinator |
| `docs/agent/PROJECT_STATE.md` | goals, scope, status, verified vs unverified, env vars, git state |
| `docs/agent/TASK_REGISTRY.md` | every unfinished task with ID, acceptance criteria, next action |
| `docs/agent/DECISIONS.md` | decisions, rationale, rejected approaches, user preferences |
| `docs/agent/ARCHITECTURE.md` | short architecture summary pointing into the full doc |
| `docs/agent/VERIFICATION.md` | how to test, what CI does, what is and is not verified |
| `docs/ARCHITECTURE.md` | authoritative full design (schema, rules, per-phase notes) |
| `docs/audit/AUDIT-2026-11-05.md` | correctness audit: findings F1–F11, L1–L10, U1–U5, plan M1–M10 |
| `docs/DEPLOY.md` | Hetzner server deployment guide |

Never put secrets in the repo, docs, commits or chat. `.env` is git-ignored.
