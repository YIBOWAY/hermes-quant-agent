### Task 6: Honest read-only Tasks, Approvals, and Results routes

**Files:**

- Create <code>app/hermes/tasks/page.tsx</code>.
- Create <code>app/hermes/approvals/page.tsx</code>.
- Create <code>app/hermes/results/page.tsx</code>.
- Create <code>lib/hermes/candidatePresentation.ts</code> and <code>candidatePresentation.test.ts</code>.
- Modify <code>tests/e2e/hermes-workbench.spec.ts</code>.

**Interfaces:**

- Tasks reads current automation artifacts and states that the research task ledger is not connected.
- Approvals reads digest-aware candidate summaries after the candidate-integrity plan and provides no approve/reject button in F2.
- Results reads current 9H artifacts and links only to existing canonical old result deep links; unified dynamic routes remain off.

- [ ] **Step 1: Add route RED tests**

~~~typescript
test("F2 subroutes are truthful and mutation-free", async ({ page }) => {
  await page.goto("/zh/hermes/tasks");
  await expect(page.getByRole("heading", { name: "任务" })).toBeVisible();
  await expect(page.getByText("研究任务账本尚未接入")).toBeVisible();

  await page.goto("/zh/hermes/approvals");
  await expect(page.getByRole("heading", { name: "待我确认" })).toBeVisible();
  await expect(page.getByText("研究审批项")).toBeVisible();
  await expect(page.getByRole("button", { name: /批准|拒绝/ })).toHaveCount(0);

  await page.goto("/zh/hermes/results");
  await expect(page.getByRole("heading", { name: "结果" })).toBeVisible();
  await expect(page.getByText("只读结果索引")).toBeVisible();
});
~~~

Add a unit table for <code>candidateBindingTone</code> covering every digest-aware API member exactly: <code>pending → warning</code>, <code>approved → success</code>, <code>rejected → danger</code>, <code>legacy_unbound → danger</code>, and <code>null → neutral</code>. Implement it with an exhaustive <code>switch</code> over <code>AgentCandidatesResponse["candidates"][number]["approval_binding"]</code> and an <code>assertNever</code>; do not use a binary legacy-vs-warning conditional.

- [ ] **Step 2: Run and confirm RED**

Run:

~~~bash
npm --prefix src/frontend test -- \
  lib/hermes/candidatePresentation.test.ts
cd src/frontend
env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
PW_HERMES_WORKBENCH_FIXTURE=normal \
npx playwright test tests/e2e/hermes-workbench.spec.ts \
  --config playwright.config.ts --workers=1
~~~

Expected: the presentation module/routes do not exist. The verified approval item comes from the normal combined fixture, not an empty temporary platform backend.

- [ ] **Step 3: Implement server-only read routes**

Use current server getters only. Every page passes <code>disabled</code> and <code>allowSubmit={false}</code> to the composer or relies on the shared layout composer. Approvals show:

~~~tsx
<StatusPill
  label={text.binding}
  value={candidate.approval_binding}
  tone={candidateBindingTone(candidate.approval_binding)}
/>
<code className="break-all">{candidate.manifest_digest}</code>
~~~

Render the digest code element only for a verified authoritative <code>manifest_digest</code>. For <code>migration_required</code>, show <code>observed_manifest_digest</code> under the label “迁移证据，不能审批”; for <code>corrupt</code>, show the localized stable error code and no preview. F2 has no approval controls in every state.

Do not import <code>AgentTaskForm</code>, <code>apiClient</code>, <code>useMutation</code>, or <code>POST /api/agent/tasks</code>.

- [ ] **Step 4: Run E2E and static mutation search**

Run:

~~~bash
npm --prefix src/frontend test -- \
  lib/hermes/candidatePresentation.test.ts
cd src/frontend
env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
PW_HERMES_WORKBENCH_FIXTURE=normal \
npx playwright test tests/e2e/hermes-workbench.spec.ts \
  --config playwright.config.ts --workers=1
! rg -n "AgentTaskForm|useMutation|apiPost|/api/agent/tasks" app/hermes components/hermes
~~~

Expected: unit and E2E pass; the fixture-backed verified candidate is visible with no approval controls; <code>! rg</code> succeeds because there is no match and the fixture server records no non-GET request.

- [ ] **Step 5: Commit**

~~~bash
git add src/frontend/app/hermes/tasks src/frontend/app/hermes/approvals \
  src/frontend/app/hermes/results \
  src/frontend/lib/hermes/candidatePresentation.ts \
  src/frontend/lib/hermes/candidatePresentation.test.ts \
  src/frontend/tests/e2e/hermes-workbench.spec.ts
git commit -m "feat(frontend): add truthful read-only Hermes task approval result views"
~~~

---

