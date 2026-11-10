# MarketOS — decisions log

Historical decisions with rationale. "Gün" = the project owner. Dates are UTC. Source: thread
records and project memory of the Claude Cloud project, cross-checked with the repo where possible.

| ID | Date | Decision | Rationale | Status |
|---|---|---|---|---|
| D-01 | 2026-09-28 | Paper trading only; `TRADING_MODE` literal `paper`; no broker code | product brief: never real money | permanent |
| D-02 | 2026-09-28 | Stack: FastAPI + SQLAlchemy 2 + Alembic, PostgreSQL 16, Celery + Redis, Next.js 16 + TS, lightweight-charts, Docker Compose | maintainable, single-host, reaffirmed 2026-11-05 ("preserve the current stack") | permanent |
| D-03 | 2026-09-28 | Money is `Decimal` / `NUMERIC`, never float | accounting correctness | permanent |
| D-04 | 2026-09-28 | Append-only tables with DB triggers; never rewrite trades, signals, evaluations | audit trail, traceability | permanent |
| D-05 | 2026-11-05 | Fixes to past methodology are **versioned** (new table/version, label old rows), never updates | Gün's audit brief §8 | permanent |
| D-06 | 2026-09-28 | Point-in-time: `available_at` on every row; stock daily bar available 20:00 New York on its date (Tiingo corrections until 8 PM ET); crypto = close + 5 s; news = max(published, collected) | no lookahead live or in backtests | permanent |
| D-07 | 2026-09-28 | Providers (terms checked 2026-09-28): Tiingo primary stocks + news; Coinbase Exchange public candles primary crypto; SEC EDGAR; Fed RSS; FRED/ALFRED; fallbacks Alpha Vantage / CoinGecko Demo planned, not built | free, legal APIs; personal/non-commercial terms | active |
| D-08 | 2026-09-28 | Rejected sources: publisher scraping, unofficial Yahoo wrappers, social media | fragile, license, deferred | active |
| D-09 | 2026-09-29 | **No paid services.** Default `AI_PROVIDER=rules` (free deterministic analyst `app/ai/rules_llm.py`); Anthropic backend optional, off by default, needs `ANTHROPIC_API_KEY` + `AI_MODEL_PRICES`; prices never guessed | Gün does not want to pay for the Claude API | permanent until Gün changes it |
| D-10 | 2026-09-29 | Fills at the next bar open after the decision, adverse slippage, fees; stop wins when a bar touches both stop and target | conservative execution | active |
| D-11 | 2026-11-05 | Session calendar derived from stored SPY daily bars; `exchange_calendars` (Apache-2.0) only if future sessions are needed | no new dependency | planned (M2) |
| D-12 | 2026-11-05 | One portfolio per strategy; rejected: one shared portfolio with tagged signals | strategies would compete for cash and slots | planned (M5) |
| D-13 | 2026-11-05 | `executed_at` stays market time of the price; add `price_available_at`, `recorded_at`; rejected: setting `executed_at` to availability time | keeps holding periods right, records both truths | planned (M3) |
| D-14 | 2026-09-29 | Claude may review and self-merge its own PRs after green CI "until I say so" | Gün did not want to be the bottleneck | **needs re-confirmation in T3 Code** (MOS-CFG-1) |
| D-15 | 2026-09-29 | "Continue all phases until the end": phases 5–10 built back to back | speed | finished; does **not** cover M2+ |
| D-16 | 2026-11-05 | Audit first, no code before approval; implementation in a fresh agent/thread; one milestone at a time with explicit approval | Gün wants to understand decisions | permanent working rule |
| D-17 | 2026-11-05 | M1 approved as proposed (option "Approve M1 as proposed"); rejected alternatives: M2 first, M1 without stop change | lowest-risk step | done |
| D-18 | 2026-11-05 | F6 entry-bar exits only for positions opened under `risk-2`; no retroactive exits | do not rewrite history | done |
| D-19 | 2026-11-03 | Host 24/7 on Hetzner CX23 (~6 EUR/month, Germany/Finland), reachable only through an SSH tunnel; Railway considered and not chosen (costlier, needs auth first) | cheapest fixed cost, compose works as is | waiting on Gün (MOS-OPS-1) |
| D-20 | 2026-11-05 | Keep the rules analyst as `RulesBaseline`; do not remove it | Gün's audit brief §4 | planned (M5) |
| D-21 | 2026-11-05 | No ML until the data gate passes; simple models first; no deep learning by default | research validity | planned (M9) |
| D-22 | 2026-09-28 | API is GET-only, bound to 127.0.0.1, no auth | single user, local | active; auth needed before exposure (MOS-SEC-2) |

## User preferences and corrections

- Gün writes in Turkish or English; answer in the language used. Wants short explanations of
  alternatives and trade-offs, not blind autonomy.
- Research questions: check facts against the current date (standing preference).
- Do not change product scope without justification; do not attempt the whole roadmap in one pass.
- Losses and failed predictions must be as visible as wins; never present uncalibrated scores as probabilities.
- Do not weaken or delete tests to get green.

## Previously rejected approaches (do not re-propose without new evidence)

- Paid AI as default (D-09). Railway hosting (D-19). Shared multi-strategy portfolio (D-12).
- `executed_at` = availability time (D-13). Provider fallback that silently mixes price sources (Phase 10 notes).
- Retroactive stop-outs of existing positions (D-18). M2 before M1 (D-17).
