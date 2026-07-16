### Task 5: Today hierarchy and focused artifact renderers

**Files:**

- Create all <code>components/hermes/today/</code> files.
- Create all <code>components/hermes/artifacts/</code> files.
- Modify <code>app/hermes/page.tsx</code>.
- Modify <code>components/hermes/ArtifactShelf.tsx</code> and <code>index.ts</code>.
- Modify <code>lib/hermesArtifactShelf.test.ts</code>.
- Modify <code>tests/e2e/hermes-workbench.spec.ts</code>.

**Interfaces:**

- <code>HermesTodayView</code> consumes only <code>HermesTodayModel</code>, locale, and read-only artifacts.
- <code>ArtifactShelf</code> becomes a compatibility facade over focused renderers until later callers migrate.

- [ ] **Step 1: Add hierarchy RED assertions**

Extend static markup tests:

~~~typescript
expect(html).toContain("自动化 4/4 正常");
expect(html).not.toContain("0 9 * * 0</");
expect(html).toContain("<details");
expect(html).toContain("研究审批项");
expect(html).not.toContain("候选</h");
~~~

Add E2E assertions that the normal combined fixture has one automation summary, the fixture-backed verified research approval item, and zero exceptional job rows; the degraded combined fixture has only its one exceptional job expanded. Both cases use <code>installLoopbackOnlyGuard</code> and assert no external request.

- [ ] **Step 2: Run and confirm RED**

Run: <code>npm --prefix src/frontend test -- lib/hermesArtifactShelf.test.ts lib/hermes/viewModel.test.ts</code>

Expected: old equal-weight shelf fails new hierarchy assertions.

- [ ] **Step 3: Split rendering responsibilities**

Implement:

- <code>ArtifactFeed</code>: feed/source-level status exactly once.
- <code>PortfolioRiskSummary</code>, <code>PredictionSummary</code>, <code>ForesightSummary</code>, <code>WeeklyReviewSummary</code>, <code>OpportunitySummary</code>: one conclusion, key evidence, limitations, collapsed technical detail.
- <code>AutomationSummary</code>: <code>N/4 normal</code> and only exceptions.
- <code>AutomationDetails</code>: cron, freshness, last attempt/success, Run ID, notification status inside <code>&lt;details&gt;</code>.
- <code>AttentionSummary</code>: approval/failure/stale/offline only.
- <code>RecentResults</code>: latest meaningful results, not raw source cards.

Task 4 has already deleted the duplicate inner safety warning. Do not reintroduce any warning <code>Card</code>, <code>ShieldCheck</code>, <code>safetyTitle</code>, or <code>safetyBody</code> while changing the Today hierarchy. Data loading remains:

~~~typescript
const [candidates, artifacts] = await Promise.all([
  getAgentCandidates(),
  getHermesArtifacts(),
]);
const model = buildHermesTodayModel({ candidates, artifacts });
~~~

- [ ] **Step 4: Run unit and deterministic combined-fixture E2E**

Run:

~~~bash
npm --prefix src/frontend test -- lib/hermesArtifactShelf.test.ts \
  lib/hermes/viewModel.test.ts
cd src/frontend
for fixture in normal degraded; do
  env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
  PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
  PW_HERMES_WORKBENCH_FIXTURE="$fixture" \
  npx playwright test tests/e2e/hermes-workbench.spec.ts \
    --config playwright.config.ts --workers=1 || exit 1
done
~~~

Expected: pass against the GET-only server; verified candidate and degraded-exception assertions come from explicit combined fixtures rather than an empty temporary candidate root. Composer is disabled, there is one safety status, and the server log contains no non-GET request.

- [ ] **Step 5: Commit**

~~~bash
git add src/frontend/app/hermes/page.tsx src/frontend/components/hermes \
  src/frontend/lib/hermesArtifactShelf.test.ts src/frontend/tests/e2e/hermes-workbench.spec.ts
git commit -m "feat(frontend): prioritize Hermes action, exceptions, and conclusions"
~~~

---

