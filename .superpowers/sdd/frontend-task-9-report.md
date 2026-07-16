# Frontend Task 9 Report — Full verification, review, docs reconciliation

**Status:** DONE  
**Date / smoke:** 2026-07-14  
**Platform branch:** `audit-remediation-2026-06-23`  
**HQA branch:** `codex/full-9h`  
**Not pushed** (controller owns push)

## Commits

| Repo | SHA | Subject |
|---|---|---|
| platform | `f658226a9d598fec0dfaffddf1e3a3ab97828d42` (`f658226`) | `test(frontend): align Hermes E2E with F2 hierarchy and fixtures` |
| platform | `ab932f30a49f44cd8a5f4a963964e90312ff87b2` (`ab932f3`) | `docs(frontend): record Hermes read-only shell delivery` |
| HQA | `cc7425715f572e02d60261638aab3f37d1d701e4` (`cc74257`) | `docs(frontend): reconcile Hermes read-only shell delivery` |

**F2 feature HEAD before this task:** `9db8e0c` — `feat(frontend): make Hermes the reversible default research home`  
**Preserved dirty/untracked (not staged):**  
- platform: `data/options_universe/earnings_calendar.csv`, `.understand-anything/diff-overlay.json`  
- HQA: `.superpowers/`

## Cross-plan barrier (before shared docs)

| Plan | Evidence | Verdict |
|---|---|---|
| Gateway Task 4 | HQA `ea0b297` docs(review) fail-closed; Stage A/B CLEAR; `verdict: blocked` chat | Complete — sibling facts preserved |
| Candidate Task 8 | platform `1589886` docs + HQA `a5d9cb1` reconcile; `320` focused + full gates recorded | Complete — sibling facts preserved |
| Frontend Tasks 1–8 | platform `9db8e0c` cutover; F0/F1 approvals in `docs/design/hermes-workbench/README.md` | Code delivered; this task verifies + reconciles |

No unexplained concurrent diffs on shared status surfaces. Task 9 is sole reconciliation owner.

## Step 1 — Frontend static gates

```text
npm --prefix src/frontend run test          → 113 passed (28 files)
npm --prefix src/frontend run type-check    → clean
npm --prefix src/frontend run lint          → clean
npm --prefix src/frontend run build         → success (Next.js 15.5.15; /hermes + subroutes present)
node --test src/frontend/tests/support/hermes-fixture-api.test.mjs → 7 passed
hard-off env grep (non-test)               → 0 hits
mutation grep (app/hermes + components/hermes) → 0 hits
  (AgentTaskForm|useMutation|apiPost|/api/agent/tasks|WebSocket|EventSource)
```

## Step 2 — Partitioned hermetic E2E

```text
# non-fixture / non-rollback (isolated temp backend :8766, frontend :3002)
--grep-invert "@combined-fixture|@rollback"  → 55 passed

# combined-fixture workbench
PW_HERMES_WORKBENCH_FIXTURE=normal|degraded hermes-workbench.spec @combined-fixture
  → 3 + 3 = 6 passed

# combined-fixture visual matrix (no --update-snapshots)
normal zh+en ×4 viewports = 8
degraded|offline|empty|long-content zh ×4 = 16
  → 24 passed

# rollback second process :3003 + nav/locale under rollback env
hermes-rollback + navigation-layout + locale-toggle → 11 passed
```

### Verification fix included in this task

1. **`hermes-workbench.spec.ts` F2 subroutes** — degraded fixture uses `legacy-pending-migration` + migration evidence digest `b*64`, not the normal verified candidate/`a*64`. Assertions are now fixture-aware.  
2. **`hermes-artifacts.spec.ts`** — F2 compresses automation to `AutomationSummary` (`自动化 0/4 正常` + 已降级), not a full-card heading `自动化状态`; composer name is `和 Hermes 对话`.

## Step 3 — Independent review summary (cite prior task reviews)

| Source | Verdict | Residual |
|---|---|---|
| F0 UX `frontend-task-1-ux-review.md` | Pass (all 3 directions selectable) | User selected direction-a |
| F0 polish / finance / token rebind reports | Craft accepted with QUANTUM_CORE rebind | — |
| Task 3 TS `frontend-task-3-review.md` | **Approved** | MEDIUM: type cast / fixture allowlist drift |
| Task 4 React `frontend-task-4-review.md` | Needs fixes → fixed in `fb98f19` | Heading order, Conversation aria, composer live region |
| Tasks 5–6 React `frontend-task-5-6-review.md` | **Approved** | MEDIUM: foresight key, status tone map, pickLatestAutomation dupe |
| Task 7 report | Visual/a11y baselines 24 snapshots | Implementer spot-check OK |
| Task 8 report | Reversible home cutover | Rollback second process green |

### Checklist (Task 9 brief)

| Gate | Result |
|---|---|
| Five-second comprehension; action/exception hierarchy | Pass (Today hierarchy + fixture E2E) |
| One safety message | Pass (single `global-safety-strip`) |
| Normal automation compression | Pass (`自动化 N/4 正常`) |
| Chinese/English long content | Pass (visual matrix + long-content fixture) |
| Keyboard/focus; 44px; reduced motion; no scroll hijack | Pass (page gates + visual matrix) |
| 0 console issues | Pass (visual matrix asserts empty console) |
| Disabled composer honesty | Pass |
| Static `blocked_in_this_slice` | Pass (`data-delivery-state`) |
| Non-shell env overrides ineffective | Pass (unit + hard-off greps) |
| Enabled/rollback navigation | Pass (nav + rollback E2E) |
| No old deep-link regression | Pass (phase10 + run-detail suites in 55) |
| No mutation path | Pass (greps + subroute E2E) |

No new CRITICAL/HIGH findings in this verification pass. Prior MEDIUM notes remain non-blocking follow-ups.

## Step 4 — Local read-only runtime smoke (2026-07-14)

Process: platform backend `http://127.0.0.1:8765` (health ok, paper true, live false); frontend production `next start` `http://127.0.0.1:3001`.

| Route | Result |
|---|---|
| `/zh/hermes` | 200 — safety strip, 研究态势, `blocked_in_this_slice`, disabled composer |
| `/zh/hermes/tasks` | 200 — Hermes chrome + capability notice |
| `/zh/hermes/approvals` | 200 |
| `/zh/hermes/results` | 200 |
| `/en/hermes` | 200 |
| `/` | 307 → `/en/hermes` |
| `/zh` | 307 → `/zh/hermes` |

Rollback second-process path re-verified via Playwright `@rollback` (Dashboard home + separate read-only Hermes). **No** prompt, approve, research, or provider calls.

## Step 5 — Docs reconciliation

### Documented delivery facts

- F0 approved: `direction-a` (user, 2026-07-13); craft accepted with QUANTUM_CORE token rebind  
- F1 approved: 2026-07-13 with token rebind  
- F2 read-only shell delivered; enabled root/nav → Hermes; rollback → Dashboard home, direct `/hermes` still read-only  
- chat / execution / unifiedResults / legacyRedirects literal false under env=true  
- capability notice static `blocked_in_this_slice` (no platform capability getter in this wave)  
- old four research pages retained pending parity  
- Gateway chat remains fail-closed (separate contract plan)  
- Candidate integrity/Gate 3 remains code-delivered; migration apply + new approval UI still closed  

### Files updated

- platform `docs/INDEX.md`, `docs/design/hermes-workbench/README.md`  
- HQA `docs/README.md`, `docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`  

Sibling plan status was **not** marked incomplete; their completed evidence left intact.

## Exact counts snapshot (2026-07-14)

| Suite | Count |
|---|---|
| Vitest unit | **113 passed** / 28 files |
| Fixture API node:test | **7 passed** |
| Playwright real-backend partition | **55 passed** |
| Combined-fixture workbench | **6 passed** |
| Combined-fixture visual | **24 passed** |
| Rollback + nav/locale (rollback env) | **11 passed** |
| type-check / lint / build | clean / clean / success |
| hard-off + mutation greps | 0 / 0 |

## Out of scope (still closed)

- Hermes chat / bridge mutation (`verify-chat` not ready)  
- Approve/reject UI; real migration `--apply`  
- Unified dynamic results; legacy redirects  
- Push to origin  
