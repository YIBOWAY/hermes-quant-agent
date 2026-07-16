# Frontend Task 6 Report — Honest read-only Tasks, Approvals, Results

**Status:** DONE  
**Commit (ai-quant-platform):** `5c21f7ad2cdcb2ad4271b172e55f9c8b876e000e`  
**Message:** `feat(frontend): hermes truthful tasks approvals results routes`  
**BASE:** `fb98f19` (post–Task 5 a11y fix on `611735b`)

## Delivered

- **`app/hermes/tasks/page.tsx`**: read-only automation from `getHermesArtifacts()`; explicit “研究任务账本尚未接入”; layout composer stays disabled.
- **`app/hermes/approvals/page.tsx`**: digest-aware candidate list from `getAgentCandidates()`; StatusPill + binding tone; verified `manifest_digest` in `<code>`; migration evidence / corrupt error code rules; **no** approve/reject controls.
- **`app/hermes/results/page.tsx`**: “只读结果索引”; 9H focused cards; links only to existing platform routes (`/factor-lab`, `/backtest`, `/experiments`, `/agent-studio`, `/paper-trading`); no unified `/hermes/results/*` detail.
- **`lib/hermes/candidatePresentation.ts`**: exhaustive `candidateBindingTone` (`pending→warning`, `approved→success`, `rejected→danger`, `legacy_unbound→danger`, `null→neutral`) + digest presentation helpers.
- **E2E**: `@combined-fixture F2 subroutes are truthful and mutation-free` on normal fixture (verified candidate + digest, zero approve/reject buttons).

## Verification

- `npm --prefix src/frontend test -- lib/hermes/candidatePresentation.test.ts` — 10 passed  
- `npm --prefix src/frontend run type-check` / `lint` — pass  
- Playwright `PW_HERMES_WORKBENCH_FIXTURE=normal` hermes-workbench.spec — 3 passed  
- No `AgentTaskForm` / `useMutation` / `apiPost` / `/api/agent/tasks` under `app/hermes` or `components/hermes`  
- Dirty `earnings_calendar` / `.understand-anything` left uncommitted; not pushed

## Out of scope (later tasks)

- Visual matrix / real-backend smoke (Task 7)
- Home cutover / rollback (Task 8)
- Approve/reject UI (post-F2)
