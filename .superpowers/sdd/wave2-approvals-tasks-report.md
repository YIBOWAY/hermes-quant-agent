# D-31 Wave 2 — Hermes Approvals Gate 2 CAS + Tasks read model

**Date:** 2026-07-14  
**Repo:** `/Users/sunyibo/programs/ai-quant-platform`  
**Status:** Delivered (code + unit + combined-fixture e2e). Not pushed.

## A) Gate 2 CAS mutation

| Item | Path |
|------|------|
| Pure rules | `src/frontend/lib/hermes/gate2Review.ts` |
| Client controls | `src/frontend/components/hermes/approvals/HermesGate2ReviewControls.tsx` |
| Approvals page | `src/frontend/app/hermes/approvals/page.tsx` |

### Behavior

- List shows Approve/Reject **only** when  
  `approval_enabled === true` **and** `status === "pending"` **and** `integrity_state === "verified"`.
- `migration_required` / `corrupt` / `approval_enabled !== true`: evidence only, **no** buttons.
- On open: re-fetch `GET /api/agent/candidates/{id}` via `getAgentCandidateDetail`.
- Confirm requires:
  - `canReviewCandidateDetail(detail)`: approval_enabled, pending status, verified integrity, pending binding, **64-hex** `manifest_digest`
  - non-empty human note (never auto-filled)
- POST body: `{ decision, note, expected_manifest_digest: detail.manifest_digest, expected_status: "pending" }`
- Digest is **never** taken from list alone for the mutation.
- Primary action tone: QUANTUM_CORE **info** blue (`tone="info"`).

### Real candidate (local platform)

- id: `factor-momentum_20d_reversal-323b045e4b`
- list/fixture digest (normal hermetic): `a` × 64  
- live platform digest (when verified):  
  `294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558`

## B) Tasks realer read model

| Item | Path |
|------|------|
| Tasks page | `src/frontend/app/hermes/tasks/page.tsx` |
| Latest-by-kind helper | `pickLatestArtifactByKind` in `lib/hermes/viewModel.ts` |

### Sections

1. Honest banner: Hermes research task **write** ledger still not connected; page is **platform evidence only**.
2. Automation status headline + full jobs list (existing automation artifact).
3. Weekly review summary (`WeeklyReviewSummary`).
4. Opportunity summary counts (`OpportunitySummary`).
5. **No** create/submit task mutation; no Hermes provider calls.

## Tests

| Suite | Result |
|-------|--------|
| `vitest` `lib/hermes/gate2Review.test.ts` (+ hermesApprovals / secondary / viewModel) | 21 passed |
| `node --test tests/support/hermes-fixture-api.test.mjs` | 8 passed (incl. GET detail, POST review still 405) |
| Playwright `@combined-fixture F2 subroutes` **normal** | passed (controls + confirm disabled without note) |
| Playwright `@combined-fixture F2 subroutes` **degraded** | passed (no buttons on migration_required) |

### Fixture support

`tests/support/hermes-fixture-api.mjs`:

- `GET /api/agent/candidates/{id}` synthesized from list rows
- CORS for browser detail re-fetch
- Non-GET still 405 (no review mutation in hermetic mode)

## Commit

```
8052fe6 feat(frontend): Hermes Gate 2 CAS approvals + Tasks evidence read model
```

Dirty preserved (not in commit):  
`earnings_calendar.csv`, options `data_refresh` files, `.understand-anything/`.

## How to verify in UI

1. Start platform stack (backend + frontend) with candidate integrity verified.
2. Open `/zh/hermes/approvals` (or `/en/hermes/approvals`).
3. For `factor-momentum_20d_reversal-323b045e4b` with `approval_enabled` + verified pending: see **批准 / 拒绝** (info blue primary).
4. Click 批准 → dialog loads detail digest → Confirm disabled until non-empty note → POST CAS review.
5. Open `/zh/hermes/tasks`: banner about write ledger; automation jobs; weekly review; opportunity counts; no create/submit.

Hermetic check:

```bash
cd src/frontend
npm test -- lib/hermes/gate2Review.test.ts
PW_E2E=1 PW_HERMES_WORKBENCH_FIXTURE=normal \
  PW_BACKEND_PORT=18765 PW_FRONTEND_PORT=13001 \
  npx playwright test tests/e2e/hermes-workbench.spec.ts -g "F2 subroutes" --project=chromium
```

## Out of scope / still blocked

- No Hermes provider/chat calls
- Fixture mode does not perform real review POST (405 by design)
- Live approve against real FastAPI requires running platform API with `approval_enabled` candidate
