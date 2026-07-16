# TypeScript Review — Hermes F2 Task 3 (view model + feature flags)

**Date:** 2026-07-13  
**Reviewer:** typescript-reviewer  
**Scope:** `ai-quant-platform` commit `2e4704b` (`c5c614d..HEAD`)  
**Package:** `src/frontend/lib/hermes/*`, fixture API/support, Playwright fixture mode  
**Diff package:** `.superpowers/sdd/frontend-task-3-review.diff`  
**Assessment:** **Approved**

---

## Review setup

| Check | Result |
|---|---|
| Review base | Commit range `c5c614d..2e4704b` (local commit review; not a GitHub PR) |
| Merge readiness (PR CI / conflicts) | **Not verifiable** — no PR metadata (`gh pr view` N/A). Local tree is clean aside from unrelated dirty paths noted in the task report. |
| `npm --prefix src/frontend run type-check` | Pass (`tsc --noEmit`) |
| `npm --prefix src/frontend run lint` | Pass (eslint, max-warnings=0) |
| Vitest hermes suite | 13/13 pass (`viewModel`, `featureFlags`, `routes`) |
| Node fixture suite | 7/7 pass (`hermes-fixture-api.test.mjs`, including Playwright fixture-mode rejection) |

No CRITICAL or HIGH findings. MEDIUM notes only; merge-with-caution is optional, not required.

---

## Contract verification (key brief requirements)

| Contract | Status | Evidence |
|---|---|---|
| Shell env only configurable | Pass | [`featureFlags.ts`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/lib/hermes/featureFlags.ts): `shell: env.QS_HERMES_SHELL_ENABLED !== "false"`; no other env reads |
| `chat` / `execution` / `unifiedResults` / `legacyRedirects` hard `false` | Pass | Literals `false` + env-true negative test |
| `deliveryState: "blocked_in_this_slice"` | Pass | Hardcoded delivery fact; no probe/API/health inference |
| Digest-aware approval attention | Pass | Approval only when `integrity_state === "verified"` **and** `approval_enabled === true` **and** pending **and** truthy `manifest_digest` |
| Non-actionable degraded for migration/corrupt/legacy | Pass | `migration_required` / `corrupt` / `approval_binding === "legacy_unbound"` → `kind: "degraded"`, no approval href |
| Latest automation by `occurred_at`; known four job IDs only | Pass | `pickLatestAutomation` + `KNOWN_JOB_ID_SET` filter |
| Exceptions: `failed\|stale\|never_run` or degraded notification | Pass | `jobIsException` + `fallback_persisted\|delivery_unknown` |
| Attention sort order | Pass | approval → failure → stale → offline → degraded → stable `id` |
| Routes: no `/hermes/conversation` | Pass | Four routes only; tests assert no `conversation` path |
| Fixture root keys + 11 candidate keys | Pass | Validator + five JSON fixtures + omit-key rejection tests |
| GET-only loopback fixture server | Pass | `127.0.0.1`, three routes, `Cache-Control: no-store`, 404/405 |
| Playwright fixture isolation | Pass | Allowlist; throws `fixture mode cannot reuse or override the backend`; fixture name not injected into Next/frontend env |

---

## Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

1. **`CandidateSummary` / `HermesCandidateReadItem` type drift (acknowledged)**  
   - **Where:** [`types.ts`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/lib/hermes/types.ts) `HermesCandidateReadItem`, [`viewModel.ts`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/lib/hermes/viewModel.ts) `raw as HermesCandidateReadItem`  
   - **Issue:** List OpenAPI/`CandidateSummary` still omits formal `universe` and keeps integrity fields optional, while fixtures and the shared builder treat eleven keys as required (nullable ≠ omitted). The `as` cast papers over that gap rather than modeling a validated read DTO.  
   - **Risk:** Future UI may assume `universe` exists on live API payloads; TypeScript will not force OpenAPI alignment.  
   - **Follow-up:** When OpenAPI catches up, drop the intersection cast and type the list item as the locked eleven-key contract.

2. **Double cast for `limitations` extraction**  
   - **Where:** [`viewModel.ts`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/lib/hermes/viewModel.ts) `limitationsFromData(item.data as unknown as Record<string, unknown>)`  
   - **Issue:** Bypasses the artifact discriminated union. Runtime is safe (array + string filter), but the cast hides missing `limitations` on some kinds.  
   - **Follow-up:** Prefer a narrow helper per kind or `'limitations' in item.data` without `unknown` escape.

3. **Duplicated query serialization in routes**  
   - **Where:** [`routes.ts`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/lib/hermes/routes.ts) `hermesHomeHref` / `hermesRouteHref`  
   - **Issue:** Identical sorted-key / multi-value loops. Drift risk if one path gains encoding rules later.  
   - **Follow-up:** Extract `buildQuerySuffix(searchParams)`.

4. **Fixture allowlist duplicated across two modules**  
   - **Where:** [`playwright.config.ts`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/playwright.config.ts) `HERMES_WORKBENCH_FIXTURES` vs [`hermes-fixture-api.mjs`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/tests/support/hermes-fixture-api.mjs) `HERMES_WORKBENCH_FIXTURE_NAMES`  
   - **Issue:** Same five names maintained twice; a sixth fixture could be accepted by one path and rejected by the other.  
   - **Follow-up:** Share one allowlist export (or generate config from the mjs module).

5. **Unit coverage gaps beyond the locked RED cases**  
   - **Where:** [`viewModel.test.ts`](file:///Users/sunyibo/programs/ai-quant-platform/src/frontend/lib/hermes/viewModel.ts)  
   - **Issue:** Covers healthy / stale+approval / empty vs offline / migration. Does not unit-test `corrupt`, `legacy_unbound`, `failed`/`never_run`, or notification-only degradation (`fallback_persisted` / `delivery_unknown`), nor attention sort stability across mixed kinds.  
   - **Risk:** Low today (logic is straightforward and fixtures exercise degraded/migration paths), but regressions could slip before Task 4 UI.  
   - **Follow-up:** Add focused pure cases in Task 4 prep if shell starts rendering those kinds.

6. **Slightly broad `pending` predicate**  
   - **Where:** `candidateAttention` — `status === "pending" \|\| approval_binding === "pending"`  
   - **Issue:** A malformed payload with `status: "pending"` plus non-pending binding still qualifies if verified + enabled + digest. Domain invariants should prevent this; the view model does not re-validate digest width/hex.  
   - **Risk:** Low for this read-only slice (approval UI/CAS still disabled; no write path).  
   - **Follow-up:** Optionally require both `status` and binding pending, and/or `manifest_digest` length 64, when Gate 2 UI lands.

### LOW / notes

- `hermesHomeHref` correctly preserves query strings through `localizePath` (split on `[?#]`).
- Fixture server validates before listen; CLI rejects unknown fixtures with exit 2; no production module imports.
- English attention titles live in the view model; locale chrome is correctly separated in `copy.ts` for later shell work.
- No production shell UI in this commit (explicit Task 4+ boundary) — out of scope, not a defect.
- No `any`, no floating promises, no secrets, no dynamic execution, no path traversal on fixture names (allowlist + basename join).

---

## Security / safety

- Read-only pure derivation only; no chat/execution/submit surfaces.
- Capability flags cannot be env-forced on except shell.
- Fixture HTTP is loopback + GET-only + no-store; non-GET → 405.
- Playwright fixture mode refuses `QUANT_API_COMMAND` / `PW_REUSE_SERVER=1` before starting servers; fixture name stays out of Next public env.
- Approval attention requires authoritative `manifest_digest` (digest-aware); migration/corrupt/legacy never become approval items.

---

## Approval criteria

- **CRITICAL:** 0  
- **HIGH:** 0  
- **MEDIUM:** 6 (type hygiene, DRY, test breadth, defensive pending)  

**Assessment: Approved** — safe to proceed to Task 4 (shell UI). Address MEDIUM items opportunistically when wiring OpenAPI types and approval surfaces; none block this pure view-model/fixture slice.
