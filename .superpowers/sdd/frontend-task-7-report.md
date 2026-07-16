# Frontend Task 7 Report — Four-viewport visual, a11y, locale, console gate

**Status:** DONE  
**Commit (ai-quant-platform):** `cc4659b3d1785a3cc6bd8963762ff823d0a8cc02`  
**Message:** `test(frontend): lock Hermes responsive and accessibility baselines`  
**BASE:** `5c21f7a` (Task 6)

## Delivered

| Area | Path |
|---|---|
| Visual matrix | `src/frontend/tests/e2e/hermes-workbench-visual.spec.ts` |
| Baselines (24 PNGs) | `src/frontend/tests/e2e/hermes-workbench-visual.spec.ts-snapshots/` |
| Real-backend smoke | `@real-backend-smoke` in `tests/e2e/hermes-workbench.spec.ts` |
| Today state contract | `data-testid="hermes-today-state"` + `data-state` on `HermesTodayView` |
| Posture derivation | Approval-only attention keeps `normal` (`viewModel.deriveState`) |
| Scroll gate | Prefer closed `<details>`; `overflow-anchor: none` on shell scroll + technical details |

### Visual matrix

- Viewports: wide 1440×900, desktop 1280×800, tablet 768×1024, mobile 390×844
- Every fixture × zh × 4 viewports
- English normal baseline at every viewport (`hermes-normal-en-{viewport}.png`)
- Gates per case: loopback-only, console error/warning empty, overflow, full-page 44×44 + focus, reduced-motion; scroll-hijack for zh `normal`/`long-content` and en `normal`
- Fixture name stays process-only (`PW_HERMES_WORKBENCH_FIXTURE` + GET-only server)

### Real temporary-backend smoke

- Data-agnostic: one safety status, Hermes chrome, disabled composer
- Skipped when `PW_HERMES_WORKBENCH_FIXTURE` is set
- Never substitutes for candidate/approval combined-fixture assertions

## Snapshot review (Step 3)

`--update-snapshots` used once to mint baselines; ordinary verification re-run without update.

Spot-checked at original size:

- `hermes-normal-zh-wide` — QUANTUM_CORE shell, platform primary CTA blue, 研究态势正常, 4/4 automation, approval attention, disabled composer
- `hermes-normal-en-mobile` — English locale, mobile chrome, healthy posture, disabled composer
- `hermes-degraded-zh-desktop` — 研究态势已降级, 3/4 automation, expanded weekly exception

Human/frontend-reviewer formal acceptance of all 24 PNGs remains the residual gate if required beyond implementer review.

## Verification

```text
# Unit
npm --prefix src/frontend test -- lib/hermes/viewModel.test.ts
# 5 passed

npm --prefix src/frontend run type-check
# clean

# Step 4 ordinary verification (no --update-snapshots)
@real-backend-smoke hermes-workbench.spec.ts — 1 passed
PW_HERMES_WORKBENCH_FIXTURE=normal   visual — 8 passed (zh+en × 4)
PW_HERMES_WORKBENCH_FIXTURE=degraded visual — 4 passed
PW_HERMES_WORKBENCH_FIXTURE=offline  visual — 4 passed
PW_HERMES_WORKBENCH_FIXTURE=empty    visual — 4 passed
PW_HERMES_WORKBENCH_FIXTURE=long-content visual — 4 passed
# Total visual cases: 24; 0 console errors/warnings; no new snapshots on re-run

# Combined-fixture shell/hierarchy still green under normal fixture
hermes-workbench.spec @combined-fixture — 3 passed (real-backend smoke skipped in fixture mode)
```

## Preserved (not staged)

- `data/options_universe/earnings_calendar.csv` (dirty)
- `.understand-anything/` (untracked)
- Not pushed

## Out of scope (later)

- Task 8 home cutover / rollback / delete obsolete root home snapshots
- Chat / unified dynamic results / approve-reject UI
