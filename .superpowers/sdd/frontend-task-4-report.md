# Frontend Task 4 Report — Responsive shell, single safety strip

**Status:** DONE  
**Commit (ai-quant-platform):** `feat(frontend): hermes workbench shell with single safety strip`

## Delivered

- Additive QUANTUM_CORE tokens: `--spacing-hermes-composer-min`, `--spacing-hermes-content-max`, `--color-hermes-attention`, `--color-hermes-canvas`, plus production `.app-touch-target`, `:focus-visible`, and reduced-motion contracts in `globals.css`.
- Hermes shell: `HermesWorkbenchShell`, `HermesInternalNav` (Today/Tasks/Approvals/Results + unavailable Conversation), `HermesCapabilityNotice` (`blocked_in_this_slice` only), `app/hermes/layout.tsx`.
- Removed duplicate inner safety `Card` / `ShieldCheck` / safety copy from `app/hermes/page.tsx`. Global `SafetyStrip` is the sole paper/live/kill status (`role="status"`, `data-global-safety-strip`, `data-testid="global-safety-strip"`).
- Removed Sidebar paper-only footer. TopBar / LocaleToggle / Sidebar / Hermes controls use `app-touch-target` (≥44×44). Composer stays `disabled` + `allowSubmit={false}` with no fetch/mutation.
- E2E: `tests/e2e/helpers/hermes-page-gates.ts` + `@combined-fixture` `hermes-workbench.spec.ts` (loopback-only, single safety strip, capability notice, disabled composer, target/focus/reduced-motion/overflow).

## Verification

- `npm --prefix src/frontend test -- lib/design-tokens.test.ts lib/safetyStripResponsive.test.ts lib/hermes/featureFlags.test.ts` — pass
- `node --test src/frontend/tests/support/hermes-fixture-api.test.mjs` — pass
- `npm --prefix src/frontend run type-check` / `lint` — pass
- Playwright `PW_HERMES_WORKBENCH_FIXTURE=normal` workbench spec — pass
- No production `fetch`/`apiPost`/`WebSocket`/`EventSource` under hermes components/routes; no non-shell capability env hooks in non-test frontend code
- Dirty `earnings_calendar` / `.understand-anything` left uncommitted

## Out of scope (later tasks)

- Today hierarchy / artifact split (Task 5)
- Tasks/Approvals/Results pages (Task 6)
- Visual matrix / real-backend smoke (Task 7)
- Home cutover / rollback (Task 8)

## Follow-up: Task 4 React review fixes (heading order + a11y)

**Commit (ai-quant-platform):** `fb98f19` — `fix(frontend): correct Hermes shell heading order and a11y nits`  
**Review:** `.superpowers/sdd/frontend-task-4-review.md`

| Finding | Fix |
|---|---|
| HIGH: capability notice `h2` before page `h1` | `HermesCapabilityNotice` title demoted to styled `<p>` (non-heading chrome) |
| MEDIUM: Conversation reason only via `title` | `HermesInternalNav` unavailable control uses `aria-label={`${label}. ${unavailableLabel}`}`; dropped redundant `aria-disabled` |
| MEDIUM: second `role="status"` in ComposerDock | unavailable hint is static `<p>` (global `SafetyStrip` remains sole live region) |
| MEDIUM: dead draft `useState` while shell locks submit | removed draft state/`onChange`; controlled `value=""` while disabled |

**Verification:** `npm --prefix src/frontend run type-check` — pass  
Dirty `earnings_calendar` / `.understand-anything` left uncommitted; no push.
