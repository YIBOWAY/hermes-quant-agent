# Frontend Tasks 5–6 — React Review

**Scope:** Hermes F2 Task 5 (Today hierarchy + focused artifact renderers) and Task 6 (truthful read-only Tasks / Approvals / Results)  
**Commits reviewed (ai-quant-platform):**
- `611735b` — `feat(frontend): prioritize Hermes action, exceptions, and conclusions`
- `fb98f19` — `fix(frontend): correct Hermes shell heading order and a11y nits` (Task 4 follow-up on shell, still in path)
- `5c21f7a` — `feat(frontend): hermes truthful tasks approvals results routes`

**Platform path:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend`  
**Briefs / reports:** `frontend-task-5-brief.md` / `frontend-task-5-report.md`, `frontend-task-6-brief.md` / `frontend-task-6-report.md`  
**Reviewer lane:** React-specific (hooks, a11y, RSC boundary, render correctness, React security, mutation-free F2 contracts)  
**Companion:** Invoke `typescript-reviewer` separately for pure TS concerns (e.g. `as` casts in `AutomationDetails`)

## Assessment: **Approved**

No **CRITICAL** or **HIGH** React issues. Task-contract items for mutation-free read-only surfaces, single global safety strip, digest display rules, and zero approve/reject controls are met. MEDIUM notes only; merge with caution is optional, not required.

## Verification run during review

| Check | Result |
|---|---|
| `npm test -- lib/hermes/candidatePresentation.test.ts lib/hermesArtifactShelf.test.ts lib/hermes/viewModel.test.ts` | 23/23 pass |
| `npm run type-check` (`tsc --noEmit`) | pass |
| `npm run lint` (`eslint-config-next` → `eslint-plugin-react-hooks`) | pass |
| `AgentTaskForm` / `useMutation` / `apiPost` / `/api/agent/tasks` under `app/hermes` + `components/hermes` | **none** |
| Inner safety Card / `ShieldCheck` / `safetyTitle` / `safetyBody` / `data-global-safety-strip` under hermes tree | **none** (global strip remains outside) |
| `"use client"` under Task 5–6 trees (`today/`, `artifacts/`, new pages) | **none** (only pre-existing `HermesInternalNav`) |
| Hooks (`useState` / `useEffect` / …) under Task 5–6 trees | **none** |
| Playwright claims (reports) | normal hierarchy + F2 subroutes; not re-run in this review (unit/static contracts verified locally) |

---

## Contract verification (user-requested focus)

| Contract | Status | Evidence |
|---|---|---|
| **Mutation-free read-only** | **Pass** | All new pages are async RSC; data via `getAgentCandidates()` / `getHermesArtifacts()` (`apiGet` only). Shell always mounts `ComposerDock` with `disabled` + `allowSubmit={false}`. No Server Actions, no forms that mutate, no `AgentTaskForm`. E2E: composer disabled on tasks/approvals/results; loopback-only guard expects zero external requests. |
| **Single safety strip** | **Pass** | Task 5 `app/hermes/page.tsx` only renders `HermesTodayView` — no inner safety `Card`. Layout → `HermesWorkbenchShell` does not reintroduce paper/live banner. E2E still asserts one `global-safety-strip` and zero `main [data-global-safety-strip]`. `ArtifactFeed` `role="status"` is feed empty/degraded announcement, not the paper/live strip; Today uses `sourcesOnly` so those regions are omitted on the primary hierarchy. |
| **Digest display rules** | **Pass** | `candidateDigestPresentation`: verified + non-empty `manifest_digest` → authoritative `<code>`; `migration_required` → `observed_manifest_digest` under “迁移证据，不能审批”; `corrupt` → stable `integrity_error_code`, **no** digest preview (even if digest fields present). Unit table covers all three paths. Approvals page branches on `digest.kind` only. |
| **No approve buttons** | **Pass** | Approvals has no `<button>` approve/reject, no review POST client. Copy explicitly states F2 cannot approve/reject. E2E: `getByRole("button", { name: /批准\|拒绝/ })` count 0. Binding tones include `legacy_unbound → danger` without enabling controls. |
| **Today hierarchy (Task 5)** | **Pass** | `AttentionSummary` → `AutomationSummary` → `RecentResults` → collapsed `TechnicalDetails` + `ArtifactFeed sourcesOnly`. Unit: `自动化 4/4 正常`, `研究审批项`, `<details`, no bare cron end-tag, no `候选</h`. Exceptions expand via `AutomationDetails open`. |
| **Tasks / Approvals / Results (Task 6)** | **Pass** | Tasks: automation-only + “研究任务账本尚未接入”. Approvals: digest-aware list + exhaustive `candidateBindingTone`. Results: “只读结果索引” + links only to `/factor-lab`, `/backtest`, `/experiments`, `/agent-studio`, `/paper-trading` (no `/hermes/results/*` detail). |
| **Exhaustive binding tones** | **Pass** | `switch` + `assertNever` over `pending\|approved\|rejected\|legacy_unbound\|null`; unit table size 5. |

---

## CRITICAL

_None._

- No `dangerouslySetInnerHTML`.
- No Server Actions / unvalidated mutations under hermes F2 surfaces.
- No client-bundle secret env hooks in Task 5–6 code.
- No conditional hooks, direct state mutation, or hooks outside components (no hooks at all in new trees).
- No `javascript:` / user-controlled `href` schemes; Attention/Results links use `hermesRouteHref` / `localizePath` with fixed path constants.

---

## HIGH

_None._

Prior Task 4 heading-order issue (`HermesCapabilityNotice` `h2` before page `h1`) is already fixed in `fb98f19` (notice title is `<p>`). Task 5–6 page titles are proper sole `<h1>`s under the shell.

---

## MEDIUM

### [MEDIUM] Foresight candidate list key ignores stable `id`

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/artifacts/ForesightSummary.tsx:65-68`

**Issue:** List keys use `` `${symbol}-${horizon_date ?? index}` `` even though `HermesForesightCandidate.id` is a required string in the generated schema.

```tsx
key={`${candidate.symbol ?? "candidate"}-${candidate.horizon_date ?? index}`}
```

**Why:** Duplicate symbol+horizon (or missing horizon falling back to index) can attach React state/identity to the wrong row if foresight candidates ever become interactive or reorder. Stable IDs already exist on the payload.

**Fix:** Prefer `key={candidate.id}` (optionally keep symbol as display only).

---

### [MEDIUM] Approvals reuses binding-tone helper for `candidate.status`

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/app/hermes/approvals/page.tsx:111-118`

**Issue:** Status pill applies `candidateBindingTone(asCandidateApprovalBinding(candidate.status))`. `status` and `approval_binding` are separate API fields; unknown status strings collapse to `null → neutral`.

**Why:** If platform `status` ever diverges from the binding enum (e.g. workflow states outside pending/approved/rejected), the pill tone silently becomes neutral and can mis-signal integrity-adjacent UX. Not a mutation risk; presentation drift only.

**Fix:** Map `status` with an explicit status→tone helper, or show status as neutral mono text unless the contract guarantees the same enum.

---

### [MEDIUM] Duplicated `pickLatestAutomation` helper

**Files:**
- `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/today/HermesTodayView.tsx:18-29`
- `/Users/sunyibo/programs/ai-quant-platform/src/frontend/app/hermes/tasks/page.tsx:9-20`

**Issue:** Identical reduce-by-`occurred_at` logic lives in two modules.

**Why:** Drift risk if “latest automation” selection rules change (e.g. filter by schema version or known job set).

**Fix:** Export one helper from `lib/hermes` (or reuse view-model selection) and import from both call sites.

---

### [MEDIUM] F2 subroute E2E does not re-assert single safety strip

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/tests/e2e/hermes-workbench.spec.ts:72-99`

**Issue:** Subroute test correctly checks headings, ledger disclaimer, zero approve buttons, verified digest, and disabled composer, but does not re-check `getByTestId("global-safety-strip")` count on tasks/approvals/results.

**Why:** Layout currently guarantees the shell; a future page-level safety Card could regress without failing this test. Residual coverage gap, not a present defect (static search shows no inner strip).

**Fix:** Add `await expect(page.getByTestId("global-safety-strip")).toHaveCount(1)` (and optionally zero `main [data-global-safety-strip]`) once per subroute visit.

---

## React / a11y notes (non-blocking)

- Heading order on new pages is sound: caps label `<p>` → page `<h1>` → section `<h2>` → item `<h3>`.
- Icons use `aria-hidden`; articles use `aria-labelledby` with `safeDomId` heading ids.
- Disclosure for cron / run ID / notification uses native `<details>` / `<summary>` with `app-touch-target` (keyboard-reachable). Exception rows set `open`.
- Results deep links are Next `<Link>`s to fixed platform paths only; no unified Hermes detail routes.
- `ArtifactShelf` remains a thin facade over focused renderers as required; production Today path uses `HermesTodayView`.

---

## Task-by-task checklist

### Task 5 — Today hierarchy & focused renderers

| Requirement | Result |
|---|---|
| Hierarchy attention → automation N/4 → recent conclusions → collapsed technical | Pass |
| Attention: approval / failure / stale / offline only | Pass (`PRIMARY_KINDS`) |
| Automation: N/4 line; only exceptions listed/expanded | Pass |
| Cron / freshness / run ID / notification inside `<details>` | Pass (`AutomationDetails`) |
| No reintroduced inner safety Card / ShieldCheck / safetyTitle | Pass |
| Data loading `Promise.all([getAgentCandidates(), getHermesArtifacts()])` | Pass (`page.tsx`) |
| RED hierarchy assertions in unit tests | Pass |

### Task 6 — Tasks / Approvals / Results

| Requirement | Result |
|---|---|
| Tasks: automation artifacts + “研究任务账本尚未接入” | Pass |
| Approvals: digest-aware candidates; StatusPill + binding tone | Pass |
| Authoritative digest only when verified | Pass |
| Migration evidence label; corrupt error code, no preview | Pass |
| No approve/reject in any integrity state | Pass |
| Results: read-only index; canonical platform links only | Pass |
| Exhaustive `candidateBindingTone` + unit table | Pass |
| No AgentTaskForm / useMutation / apiPost / `/api/agent/tasks` | Pass |
| Composer disabled via layout shell | Pass |

---

## Approval criteria mapping

| Criterion | Outcome |
|---|---|
| CRITICAL issues | 0 |
| HIGH issues | 0 |
| MEDIUM issues | 4 (optional follow-ups) |
| **Verdict** | **Approved** |

