# Frontend Task 3 Report — Pure read-only view model and feature flags

**Date:** 2026-07-13  
**Status:** Complete (committed, not pushed)  
**Repo:** `/Users/sunyibo/programs/ai-quant-platform`  
**BASE:** `c5c614d`  
**Commit:** `2e4704bd1fc4d00573057d4108363e8b1914a005`  
**Message:** `feat(frontend): derive truthful Hermes read-only workbench state`

## Delivered

| Area | Path |
|---|---|
| Types | `src/frontend/lib/hermes/types.ts` |
| View model | `src/frontend/lib/hermes/viewModel.ts` + `viewModel.test.ts` + `viewModelFixtures.ts` |
| Feature flags | `src/frontend/lib/hermes/featureFlags.ts` + `featureFlags.test.ts` |
| Copy | `src/frontend/lib/hermes/copy.ts` |
| Routes | `src/frontend/lib/hermes/routes.ts` + `routes.test.ts` |
| Combined fixtures | `src/frontend/tests/fixtures/hermes-workbench/{normal,degraded,offline,empty,long-content}.json` |
| GET-only fixture API | `src/frontend/tests/support/hermes-fixture-api.mjs` + `.test.mjs` |
| Playwright fixture mode | `src/frontend/playwright.config.ts` |

## Contracts locked

- **Shell flag only:** `QS_HERMES_SHELL_ENABLED !== "false"` (default true). `chat` / `execution` / `unifiedResults` / `legacyRedirects` are hard `false` even when matching env vars are `"true"`.
- **Delivery fact:** always `blocked_in_this_slice` (no probe, no platform capability read).
- **View model:** latest automation by `occurred_at`; only the four known job IDs; exceptions for `failed|stale|never_run` or degraded notification (`fallback_persisted|delivery_unknown`); verified+approval_enabled+pending → approval attention; `migration_required|corrupt|legacy_unbound` → non-actionable degraded; attention sort = approval → failure → stale → offline → degraded → stable id.
- **Routes:** `/hermes`, `/hermes/tasks`, `/hermes/approvals`, `/hermes/results` only — no `/hermes/conversation` href.
- **Fixtures:** root keys exactly `schema_version|health|artifacts|candidates`; every candidate has all eleven required keys (nullable ≠ omitted).
- **Fixture server:** loopback `127.0.0.1`, three GET routes, `Cache-Control: no-store`, 404 other GET, 405 non-GET, validate-before-listen.
- **Playwright:** `PW_HERMES_WORKBENCH_FIXTURE` allowlist; coexistence with `QUANT_API_COMMAND` or `PW_REUSE_SERVER=1` throws `fixture mode cannot reuse or override the backend` before any server; fixture name never injected into frontend/Next env.

## Verification

```text
npm --prefix src/frontend test -- lib/hermes/viewModel.test.ts \
  lib/hermes/featureFlags.test.ts lib/hermes/routes.test.ts
# 13 passed

node --test src/frontend/tests/support/hermes-fixture-api.test.mjs
# 7 passed (includes playwright --list fixture-mode rejection)

npm --prefix src/frontend run type-check
# clean
```

## Preserved (not staged)

- `data/options_universe/earnings_calendar.csv` (dirty)
- `.understand-anything/` (untracked)

## Concerns / follow-ups for Task 4+

1. Frontend `CandidateSummary` in `lib/api.ts` still omits formal `universe`; fixtures use `HermesCandidateReadItem` extension. Optional later OpenAPI/type align.
2. View-model attention titles/summaries are English fact strings; locale chrome lives in `copy.ts` for shell components.
3. No production shell UI in this commit (Task 4+). Existing `/hermes` page unchanged.
4. Not pushed.

## Safety

- Read-only pure derivation + hermetic GET fixtures only.
- No chat/execution/submit paths.
- No paper/live/broker mutation.
- No capability probe.
