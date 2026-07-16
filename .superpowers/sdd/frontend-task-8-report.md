# Frontend Task 8 Report — Reversible default-home cutover

**Status:** DONE  
**Commit (ai-quant-platform):** `9db8e0c60ed9e7b2341255ca39a4535d2bde340a`  
**Message:** `feat(frontend): make Hermes the reversible default research home`  
**BASE:** `cc4659b` (Task 7)

## Delivered

| Area | Path |
|---|---|
| Root cutover | `app/page.tsx` → redirect via `hermesHomeHref` when `QS_HERMES_SHELL_ENABLED≠false`; else `LegacyDashboard` |
| Legacy dashboard | `components/dashboard/LegacyDashboard.tsx` (unchanged UI; Factor Lab etc. untouched) |
| Nav modes | `buildNavSections({ shellEnabled })` — Hermes home (omit Dashboard) / rollback Dashboard+Hermes |
| Shell flag wiring | Server-only `shellEnabled` into `Sidebar`/`TopBar`; never `NEXT_PUBLIC_*` |
| Locale toggle | Query + `window.location.hash` preserved; Suspense fallback in TopBar |
| Rollback E2E | Second process on `PW_HERMES_ROLLBACK_PORT` with `QS_HERMES_SHELL_ENABLED=false` |
| Snapshots | Removed obsolete `home-desktop` / `home-mobile` root baselines |

## Verification

```text
npm --prefix src/frontend test -- lib/navConfig.test.ts lib/hermes/featureFlags.test.ts  # pass
npm --prefix src/frontend run type-check  # clean
# Fixture + rollback (PW_HERMES_ROLLBACK_E2E=1, ports 3002/3003): 14 passed, 1 skipped (@real-backend-smoke)
# Old-consumer real backend: run-detail / experiments / brief-archive — 4 passed
```

## Preserved / not pushed

- Dirty: `data/options_universe/earnings_calendar.csv`, `.understand-anything/`
- Not pushed
