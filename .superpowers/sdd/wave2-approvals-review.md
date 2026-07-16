# Wave 2 React Review — Hermes Gate 2 CAS Approvals UI

**Reviewer role:** senior React specialist (hooks, React Query, a11y, React security)  
**Scope:** Hermes Approvals Gate 2 CAS mutation surface only (not Tasks read model, not Agent Studio)  
**Focus contract:** no digest invent · detail re-fetch · note required · no buttons for migration/corrupt · mutation only review endpoint  
**Platform commit:** `8052fe6ba39e41cb17c4bcecc25e0fed6706b6d4`  
**Platform root:** `/Users/sunyibo/programs/ai-quant-platform`  
**Date:** 2026-07-14  

**Assessment: Approved**

No CRITICAL or HIGH React/CAS issues. Gate 2 mutation path is detail-bound, note-gated, and fail-closed for migration/corrupt. Residual items are MEDIUM (dialog a11y, whitespace note schema, React Compiler `watch` warning).

---

## Files reviewed

| Path | Role |
|------|------|
| `src/frontend/lib/hermes/gate2Review.ts` | Pure Gate 2 readiness predicates |
| `src/frontend/lib/hermes/gate2Review.test.ts` | Unit coverage of canReview / list-row gates |
| `src/frontend/components/hermes/approvals/HermesGate2ReviewControls.tsx` | Client dialog + mutation |
| `src/frontend/app/hermes/approvals/page.tsx` | Server list shell + control mount gate |
| `src/frontend/lib/api.ts` | `getAgentCandidateDetail` soft-fail fallback; `AgentReviewRequest` |
| `src/frontend/lib/apiClient.ts` | `apiPost` only |
| `src/frontend/components/ui/primitives.tsx` | `TerminalToolbarButton` = real `<button>` |
| `src/frontend/tests/e2e/hermes-workbench.spec.ts` | Combined-fixture Gate 2 controls |
| `src/frontend/tests/support/hermes-fixture-api.mjs` | GET detail + POST review still 405 in fixture |

Cross-check only (not in this commit’s mutation surface): legacy `AgentTaskForm` ReviewDialog uses the same CAS pattern; Hermes improves it with explicit `noteEmpty` disable + extracted pure helpers.

---

## Focus checklist

| Requirement | Status | Evidence |
|---|---|---|
| **No digest invent** — never build/use list-row digest as CAS authority | **Met** | POST body uses `detail.manifest_digest` only after `canReviewCandidateDetail(detail)`; list digest is display-only via `candidateDigestPresentation` |
| **Detail re-fetch** before approve/reject | **Met** | `useQuery` → `getAgentCandidateDetail` with `enabled: open && isHydrated`, `staleTime: 0`, `refetchOnMount: "always"`; Confirm disabled while `isLoading`/`isFetching` |
| **Note required** (human, non-empty, never auto-filled) | **Met** | `defaultValues: { note: "" }`; zod `min(1)`; `noteEmpty` disables Confirm; e2e asserts Confirm disabled without note |
| **No buttons for migration/corrupt** | **Met** | `listRowShowsGate2Controls` requires `approval_enabled === true && status === "pending" && integrity_state === "verified"`; page mounts controls only when true; degraded fixture e2e expects 0 controls |
| **Mutation only review endpoint** | **Met** | Sole write: `apiPost(\`/api/agent/candidates/${id}/review\`, { decision, note, expected_manifest_digest, expected_status: "pending" })` |
| `eslint-plugin-react-hooks` present | **Met** | via `eslint-config-next`; targeted lint: 0 errors (1 React Compiler `watch` warning) |
| Typecheck | **Met** | `npm run type-check` clean |
| Unit tests | **Met** | `vitest` `gate2Review.test.ts` — 8 passed |

---

## What was verified

### 1. Pure CAS predicates (`gate2Review.ts`)

```16:42:src/frontend/lib/hermes/gate2Review.ts
export function canReviewCandidateDetail(
  detail: AgentCandidateDetailResponse | undefined | null,
): detail is ReviewableCandidateDetail {
  if (!detail) return false;
  if (detail.approval_enabled !== true) return false;
  if (detail.status !== "pending") return false;
  if (detail.integrity_state !== "verified") return false;
  if (detail.approval_binding !== "pending") return false;
  const digest = detail.manifest_digest;
  return typeof digest === "string" && MANIFEST_DIGEST_RE.test(digest);
}

export function listRowShowsGate2Controls(candidate: {
  approval_enabled?: boolean | null;
  status?: string | null;
  integrity_state?: string | null;
}): boolean {
  return (
    candidate.approval_enabled === true &&
    candidate.status === "pending" &&
    candidate.integrity_state === "verified"
  );
}
```

- Strict `=== true` / exact string matches — no truthy coercion.
- Digest authority requires full lowercase 64-hex (`^[0-9a-f]{64}$`); uppercase / short / missing rejected (unit-tested).
- Soft-fail detail fallback (`getAgentCandidateDetail`) sets `approval_enabled: false`, `integrity_state: "corrupt"`, `manifest_digest: null` → cannot pass `canReviewCandidateDetail`.
- List-row gate is **entry-only**; comments and dialog re-validate via detail.

### 2. Detail-first mutation (`HermesGate2ReviewControls.tsx`)

```100:125:src/frontend/components/hermes/approvals/HermesGate2ReviewControls.tsx
  const detailQuery = useQuery({
    queryKey: ["hermes-gate2-candidate-detail", candidate.candidate_id],
    queryFn: () => getAgentCandidateDetail(candidate.candidate_id),
    enabled: open && isHydrated,
    staleTime: 0,
    refetchOnMount: "always",
  });

  const detail = detailQuery.data;
  const reviewReady = canReviewCandidateDetail(detail);

  const mutation = useMutation({
    mutationFn: (values: ReviewValues) => {
      // Always re-validate the latest detail object; digest comes only from detail.
      if (!canReviewCandidateDetail(detail)) {
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

- Query off until dialog open + hydrated — no speculative client detail fetch on page load.
- Fresh bind per open (`staleTime: 0` + `refetchOnMount: "always"`).
- Confirm blocked while detail is loading/fetching → cannot race submit against a previous cache entry mid-refetch.
- `expected_status` is the literal `"pending"` (CAS field), not list-derived status.
- List `candidate` supplies **identity** (`candidate_id`) only for the URL; never list digests for CAS.
- `apiPost` → single review path; no alternate approve/register endpoints.

### 3. Note gate

```74:76:src/frontend/components/hermes/approvals/HermesGate2ReviewControls.tsx
const reviewSchema = z.object({
  note: z.string().min(1, "Review note is required").max(2000),
});
```

- Form defaults to empty string; reset on open/success.
- `noteEmpty = !noteValue?.trim()` keeps Confirm disabled for blank/whitespace in the UI.
- Playwright: open 批准 → digest visible → Confirm disabled until note.

### 4. Server shell mount gate (`approvals/page.tsx`)

- Server Component lists candidates; mounts `HermesGate2ReviewControls` only when `listRowShowsGate2Controls(candidate)`.
- Migration rows render evidence panel (`observed_manifest_digest`) without controls.
- Corrupt rows render error code + “No source preview” without controls.
- Stable list keys: `key={candidate.candidate_id}`.
- Heading order: page `h1` → section `h2` → card `h3` (candidate id).

### 5. Hooks / React Query discipline

- No conditional hooks; early return in `HermesGate2ReviewControls` is after the export function’s control flow but **before** any hooks in that component (it only gates render of two dialogs). Each `Gate2ReviewDialog` always calls the same hooks unconditionally — **rules-of-hooks OK**.
- `useIsHydrated` prevents SSR/client control mismatch on open buttons.
- Mutation success: toast → form reset → close → `router.refresh()` to re-read server list.
- Query key namespaced `hermes-gate2-candidate-detail` (distinct from Agent Studio `agent-candidate-detail`) — intentional isolation.

### 6. Accessibility (passable; residual MEDIUM)

- `TerminalToolbarButton` renders a real `<button type="button">` with focus-visible outline and disabled opacity.
- Touch targets use `min-h-[44px]` / `app-touch-target`.
- Note field wrapped in `<label>` with visible text.
- Dialog uses `role="alertdialog"` + `aria-modal="true"` (same pattern as Agent Studio).
- Missing focus trap / Escape / `aria-labelledby` — see MEDIUM findings (not Gate 2 correctness).

### 7. Security (React lane)

- No `dangerouslySetInnerHTML`.
- No user-controlled `href`/`src` schemes.
- No client env secrets (`NEXT_PUBLIC_*` private keys) in this surface.
- Mutation body is structured CAS fields only; note is plain text, max 2000.

---

## Findings

### CRITICAL

_None._

### HIGH

_None._

### MEDIUM

```
[MEDIUM] Dialog a11y incomplete (focus / Escape / labelledby)
File: src/frontend/components/hermes/approvals/HermesGate2ReviewControls.tsx:172-178
Issue: alertdialog lacks aria-labelledby/aria-describedby, focus trap, initial focus, and Escape-to-close.
Why: Keyboard and screen-reader users can tab behind the modal and may not get a named dialog context.
Fix: Wire aria-labelledby to the title id, move focus into the dialog on open, restore focus on close, handle Escape, optionally use a small focus-trap utility. Matches residual debt on Agent Studio ReviewDialog.
```

```
[MEDIUM] Zod note allows whitespace-only while UI trims
File: src/frontend/components/hermes/approvals/HermesGate2ReviewControls.tsx:74-76, 147
Issue: UI disables Confirm via noteValue.trim(), but reviewSchema is z.string().min(1) which accepts "   ".
Why: A programmatic submit path (or future type="submit") could POST a whitespace note that is not a real human rationale.
Fix: note: z.string().trim().min(1, "...").max(2000) (or refine) so schema and UI agree.
```

```
[MEDIUM] React Compiler warns on form.watch
File: src/frontend/components/hermes/approvals/HermesGate2ReviewControls.tsx:98
Issue: eslint react-hooks/incompatible-library flags form.watch("note") under React Compiler memoization rules.
Why: watch() is not compiler-memo-safe; currently a warning only (lint --max-warnings=0 fails if run with that flag on this file).
Fix: Prefer form.formState / Controller / useWatch from react-hook-form, or subscribe via form.watch((v) => ...) in an effect if needed; acceptable to leave with project-wide RHF pattern acknowledgment.
```

```
[MEDIUM] List-row gate omits approval_binding === "pending"
File: src/frontend/lib/hermes/gate2Review.ts:32-42
Issue: listRowShowsGate2Controls checks approval_enabled + status + integrity only, not approval_binding.
Why: An anomalous list row (verified pending status, non-pending binding) could show Approve/Reject; dialog still fail-closes via canReviewCandidateDetail — no CAS bypass, but noisy UX.
Fix: Align list gate with detail: also require approval_binding === "pending" when the list contract exposes it.
```

---

## Explicit non-issues (contract)

| Risk | Why not a finding |
|------|-------------------|
| List digest used for POST | Never referenced in mutationFn; only `detail.manifest_digest` after type guard |
| Confirm without re-fetch at click | Open-time re-fetch + disable while fetching is the established Agent Studio CAS pattern; server CAS still rejects stale digest |
| migration_required observed digest authorizes | Display-only; canReview requires authoritative `manifest_digest` + verified + approval_enabled |
| Alternate mutation endpoints | Only `/review` via `apiPost` |
| Conditional hooks | Dialog hooks unconditional; parent early-return is hook-free |
| `key={index}` | Uses `candidate.candidate_id` |
| Secret leakage in client bundle | No secrets in this surface |

---

## Diagnostics run

```text
vitest run lib/hermes/gate2Review.test.ts     → 8 passed
npm run type-check                            → clean
eslint … HermesGate2ReviewControls + gate2…   → 0 errors; 1 warning (form.watch)
```

---

## Verdict

**Approved** — safe to merge from a React/Gate 2 CAS perspective.

The Hermes Approvals UI correctly:

1. Shows mutation controls only for `approval_enabled + verified + pending` list rows.
2. Re-fetches candidate **detail** on dialog open and binds `expected_manifest_digest` exclusively from that detail.
3. Requires a human note before Confirm.
4. Keeps migration/corrupt evidence-only.
5. Mutates solely through `POST /api/agent/candidates/{id}/review` with CAS fields.

Follow-ups (non-blocking): dialog focus management, `z.string().trim().min(1)`, optional list-gate `approval_binding`, and RHF `useWatch` for compiler cleanliness.

---

## Related

- Delivery report: `.superpowers/sdd/wave2-approvals-tasks-report.md`
- Plan: `docs/superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md` (Task B)
- Prior CAS React review (Agent Studio): `.superpowers/sdd/candidate-task-5-react-review.md`
