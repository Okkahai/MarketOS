# MarketOS — project state

Snapshot taken **2026-11-06 ~14:00 UTC** from `main` at `3232003` (merge of PR #13).
Labels used below: **[verified]** checked during this snapshot against the repo, GitHub or a test
run; **[recorded]** taken from project memory or thread records and not re-checked;
**[assumption]**; **[open question]**.

## 1. Goals

MarketOS is a financial research laboratory with virtual capital only. Central research question
(Gün, 2026-11-05): *can a particular decision-making strategy consistently produce useful
predictions or risk-adjusted performance beyond appropriate baseline strategies?*

It must continuously: collect news, events and market data; detect events and affected assets;
generate hypotheses with multiple independent strategies; simulate decisions; track positions,
costs and P&L; evaluate predictions against outcomes; compare against benchmarks and baselines;
later learn from history (ML); and produce transparent daily reports.

Original product brief (2026-09-28): layered pipeline news → normalization → events → market data →
AI analysis → signals → risk → paper trading → portfolio → analytics → dashboard; every
recommendation journaled even if not traded; losses as visible as wins.

## 2. Scope and non-goals

In scope: US stocks/ETFs and crypto (14-asset seeded universe), daily bars (+1m crypto), Tiingo /
SEC EDGAR / Fed RSS news, rules analyst, paper portfolios, backtests on stored data, dashboard.

Non-goals (explicit):
- Real-money trading or any broker execution — **never**.
- Paid services as defaults (cost rule, 2026-09-29).
- Rebuilding from scratch, replacing the stack, microservices, premature optimization (2026-11-05).
- ML "for marketing": no model until the data gate in audit D.6 passes.
- Showing uncalibrated scores as probabilities.
- Scraping publisher sites, unofficial Yahoo wrappers, social media (docs/ARCHITECTURE.md §6).

## 3. Status summary

| Area | State | Evidence |
|---|---|---|
| Phases 1–10 (MVP) | implemented, merged (PRs #1–#10, 2026-09-29) | [verified] GitHub PR list |
| README rewrite, Hetzner deploy guide + `packaging` dep fix | merged PRs #11 (2026-09-29), #12 (2026-11-03) | [verified] |
| Audit of `fe7bb60` | written 2026-11-05, now also in repo at `docs/audit/AUDIT-2026-11-05.md` | [verified] sha256 `d1d0bae2…8e36` identical to project-file copy |
| Milestone M1 (F2, F4, F5 partial, F6, F8) | implemented and merged PR #13, 2026-11-05 12:46Z, CI green | [verified] PR + Actions run 42030043402 success |
| Milestones M2–M10 | not started; M2 awaits Gün's approval | [verified] no branch/PR; [recorded] thread replies |
| Test suite on `3232003` | 319 backend passed, 21 frontend passed, ruff, eslint, tsc, alembic check clean | [verified] run 2026-11-06 in cloud sandbox |
| Live data | Tiingo stock prices fetched live once (2026-09-29); everything else only mocks/fixtures | [recorded] README, memory |
| Deployment | Hetzner CX23 chosen 2026-11-03; waiting on Gün to create server and send IP | [recorded] thread; [open question] did it happen? |
| Analyst edge | unknown; current hit rates are invalid until M2 (F1) | [verified] audit F1, ARCHITECTURE.md audit section |

**Implementation-complete vs verified-complete:** Phases 1–10 and M1 are implementation-complete
and CI-verified on synthetic data and fixtures. None is verified on real live data end to end.

## 4. Completed and verified capabilities (CI / fixtures level)

Providers with retry, rate limit and `provider_failures`; append-only market prices with revisions
and `available_at`; 19 indicators; news normalize/dedup/store with `available_at =
max(published, collected)`; event clustering (ticker + Jaccard 0.30) with `state_as_of`;
point-in-time context builder; rules analyst + optional Claude client with validation and journal;
deterministic risk engine (15 rules) and recorded verdicts; fills at next bar open with slippage
and fees; immutable trades, ledger, snapshots; reconciliation job; evaluations 1d/3d/7d/30d (v1,
biased, see F1); metrics vs SPY/BTC/cash; deterministic backtests in isolated portfolios; job health
alerts; security headers; Next.js pages overview, news, events, market, asset, portfolio, trades,
journal, analytics, backtests, signal trace. M1 fixes listed in `TASK_REGISTRY.md` MOS-M1.

## 5. Known bugs and technical debt (open)

From the audit (details and line refs in `docs/audit/AUDIT-2026-11-05.md`; line numbers refer to
`fe7bb60`, some moved in M1):

- **F1 P0** evaluation starts at last close seen → pre-decision moves credited. → MOS-M2
- **F3 P1** weekend/holiday 1d windows never evaluated, no status rows. → MOS-M2
- **F5 P1 (rest)** `trades.executed_at` back-dated; no `price_available_at`/`recorded_at`. → MOS-M3
- **F7 P1/P0 on split** raw unadjusted prices; splits fire fake stops; dividends ignored. → MOS-M4
- **F9 P2** freshness in hours, not sessions; rejects stock buys after holidays. → MOS-M2
- **F10 P2** past events in context snapshots not point-in-time. → MOS-M7
- **F11 P2** live vs backtest event selection differ. → MOS-M7
- **L1–L10** limitations (no strategy identity, horizon is a label, uncalibrated score, no
  baselines, pseudo-replication, backfill labelled as theoretical, daily bars can't order intraday,
  no session calendar, events built once live, doc drift — L10 fixed in M1).
- **U1–U5** unverified risks: Tiingo split/dividend fields; re-analysis on portfolio-only change;
  event membership hindsight; concurrent `fill_pending` without row lock; crypto 1m retention and
  Coinbase reachability. → MOS-INV-* tasks
- `evaluate.py` shortcut: unevaluable signals stay in the queue forever (until M2 statuses).
- SQLAlchemy deprecation: `distinct(expr)` for DISTINCT ON in `trading/engine.py:80`,
  `market/repository.py:36,93`, `analytics/evaluate.py:41` (694 warnings in test run). → MOS-DEBT-1
- `.env.example` lacks `AI_MAX_OUTPUT_TOKENS`, `AI_TIMEOUT_SECONDS` (exist in `core/config.py`). → MOS-DEBT-2
- ARCHITECTURE.md §9 rule 3 says "≤ 1 trading day old"; config uses 100 h / 54 h (see F9).
- Deliberately deferred since Phase 10: provider fallback (Alpha Vantage, CoinGecko), API auth,
  Redis-shared rate limiter, 6-month load test, auto-healing stuck runs.

## 6. Environment variables (names only, no values)

Defined in `.env.example` and `backend/app/core/config.py` [verified]. Secrets are `SecretStr`.

- **App:** `APP_ENV`, `LOG_LEVEL`, `LOG_FORMAT`, `TRADING_MODE` (only `paper`), `CORS_ORIGINS`,
  `HEALTH_CHECK_TIMEOUT_SECONDS`
- **DB/cache:** `POSTGRES_USER`, `POSTGRES_PASSWORD` (secret), `POSTGRES_DB`, `DATABASE_URL`,
  `REDIS_URL`; tests: `TEST_DATABASE_URL`, `TEST_REDIS_URL`
- **Paper trading/risk:** `PAPER_INITIAL_CAPITAL`, `BASE_CURRENCY`, `PAPER_MIN_CONFIDENCE`,
  `PAPER_STRONG_BUY_MIN_CONFIDENCE`, `PAPER_MAX_POSITION_PCT`, `PAPER_MAX_SECTOR_PCT`,
  `PAPER_MAX_CRYPTO_PCT`, `PAPER_MIN_CASH_PCT`, `PAPER_MAX_OPEN_POSITIONS`, `PAPER_MIN_TRADE_USD`,
  `PAPER_DEFAULT_POSITION_PCT`, `PAPER_COOLDOWN_HOURS`, `PAPER_MAX_TRADES_PER_DAY`,
  `PAPER_DEFAULT_STOP_PCT`, `PAPER_MAX_STOP_PCT`, `PAPER_MAX_TAKE_PROFIT_PCT`,
  `PAPER_DRAWDOWN_BREAKER_PCT`, `PAPER_SLIPPAGE_BPS_STOCK`, `PAPER_SLIPPAGE_BPS_CRYPTO`,
  `PAPER_FEE_BPS_STOCK`, `PAPER_FEE_BPS_CRYPTO`, `PAPER_MIN_FEE`, `PAPER_ORDER_EXPIRY_HOURS`,
  `PAPER_MAX_PRICE_AGE_HOURS_STOCK`, `PAPER_MAX_PRICE_AGE_HOURS_CRYPTO`, `PAPER_CRYPTO_FILL_INTERVAL`
- **Schedules:** `SCHEDULE_HEARTBEAT_SECONDS`, `SCHEDULE_STOCK_DAILY_SECONDS`,
  `SCHEDULE_CRYPTO_DAILY_SECONDS`, `SCHEDULE_CRYPTO_1M_SECONDS`, `SCHEDULE_INDICATORS_SECONDS`,
  `SCHEDULE_NEWS_SECONDS`, `SCHEDULE_EVENTS_SECONDS`, `SCHEDULE_AI_SECONDS`,
  `SCHEDULE_PAPER_SECONDS`, `SCHEDULE_RECONCILE_SECONDS`, `SCHEDULE_EVALUATE_SECONDS`,
  `SCHEDULE_HEALTH_SECONDS`, `EVENT_WINDOW_HOURS`, `NEWS_BACKFILL_DAYS`, `NEWS_DEDUP_WINDOW_HOURS`
- **Market data:** `MARKET_HISTORY_DAYS`, `MARKET_INTRADAY_BACKFILL_HOURS`, `MARKET_OVERLAP_DAYS`,
  `INDICATOR_STORE_BARS`, `PROVIDER_HTTP_TIMEOUT_SECONDS`, `PROVIDER_MAX_RETRIES`,
  `TIINGO_MAX_REQUESTS_PER_HOUR`
- **Provider keys (secrets, all optional):** `TIINGO_API_KEY` (needed for stocks + news),
  `SEC_USER_AGENT` (name + email, needed for EDGAR), `ALPHA_VANTAGE_API_KEY`, `COINGECKO_API_KEY`
  (fallbacks, not built), `FRED_API_KEY`, `FINNHUB_API_KEY`
- **AI:** `AI_PROVIDER` (`rules` default | `anthropic`), `ANTHROPIC_API_KEY`, `AI_MODEL_PRICES`,
  `AI_TRIAGE_MODEL`, `AI_ANALYSIS_MODEL`, `AI_DAILY_BUDGET_USD`, `AI_MIN_EVENT_IMPORTANCE`,
  `AI_MAX_EVENTS_PER_RUN`, `AI_REANALYZE_HOURS`, `AI_MAX_SIGNALS_PER_ANALYSIS`,
  `AI_MAX_OUTPUT_TOKENS`, `AI_TIMEOUT_SECONDS`

External services: Tiingo (free, personal use), Coinbase Exchange public candles (no key), SEC
EDGAR (User-Agent), Federal Reserve RSS, optional FRED; GitHub Actions CI; planned Hetzner CX23.
Security note [recorded]: Gün pasted a Tiingo token in a chat on 2026-11-03; rotating it was
advised. Not confirmed done → MOS-SEC-1.

## 7. Git state [verified 2026-11-06]

| Ref | SHA | State |
|---|---|---|
| `main` | `3232003` | merge of PR #13; CI success (run 42030043402) |
| `claude/project-thread-vmcf8w` | `cab3f23` | fully merged (PR #13), 0 commits ahead of main |
| `claude/phase1-foundation-y6tj5f` | `968a9e3` | fully merged (PR #12), 0 commits ahead of main |
| `migration/handoff` | merged via PR #14 | adds AGENTS.md, CLAUDE.md, docs/agent/*, docs/audit/* (docs only) |

PRs: #1–#13 all merged, **no open PRs, no issues**. No unmerged or uncommitted work exists in any
remote branch. The two `claude/*` branches can be deleted after Gün approves (MOS-GIT-1).

## 8. Threads and sessions in the old Claude Cloud project [verified via thread list]

| Thread | Session | State | Outstanding |
|---|---|---|---|
| "MarketOS architecture and Phase 1" | `cse_01AmLMAHJUFLrv3QAuJibRHF` | done, resolved | last ask to Gün: create Hetzner server, send IP (MOS-OPS-1) |
| "Audit MarketOS correctness and architecture" | `cse_01EkSrunPE1ogHXVKf4zQCV1` | done, not resolved | none; M1 approved there |
| "Implement M1 correctness fixes" | `cse_01EkSrujLAtC1EFYWG5DWsyk` | done, resolved | M2 awaits approval |
| "Prepare migration handoff for T3 Code" | `cse_01EkSrunHsZPjNL1orhjoP5D` | done | none (PR #14 merged) |

No thread is running. Stopping these sessions loses nothing that is not in git or in this folder,
**except**: the seven audit reproduction probes (`test_A,B,C,E,F,G,weekend`) were throwaway files in
the audit sandbox and are gone [assumption: sandbox reclaimed]. M1 turned A, B, C, G into regression
tests; E, F and weekend must be rewritten from the audit text for M2/M4.

## 9. Sources used for this snapshot

Repo (`main` 3232003): README.md, docs/ARCHITECTURE.md, docs/DEPLOY.md, .env.example,
.github/workflows/ci.yml, backend/pyproject.toml, frontend/package.json, code grep.
GitHub: PR list, branches, issues, Actions runs. Project files: `marketos/ARCHITECTURE.md` (stale
copy from 2026-09-29, 852 lines vs 869 in repo — **repo is authoritative**),
`marketos/audit/AUDIT-2026-11-05.md`. Project memory (5 files). Thread records of the four threads
and the project chat.
Not accessible / not inspected: Gün's local machine and any local Docker database; any Hetzner
server; earlier messages of the phase thread beyond its last ~12 (memory summarises them); the
live Tiingo account.
