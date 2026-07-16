# Frontend Task 5 Report — Today hierarchy and focused artifact renderers

**Status:** DONE  
**Commit (ai-quant-platform):** `611735bac9785a4a33c881d74f6e6a342a298ea9`  
**Message:** `feat(frontend): prioritize Hermes action, exceptions, and conclusions`  
**BASE:** `bf82a76` (Task 4)

## Delivered

- **Today hierarchy** (`components/hermes/today/`):
  - `HermesTodayView` — attention → automation (N/4) → recent conclusions → collapsed technical feed
  - `AttentionSummary` — approval / failure / stale / offline only (localized “研究审批项”)
  - `AutomationSummary` — `自动化 N/4 正常`; only exception job rows
  - `RecentResults` — focused conclusion cards (not raw equal-weight source dumps)
- **Focused artifacts** (`components/hermes/artifacts/`):
  - `ArtifactFeed`, `PortfolioRiskSummary`, `PredictionSummary`, `ForesightSummary`,
    `WeeklyReviewSummary`, `OpportunitySummary`, `AutomationDetails`, `FocusedArtifactCard`
  - Cron / freshness / run ID / notification only inside `<details>` (exception rows `open`)
- **`ArtifactShelf`** is a compatibility facade over focused renderers
- **`app/hermes/page.tsx`**: `buildHermesTodayModel` + `HermesTodayView`; no candidate rail heading; no inner safety Card
- Data loading unchanged: `Promise.all([getAgentCandidates(), getHermesArtifacts()])`

## Verification

- `npm --prefix src/frontend test -- lib/hermesArtifactShelf.test.ts lib/hermes/viewModel.test.ts` — 13 passed  
  (includes hierarchy: `自动化 4/4 正常`, no bare cron, `<details`, `研究审批项`, no `候选</h`)
- `npm --prefix src/frontend run type-check` / `lint` — pass
- Playwright `PW_HERMES_WORKBENCH_FIXTURE=normal` — shell + hierarchy (4/4, research approval, 0 exceptions) pass
- Playwright `PW_HERMES_WORKBENCH_FIXTURE=degraded` — 3/4 + single `weekly` exception expanded pass
- Dirty `earnings_calendar` / `.understand-anything` left uncommitted; not pushed

## Out of scope (later tasks)

- Tasks / Approvals / Results routes (Task 6)
- Visual matrix / real-backend smoke (Task 7)
- Home cutover / rollback (Task 8)
