# MarketOS — task registry

Snapshot 2026-11-09, `main` = `3232003`. One row per task; details below. IDs are stable: never
reuse or renumber. Milestone IDs M1–M10 match `docs/audit/AUDIT-2026-11-05.md` §E.

Status values: `done-verified` (merged, CI green, tests prove it), `done-unverified-live` (merged,
only synthetic/fixture evidence), `ready` (can start once approved), `blocked`, `waiting-user`,
`deferred` (left out on purpose), `investigate`.

Confidence: high = checked in repo/GitHub/test run on 2026-11-06..09; medium = from thread records
or memory; low = inferred.

| ID | Title | Status | Priority | Needs Gün's approval | Depends on |
|---|---|---|---|---|---|
| MOS-M1 | Engine and queue correctness (F2, F4, F5 partial, F6, F8) | done-verified (CI) / unverified-live | — | — | — |
| MOS-M1-FU1 | Backtest test with `step_hours=96` (skipped in M1) | ready | P2 | yes (small) | — |
| MOS-M2 | Evaluation v2 + session calendar (F1, F3, F9, primary horizon) | ready | **P0** | **yes** | M1 |
| MOS-M3 | Execution-time model (F5 full) | ready after approval | P1 | yes | M1 |
| MOS-M4 | Corporate actions (F7) | blocked | P1 | yes | M2, M3, MOS-OPS-3 |
| MOS-M5 | Strategy identity + per-strategy portfolios (L1) | ready after approval | P1 | yes | M1 |
| MOS-M6 | Baselines and comparison with intervals (L4) | blocked | P1 | yes | M2, M5 |
| MOS-M7 | Daily workflow + report; F10, F11 parity | blocked | P1 | yes | M2, M5 |
| MOS-M8 | Event-intelligence measurement + cheap fixes | blocked | P2 | yes | MOS-OPS-2 (live news) |
| MOS-M9 | ML dataset, splits, first model (gated) | blocked | P3 | yes | M2, M5, M6, data gate |
| MOS-M10 | Optional LLMResearchStrategy (forward-test only, off by default) | blocked | P3 | yes | M5 |
| MOS-OPS-1 | Deploy on Hetzner CX23 via docs/DEPLOY.md | waiting-user | P1 | Gün acts | — |
| MOS-OPS-2 | First full live run (Tiingo news, SEC, Fed, Coinbase) | waiting-user | P1 | Gün acts | keys in `.env` |
| MOS-OPS-3 | Check Tiingo `splitFactor`/`divCash`/`adjClose` live (U1) | waiting-user | P1 | Gün acts | TIINGO_API_KEY |
| MOS-SEC-1 | Rotate Tiingo token pasted in chat 2026-11-03 | waiting-user | P1 | Gün acts | — |
| MOS-SEC-2 | Login/password gate before exposing ports 3000/8000 | deferred | P1 if exposed | yes | — |
| MOS-INV-1 | U2 re-analysis on portfolio-only changes | investigate | P2 | no (read-only) | — |
| MOS-INV-2 | U3 event membership with hindsight | investigate | P2 | no | — |
| MOS-INV-3 | U4 concurrent `fill_pending` without row lock | investigate | P2 | no | — |
| MOS-INV-4 | U5 crypto 1m retention/gaps, Coinbase reachability | investigate | P2 | no | MOS-OPS-1/2 |
| MOS-DEF-1 | Provider fallback (Alpha Vantage, CoinGecko) | deferred | P3 | yes | — |
| MOS-DEF-2 | Redis-shared rate limiter | deferred | P3 | yes | — |
| MOS-DEF-3 | 6-month history load test | deferred | P3 | yes | MOS-OPS-2 |
| MOS-DEBT-1 | SQLAlchemy `distinct(expr)` deprecation → `postgresql.distinct_on` | ready | P3 | yes (small) | — |
| MOS-DEBT-2 | Add `AI_MAX_OUTPUT_TOKENS`, `AI_TIMEOUT_SECONDS` to `.env.example` | ready | P3 | yes (small) | — |
| MOS-DOC-1 | Stale `marketos/ARCHITECTURE.md` in old project files | done (repo is authoritative) | — | — | — |
| MOS-MIG-1 | Publish handoff docs on `main` | done (PR #14, merged on Gün's approval 2026-11-10) | — | — | — |
| MOS-GIT-1 | Delete merged branches `claude/phase1-foundation-y6tj5f`, `claude/project-thread-vmcf8w` | waiting-user | P3 | yes | — |
| MOS-CFG-1 | Confirm merge authority for agents in T3 Code | waiting-user | P1 | Gün decides | — |

---

## MOS-M1 — Engine and queue correctness

- **Status:** implementation complete, merged, CI verified. Not verified on live data.
- **Objective:** remove confirmed engine/queue defects without migration or history change (audit §F).
- **Acceptance (audit §E):** probes become regression tests failing on `fe7bb60` and passing after;
  suite green; no migration; `ENGINE_VERSION = "risk-2"`; no historical row changed.
- **Threads/sessions:** approved in audit thread `cse_01EkSrunPE1ogHXVKf4zQCV1` (2026-11-05 12:25Z);
  implemented in `cse_01EkSrujLAtC1EFYWG5DWsyk`.
- **Git:** branch `claude/project-thread-vmcf8w`, commit `cab3f23`, PR #13 merged 2026-11-05 12:46Z
  as `3232003`; CI run 42030043402 success.
- **Done:** F4 expiry before fill; F2 `NOT EXISTS` + keyset pages; F6 entry bar for `risk-2`
  positions only; F5 cooldown/daily cap by `orders.signal_time` incl. pending; F8 signed averages,
  no self-benchmark, per-action, UI "score (uncalibrated)"; ARCHITECTURE.md drift (L10) + audit section.
- **Files:** `backend/app/analytics/{evaluate,metrics}.py`, `backend/app/api/routes/analytics.py`,
  `backend/app/trading/{engine,risk,rules,state}.py`, tests `integration/test_{analytics,trading}.py`,
  frontend pages analytics, asset, journal, overview, signals/[id], trades.
- **Verification:** 319 backend + 21 frontend tests pass on `3232003` (re-run 2026-11-06).
- **Remaining:** MOS-M1-FU1. **Do not restart M1.**
- **Confidence:** high.

## MOS-M1-FU1 — Backtest with 96-hour steps

- **Objective:** audit F4 asked for a backtest test with `step_hours=96` (expiry 72 h is shorter
  than one step); M1 thread reported it skipped.
- **Acceptance:** a backtest with `step_hours=96` never fills an order on a bar opening at/after
  `expires_at`. Files: `backend/tests/integration/test_backtest.py`, `backend/app/backtest/runner.py`.
- **Next action:** fold into M2's PR or a tiny separate PR after approval. Confidence: medium.

## MOS-M2 — Evaluation v2 and session calendar (NEXT)

- **Status:** ready, not started, **awaiting Gün's approval** (asked in M1 thread 2026-11-05 12:47Z, no answer).
- **Objective:** measure forecasts from the first executable price after the decision (F1), horizons
  in trading sessions with terminal statuses (F3), freshness in missed sessions (F9), primary
  horizon = the one the forecast declared (L2).
- **Acceptance (audit §E, D.2):** new append-only table `forecast_evaluations` (`signal_id,
  horizon_sessions, methodology_version, status complete|insufficient_data|not_applicable,
  entry_price, entry_price_ts, entry_available_at, exit_price, exit_price_ts, asset_return,
  benchmark_symbol, benchmark_return, excess_return, signed_return, signed_excess, pre_entry_drift,
  mfe, mae, evaluated_at`) with append-only trigger; additive migration `0009`; v1
  `performance_evaluations` untouched and labelled "measured from last close seen" in API + UI;
  session calendar derived from stored SPY daily bars (no new dependency); tests: probe E inverted
  (Monday 21:00 UTC BUY; Tuesday open 102 close 97 → v2 entry 102, return −4.9 %, wrong; v1 row
  unchanged), weekend, US holiday 2026-07-03, data gap → status rows; F9 freshness after Monday
  holiday accepts Friday close; `alembic check` clean.
- **Files:** `backend/app/analytics/evaluate.py` (v1 stays), new `analytics/evaluate_v2.py` or
  similar, `backend/app/models/evaluation.py`, `backend/alembic/versions/0009_*.py`,
  `backend/app/trading/risk.py` (F9 ~`:287`), `backend/app/api/routes/analytics.py`,
  `frontend/src/app/analytics/page.tsx`, `docs/ARCHITECTURE.md` §4, §10, audit section.
- **Decisions already made:** versioned table, never update v1 (D-05); calendar from SPY bars,
  `exchange_calendars` (Apache-2.0) only if future sessions are needed (D-11).
- **Lost context:** audit probes `test_E` and `test_weekend` were not kept; rewrite them from audit F1/F3 text.
- **Next action:** ask Gün to approve M2; then branch `m2/evaluation-v2` from `origin/main`, write
  failing tests first. Confidence: high (plan), medium (exact file layout).

## MOS-M3 — Execution-time model (F5 in full)

- **Acceptance:** additive nullable `trades.price_available_at`, `trades.recorded_at`,
  `price_assumption` (`gap_open|stop_level|target_level|double_touch_stop`); null for old trades;
  "book as of T" rebuilt with `recorded_at <= T` equals the snapshot at T over a long synthetic run.
- **Files:** `backend/app/trading/{engine,execute,state}.py`, `backend/app/models/trading.py`, migration.
- **Next action:** after M2 (or in parallel worktree once approved). Confidence: high.

## MOS-M4 — Corporate actions (F7)

- **Blocked on:** MOS-OPS-3 (U1 live check of Tiingo fields), M2, M3.
- **Acceptance:** table `corporate_actions` (point-in-time); split applied to open positions as an
  explicit adjustment record (qty, avg cost, stop, target scaled), dividend as new `cash_ledger`
  kind; indicators and evaluations on series adjusted only with actions `available_at <= as_of`;
  tests: split mid-position (no stop, qty ×4, value unchanged), dividend credited, evaluation across
  split, indicator continuity. Also fix `_same` in `market/repository.py:131-133` creating revision
  rows on every dividend. Probe `test_F` (4:1 split fires stop) must be rewritten.
- **Files:** `backend/app/providers/tiingo.py:43-51`, `market/repository.py`, `ai/context.py:62-69`,
  `trading/*`, `analytics/*`.

## MOS-M5 — Strategy identity and per-strategy portfolios

- **Acceptance:** `strategies` and `strategy_runs` tables; nullable `signals.strategy_id`;
  `portfolios.strategy_id`; engine `decide()` filters signals by portfolio strategy; today's analyst
  wrapped as `RulesBaseline v1` (behaviour unchanged); legacy mapping
  `ai_analyses.model='rules-analysis-1'` → RulesBaseline v1 via a view; two strategies in one replay
  do not affect each other; repeated backtests identical. Rejected alternative: one shared portfolio (D-12).

## MOS-M6 — Baselines and comparison

- **Acceptance:** cash, buy-and-hold SPY, equal-weight universe, seeded matched-random, technical
  rule, always-buy-on-news, under identical data/execution/costs/risk; bootstrap intervals; base
  rates; beta/exposure; reproducible from seed (audit §C items 3–8).

## MOS-M7 — Daily research workflow and report; F10, F11

- **Acceptance:** one Celery chain after 20:00 New York (e.g. 21:30) with data-quality gate;
  append-only `daily_reports`; sections per audit D.5; past events in context built with
  `state_as_of` (F10, test injects a late article); one shared point-in-time event selection for
  live and backtest (F11).

## MOS-M8 — Event intelligence (measure first)

- **Blocked on:** live news running (MOS-OPS-2). Label ~100 real clusters, then cheap fixes in the
  order of audit D.7. Embeddings (local MiniLM, free) only if labelled error rate demands it.

## MOS-M9 — ML (gated)

- **Gate:** at least ~1,000 independent event-asset forecasts over ≥ 6 months, both classes
  represented (audit D.6, suggestion, not yet agreed with Gün → open question Q-05). Logistic
  regression first, then gradient-boosted trees; walk-forward; leakage tests; calibration on validation fold only.

## MOS-M10 — Optional LLMResearchStrategy

- Forward-test only, off by default, $0 unless Gün enables it; never runs in backtests.

## MOS-OPS-1 — Hetzner deployment

- **Status:** waiting on Gün since 2026-11-03 22:02Z: create Hetzner account and CX23 server
  (Germany/Finland, Ubuntu 24.04, firewall only TCP 22), send the IP. Then walk docs/DEPLOY.md
  §2–6 (Docker, `.env`, `docker compose up --build -d`, SSH tunnel, backups).
- **Unknown:** whether Gün did this (Q-01). Thread `cse_01AmLMAHJUFLrv3QAuJibRHF`. Confidence: medium.

## MOS-OPS-2 — First live run

- Needs `TIINGO_API_KEY` and `SEC_USER_AGENT` in `.env`. Verify on System status page: jobs
  succeed, Alerts empty, Coinbase reachable (was blocked on Gün's home ISP). Only stock prices were
  verified live (2026-09-29). Run on the server or Gün's machine; the cloud sandbox blocks these hosts.

## MOS-OPS-3 — Tiingo corporate-action fields (U1)

- With the live key, fetch a known splitter around its ex-date (e.g. NVDA 2024-06-10) and record
  whether the free plan returns `splitFactor`, `divCash`, and how `adjClose` behaves. Output goes into M4's design.

## MOS-SEC-1 — Rotate Tiingo token

- Gün pasted the token in a chat on 2026-11-03; rotation was advised, not confirmed. Gün does it at tiingo.com.

## MOS-SEC-2 — Login gate

- Web and API have no auth; DEPLOY.md keeps all ports closed and uses an SSH tunnel. Any public
  exposure (Railway, opened ports) needs this first.

## MOS-INV-1..4 — Unverified risks U2–U5

Read-only investigations; each ends with either a reproduction test (then a fix task) or a note
that the risk is not real. References: audit B.3. U4 likely fix: `SELECT … FOR UPDATE` on the order row.

## MOS-DEBT-1, MOS-DEBT-2

Small hygiene; bundle into any milestone PR. DEBT-1 sites: `trading/engine.py:80`,
`market/repository.py:36,93`, `analytics/evaluate.py:41`.

## MOS-MIG-1 — Publish the handoff

- Done: branch `migration/handoff` pushed and merged to `main` via PR #14 on Gün's approval
  (2026-11-10). Backup copies remain in the old project's files folder `migration/`.

## MOS-CFG-1 — Merge authority

- Old rule: Claude self-merges after green CI ("until I say so", 2026-09-29). For M1 the agent still
  asked before merging. In T3 Code, Gün should state the rule for each agent (Claude, Codex,
  reviewers). Until then: no merges without Gün.
