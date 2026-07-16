# Candidate Task 5 React Review — Frontend CAS (Agent Studio)

**Reviewer role:** senior React specialist (hooks, React Query, a11y, React security)  
**Scope:** Detail-first CAS in Agent Studio; disable without digest; no mutation without both CAS fields; React Query correctness  
**Platform commit:** `392485ad190020c6179ad1a563a6cacf485f7e6d`  
**Files reviewed:**
- `src/frontend/components/forms/AgentTaskForm.tsx`
- `src/frontend/lib/api.ts` (candidate types + `getAgentCandidateDetail` fallback)
- `src/frontend/lib/api.generated.ts` (`AgentReviewRequest`, detail/list schemas)
- `src/frontend/app/agent-studio/page.tsx` (server shell wiring)
- `src/frontend/components/Providers.tsx` (QueryClient defaults)
- Cross-check: Hermes workbench remains read-only (no approve/reject surface)

**Date:** 2026-07-13  
**Assessment: Approved**

No CRITICAL or HIGH React/CAS issues. Mutation path is detail-bound and fail-closed. Residual items are MEDIUM (UX, test coverage, defense-in-depth consistency).

---

## Brief compliance checklist

| Requirement | Status | Evidence |
|---|---|---|
| Detail-first CAS: read selected candidate detail before review | **Met** | `ReviewDialog` `useQuery` → `getAgentCandidateDetail` when dialog opens; POST uses `detail.manifest_digest`, not list summary |
| Submit both `expected_manifest_digest` and `expected_status: "pending"` | **Met** | `AgentTaskForm.tsx` mutation body lines 177–181 |
| Disable approve/reject when detail unavailable / not pending / no digest | **Met** | `canReview` + `controlsDisabled`; outer `reviewAllowed` gates button mount |
| Disable when `approval_enabled` is false | **Met** | Outer gate + open button + `canReview` (`=== true` on submit path) |
| Migration observed digest never authorizes approval | **Met** | Display-only; `canReview` requires authoritative `manifest_digest` hex-64 + `approval_enabled === true` |
| OpenAPI / shared types carry CAS fields | **Met** | `api.generated.ts` `AgentReviewRequest`; hand types in `api.ts` |
| Hermes does not offer mutation without CAS | **Met** | Hermes page is read-only candidate list; no review POST |
| `eslint-plugin-react-hooks` present | **Met** | via `eslint-config-next`; `npm run lint` clean |
| Typecheck | **Met** | `npm run type-check` clean |

---

## What was verified

### Detail-first CAS (`ReviewDialog`)

```158:181:src/frontend/components/forms/AgentTaskForm.tsx
  const detailQuery = useQuery({
    queryKey: ["agent-candidate-detail", candidate.candidate_id],
    queryFn: () => getAgentCandidateDetail(candidate.candidate_id),
    enabled: open && isHydrated,
    staleTime: 0,
    refetchOnMount: "always",
  });
  // ...
  const mutation = useMutation({
    mutationFn: (values: ReviewValues) => {
      if (!canReview(detail)) {
        throw new Error("candidate detail is not reviewable");
      }
      return apiPost<AgentReviewResponse>(
        `/api/agent/candidates/${candidate.candidate_id}/review`,
        {
          decision,
          note: values.note,
          expected_manifest_digest: detail.manifest_digest,
          expected_status: "pending" as const,
        },
      );
    },
```

- Query is **off until dialog open + hydrated** — no speculative client fetch.
- `staleTime: 0` + `refetchOnMount: "always"` force a fresh detail bind per open.
- Confirm is disabled while `isLoading` / `isFetching`, so a background refetch cannot race a submit against a previous cache entry.
- List-row `manifest_digest` is display-only; the POST never reads list fields for CAS.

### Fail-closed `canReview` gate

```129:138:src/frontend/components/forms/AgentTaskForm.tsx
function canReview(detail: AgentCandidateDetailResponse | undefined): detail is AgentCandidateDetailResponse & {
  manifest_digest: string;
} {
  if (!detail) return false;
  if (detail.approval_enabled !== true) return false;
  if (detail.status !== "pending") return false;
  if (detail.integrity_state && detail.integrity_state !== "verified") return false;
  const digest = detail.manifest_digest;
  return typeof digest === "string" && /^[0-9a-f]{64}$/.test(digest);
}
```

- Strict `approval_enabled === true` (not merely truthy-from-list).
- Status must be `"pending"`.
- Non-verified integrity (`migration_required` / `corrupt` / other) blocks.
- Digest must match backend pattern `^[0-9a-f]{64}$` before type-narrowing into the POST body.
- Soft-fail detail fallback in `getAgentCandidateDetail` sets `approval_enabled: false` and null digests → cannot pass `canReview`.

### Outer list gate (button surface)

- Prefers verified pending with `approval_enabled !== false`.
- Falls back to any pending for display only; `reviewAllowed` still false for migration/corrupt → shows `reviewDisabled` copy, no Approve/Reject mount.
- Open button additionally disables when list says `approval_enabled === false`.

### React Query / providers

- Global `mutations.retry: false` — review lock write is not retried (correct for non-idempotent human gate).
- Global `queries.retry: 1`, `refetchOnWindowFocus: false` — dialog relies on open-gated fetch + `staleTime: 0`.
- Shared `queryKey` between Approve/Reject dialogs correctly shares cache for the same `candidate_id`.
- Success path: toast + close dialog + `router.refresh()` (RSC list/detail shell). Acceptable; no client cache poisoning of CAS fields into the POST (POST always re-reads current `detail` at mutate time via latest observer options in RQ v5).

### Security (React lane)

- No `dangerouslySetInnerHTML`.
- Review note is JSON body via `apiPost`, not HTML injection.
- Source preview on the server page is plain-text `<pre>{source_preview}</pre>` (React-escaped).
- No client-bundled secrets in this change (`NEXT_PUBLIC_*` only for API base, pre-existing).
- No `javascript:` / user-controlled `href` introduced.

### Accessibility (touched surface)

- Note field uses wrapping `<label>` (accessible name present).
- Controls are real `<button>`s via `TerminalToolbarButton`.
- Dialog uses `role="alertdialog"` + `aria-modal="true"` (pre-existing pattern; residual gaps below).

### Tooling re-run

```text
cd src/frontend && npm run type-check   # clean
cd src/frontend && npm run lint         # clean
```

---

## Findings

### [MEDIUM] Soft-failing `apiGet` makes React Query treat detail failures as success

**File:** `src/frontend/lib/api.ts:1917-1961` (via `getAgentCandidateDetail`)  
**File:** `src/frontend/components/forms/AgentTaskForm.tsx:158-164, 192-199`

**Issue:** `getAgentCandidateDetail` never throws; network/HTTP failures return the fallback envelope with `apiError` and `approval_enabled: false`. React Query therefore sets `isSuccess` / never sets `isError`, so `detailQuery.error` is always undefined and the dialog error branch never surfaces load failures. Global `queries.retry: 1` also never runs for soft-failures.

**Why:** CAS remains fail-closed (confirm stays disabled), but operators see only the generic “review disabled” copy instead of the real transport/API error, and RQ retry/error semantics are bypassed for this query.

**Fix (optional):** For the dialog path only, either:
1. Throw when `apiError` is present inside `queryFn`, or
2. After success, branch on `detail.apiError` and render that message; treat soft-fail as non-reviewable explicitly in the UI.

Do **not** change the fallback to `approval_enabled: true`.

---

### [MEDIUM] Outer list gate is looser than submit gate on `approval_enabled`

**File:** `src/frontend/components/forms/AgentTaskForm.tsx:322-336, 208`

**Issue:** List/selection uses `approval_enabled !== false` (allows `null`/`undefined`); submit uses `approval_enabled === true`. Open button disables only on `=== false`.

**Why:** During schema transition, Approve/Reject can mount and open a dialog that immediately cannot confirm. Not a CAS bypass (mutation still fail-closed), but inconsistent UX and a footgun if a future change weakens `canReview`.

**Fix:** Align outer gates with submit: require `approval_enabled === true` (and ideally a list-side authoritative digest) before mounting dialogs.

---

### [MEDIUM] No component-level test that the review POST body always carries both CAS fields

**File:** `src/frontend/components/forms/AgentTaskForm.tsx`  
**Existing:** `tests/test_frontend_run_response_type_contract.py` only asserts shared type imports / `apiPost<AgentReviewResponse>` string presence.

**Issue:** No vitest/RTL or e2e coverage that:
- confirm is disabled without detail digest / `approval_enabled`
- successful confirm posts `{ expected_manifest_digest, expected_status: "pending" }` from **detail**, not list
- migration/corrupt never enables confirm

**Why:** Backend contract tests cover the API; a frontend regression (e.g. wiring list digest, dropping `expected_status`) would not be caught by current frontend suites.

**Fix:** Add a focused vitest (mock `getAgentCandidateDetail` + `apiPost`) for `canReview` matrix + mutation payload; optional Playwright smoke on Agent Studio.

---

### [MEDIUM] Alertdialog missing labelled-by / focus management (pre-existing, still present)

**File:** `src/frontend/components/forms/AgentTaskForm.tsx:214-220`

**Issue:** `role="alertdialog"` + `aria-modal="true"` without `aria-labelledby` / `aria-describedby`, Escape-to-close, or focus trap / restore.

**Why:** Keyboard and AT users can lose context in a modal gate that writes lock files.

**Fix:** Wire `aria-labelledby` to the title `id`, trap focus while open, close on Escape, restore focus to the trigger.

---

## Non-issues (explicitly checked)

| Concern | Result |
|---|---|
| Conditional hooks | None — hooks always called at top of `ReviewDialog` / `AgentTaskForm` |
| Submitting list digest | Not present — only `detail.manifest_digest` after `canReview` |
| Submitting without `expected_status` | Not present — always `"pending" as const` |
| Observed migration digest in POST | Not present — display only |
| Hermes approve surface | None — read-only |
| `key={index}` on review controls | N/A — dialogs are not a dynamic list of mutable rows |
| Direct state mutation | None |
| `dangerouslySetInnerHTML` | None in touched CAS path |
| Secret env in client CAS path | None introduced |

---

## Residual notes (informational, not blocking)

1. `expected_status` is a literal `"pending"` rather than `detail.status`; equivalent under `canReview` (`status === "pending"`) and matches the API `Literal["pending"]` schema.
2. `canReview` allows `integrity_state == null` when `approval_enabled === true` and digest is valid — defense-in-depth could require `=== "verified"` once all backends always emit the field.
3. Success does not `queryClient.invalidateQueries`; `router.refresh()` updates the RSC shell. A second open of the same id refetches via `staleTime: 0` / enable-edge. Stale approve attempt correctly becomes HTTP 409 from the backend.
4. Dedicated frontend audit file `candidate-task-5-frontend-audit.md` was not present at review time; this report is based on committed code + brief + delivery report.

---

## Verdict

**Approved** for Task 5 frontend CAS.

Agent Studio implements detail-first Gate 2 review: detail is loaded on dialog open, confirm is disabled until a verified pending detail with an authoritative digest is present, and the mutation always posts both CAS fields. Soft-fail detail loading and outer-gate looseness are MEDIUM polish items, not CAS bypasses. Typecheck and lint are clean.

**Merge posture:** safe to land alongside platform API/CLI CAS (already in `392485a`); optional follow-ups for soft-fail error surfacing, gate alignment, and component tests.
