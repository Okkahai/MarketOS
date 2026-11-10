# MarketOS — handoff to a new coordinator

Written 2026-11-09 for the move from Claude Code Cloud Projects to a local T3 Code setup
(Claude Code, Codex CLI, git worktrees, independent reviewers, GitHub CI). Assumes zero prior context.

## 1. Read in this order

1. `AGENTS.md` (rules) → 2. this file → 3. `docs/agent/TASK_REGISTRY.md` →
4. `docs/agent/PROJECT_STATE.md` → 5. `docs/agent/DECISIONS.md` →
6. `docs/audit/AUDIT-2026-11-05.md` §B, §E, §F → 7. `docs/ARCHITECTURE.md` "Audit 2026-11-05" section.

## 2. Where things stand (one paragraph)

The MVP (10 phases) and the first correctness milestone M1 are merged on `main` (`3232003`) with
green CI; 319 backend and 21 frontend tests pass. Nothing has run end to end on real news, so the
system's hit rates mean nothing yet, and they are also biased until M2 fixes the evaluation entry
price (audit F1, P0). No work is in flight: no open PRs, no running threads, both old feature
branches are fully merged. The next engineering step is M2, which Gün has **not approved yet**.
The next operational step is Gün's: create the Hetzner server (or another always-on host), rotate
the Tiingo token, and start a live run.

## 3. First actions for the new coordinator

1. The handoff docs are on `main` (PR #14, MOS-MIG-1 done). Re-check `git log origin/main` for
   anything merged after 2026-11-10.
2. Ask Gün, in one message, the open questions in §6 (at minimum Q-01, Q-02, Q-03).
3. Ask Gün to approve M2 (scope in TASK_REGISTRY MOS-M2). Do not start before the answer.
4. Once approved: one worktree per milestone, e.g.
   `git worktree add ../mos-m2 -b m2/evaluation-v2 origin/main`; implementer agent writes failing
   tests first; a different agent reviews against MOS-M2 acceptance criteria and audit F1/F3/F9.
5. Keep `TASK_REGISTRY.md` statuses current in each PR.

## 4. Recommended execution order

1. ~~MOS-MIG-1 publish this handoff~~ done (PR #14).
2. MOS-CFG-1 merge rule for agents; MOS-SEC-1 rotate token (Gün).
3. MOS-OPS-1 / MOS-OPS-2 deploy and live run (Gün acts; agents guide). Starts the data clock, which
   M8 and M9 need and which takes months — so start it early, in parallel with code work.
4. **MOS-M2** evaluation v2 + calendar (P0), with MOS-M1-FU1 folded in.
5. MOS-M3 execution-time model and MOS-M5 strategy identity (independent; parallel worktrees ok,
   but both touch `trading/engine.py`, so merge one and rebase the other).
6. MOS-OPS-3 Tiingo field check → MOS-M4 corporate actions.
7. MOS-M6 baselines → MOS-M7 daily workflow/report (+F10, F11).
8. MOS-INV-1..4 any time as read-only side work; MOS-DEBT-1/2 bundled into a milestone PR.
9. MOS-M8 once ~weeks of live news exist; MOS-M9 only after the data gate; MOS-M10 only if Gün wants it.

## 5. Do not restart or redo

- Phases 1–10, README (#11), DEPLOY guide + `packaging` fix (#12), **M1 (#13)**. All merged.
- The audit itself: it is complete; extend it, do not redo it.
- Do not re-propose rejected approaches (DECISIONS.md list).

## 6. Open questions for Gün

| ID | Question | Why it matters |
|---|---|---|
| Q-01 | Was the Hetzner server created? If yes, is the stack running and since when? | live data clock; whether a production-like DB with history now exists that migrations must respect |
| Q-02 | Is M2 approved as described in MOS-M2? | next engineering step |
| Q-03 | Which agents may merge their own PRs after green CI, if any? | D-14 was given to the old Claude coordinator only |
| Q-04 | Was the Tiingo token rotated? | security |
| Q-05 | Agree the ML data gate (audit suggests ≥ 1,000 independent forecasts over ≥ 6 months)? | M9 |
| Q-06 | Is a local Docker database on Gün's machine holding paper history worth keeping? | history cannot be recreated |
| Q-07 | May the merged branches `claude/phase1-foundation-y6tj5f` and `claude/project-thread-vmcf8w` be deleted? | hygiene |

## 7. Migration readiness audit (2026-11-09)

**Verdict: READY FOR MIGRATION** once PR #14 is on `main`: all code is merged, no work is in
flight, and every decision and open task is recorded here. Open items are Gün's decisions and
actions (§6), not lost state.

Cross-checked: GitHub (PRs #1–#13, branches, issues, CI runs), repo `main`, project memory (5
files), the four thread records and project chat, the project files folder.

- **Missing context:** whether deployment happened (Q-01); state of any local or server database;
  older phase-thread messages beyond the summarised memory (low risk, memory covers decisions);
  the audit's seven reproduction probes (not kept; A, B, C, G live on as M1 regression tests; E, F
  and weekend must be rewritten).
- **Contradictions found:** (a) project memory file `marketos-audit-2026-11` still says "do not
  start M1 until Gün approves" while it also records M1 as merged — M1 is done (verified on GitHub).
  (b) Old project-files copy `marketos/ARCHITECTURE.md` (2026-09-29, 852 lines) is stale vs repo
  (869 lines) — repo wins. (c) ARCHITECTURE.md §9 rule 3 "≤ 1 trading day" vs config 100 h/54 h — known as F9.
  (d) Self-merge authority (D-14) vs M1 thread asking before merging — resolved by MOS-CFG-1.
- **Stale statuses:** audit thread is "done" but not resolved in the old project (harmless).
  README "Status" table does not mention the audit or M1 (minor; update with M2).
- **Duplicates:** none in the registry. Audit F-items map 1:1 to milestones; L10 already fixed.
- **Work only in cloud sessions:** none of the code. Only this handoff (local branch, not pushed)
  and the audit probes (lost). The audit document itself was only in project files; it is now
  copied into `docs/audit/` byte-for-byte (sha256 `d1d0bae2c2a54a01492862e48c5c2a9435d7a33a0190df18b0a47503a1068e36`).
- **Must not restart:** see §5.
- **Needs Gün's approval:** pushing this branch, M2 and every later milestone, branch deletion,
  merge authority, anything that costs money or exposes ports.

## 8. Risks of stopping the old cloud sessions

- No running work is lost: every code change is merged on GitHub.
- The cloud sandbox holding `migration/handoff` is ephemeral. If it is reclaimed before the push,
  the copies in the old project files folder `migration/` are the only ones. Download them or push first.
- Project memory and thread history stay in the old project but will not be readable by agents in
  T3 Code; their content is in `docs/agent/`.
