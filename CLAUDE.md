# CLAUDE.md — MarketOS

All shared rules live in **`AGENTS.md`**. Read it first; it overrides nothing here and this file
overrides nothing there. Then read `docs/agent/HANDOFF.md`.

Claude-specific notes:

- **The user is Gün** (GitHub `Okkahai`). Gün often writes in Turkish; reply in the language Gün
  used. Gün wants to understand design choices: explain alternatives and trade-offs briefly, and
  when a question needs research, check it against the current date.
- **Do not make Claude itself a runtime dependency.** `AI_PROVIDER=anthropic` exists but is off by
  default because Gün does not want to pay for the Claude API (decision 2026-09-29). Never switch
  the default, never add a model call to tests or backtests (backtests refuse hosted models).
- **Model IDs and prices** in `.env.example` (`AI_TRIAGE_MODEL`, `AI_ANALYSIS_MODEL`,
  `AI_MODEL_PRICES`) are unverified placeholders. Prices are never guessed in code: a model without
  a price in `AI_MODEL_PRICES` is never called.
- **Merge authority:** the previous Claude coordinator was allowed to self-merge its own PRs after
  green CI (Gün, 2026-09-29, "until I say so"). In the new T3 Code setup, ask Gün to confirm this
  before merging anything (`docs/agent/DECISIONS.md` D-14).
- **Commit trailers:** follow whatever attribution the harness asks for; do not put model names in
  code, comments or docs.
- Project memory from the old Claude Cloud project is **not** available in the new environment; its
  content has been copied into `docs/agent/` (see `PROJECT_STATE.md` section "Sources").
