### Task 7: Four-viewport visual, accessibility, locale, and console gate

**Files:**

- Use, without recreating, Task 3's five combined fixtures and GET-only server.
- Create <code>tests/e2e/hermes-workbench-visual.spec.ts</code>.
- Modify <code>tests/e2e/hermes-workbench.spec.ts</code>: add a data-agnostic real temporary-backend smoke.
- Add approved snapshot files under the generated snapshot directory.

**Interfaces:**

- Fixture selection exists only in the test process and the loopback GET-only fixture server; no production page, component, route, API, localStorage key, or public environment variable knows about it.
- Visual matrix: 1440×900, 1280×800, 768×1024, 390×844; every fixture in Chinese and a separate English normal baseline at every viewport.
- Candidate/approval assertions always use a combined fixture. The real temporary platform backend smoke is intentionally data-agnostic and never substitutes for those assertions.

- [ ] **Step 1: Write visual, accessibility, and real-backend smoke RED tests**

Import all five helpers from <code>hermes-page-gates.ts</code>. Install the loopback-only guard before each navigation, collect console warnings/errors, and run target/focus/reduced-motion/overflow gates against the complete rendered page, not only the Hermes content container. Call <code>assertNoHorizontalOverflow</code> in both locale branches for every fixture and viewport so it checks both <code>documentElement</code> and the named app scroll region.

For the applicable F2 no-scroll-hijack gate, call <code>assertTechnicalDetailDoesNotHijackScroll</code> for Chinese <code>normal</code>/<code>long-content</code> and English <code>normal</code> at every viewport. F2 has no client-side streaming/result-list update path; do not invent a production update hook or test-only selector. The dynamic-stream update gate belongs to the later chat/unified-results slice.

Add one <code>@real-backend-smoke</code> case to <code>hermes-workbench.spec.ts</code>. It may assert only that <code>/zh/hermes</code> renders one safety status, read-only page chrome, and a disabled composer against the isolated real platform FastAPI process. It must not require a candidate, approval item, particular artifact count, database, provider, paper/live path, or external network.

- [ ] **Step 2: Implement visual matrix**

~~~typescript
const viewports = [
  { name: "wide", width: 1440, height: 900 },
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
] as const;

const fixture = process.env.PW_HERMES_WORKBENCH_FIXTURE ?? "normal";

for (const viewport of viewports) {
  test(`@combined-fixture Hermes ${fixture} zh ${viewport.name}`, async ({ page }) => {
    const externalRequests = await installLoopbackOnlyGuard(page);
    await page.setViewportSize(viewport);
    await page.goto("/zh/hermes", { waitUntil: "networkidle" });
    await expect(page.getByTestId("hermes-today-state"))
      .toHaveAttribute("data-state", fixture === "long-content" ? "degraded" : fixture);
    await assertNoHorizontalOverflow(page, viewport.width);
    await assertFullPageTargetsAndFocus(page);
    await assertReducedMotion(page);
    if (fixture === "normal" || fixture === "long-content") {
      await assertTechnicalDetailDoesNotHijackScroll(page);
    }
    expect(externalRequests).toEqual([]);
    await page.evaluate(() => {
      window.scrollTo(0, 0);
      document.querySelectorAll<HTMLElement>("[data-page-scroll-region]")
        .forEach((node) => { node.scrollTop = 0; });
    });
    await expect(page).toHaveScreenshot(
      `hermes-${fixture}-zh-${viewport.name}.png`,
      { animations: "disabled", maxDiffPixelRatio: 0.02 },
    );
  });

  if (fixture === "normal") {
    test(`@combined-fixture Hermes normal en ${viewport.name}`, async ({ page }) => {
      const externalRequests = await installLoopbackOnlyGuard(page);
      await page.setViewportSize(viewport);
      await page.goto("/en/hermes", { waitUntil: "networkidle" });
      await expect(page.getByTestId("hermes-today-state"))
        .toHaveAttribute("data-state", "normal");
      await assertNoHorizontalOverflow(page, viewport.width);
      await assertFullPageTargetsAndFocus(page);
      await assertReducedMotion(page);
      await assertTechnicalDetailDoesNotHijackScroll(page);
      expect(externalRequests).toEqual([]);
      await page.evaluate(() => {
        window.scrollTo(0, 0);
        document.querySelectorAll<HTMLElement>("[data-page-scroll-region]")
          .forEach((node) => { node.scrollTop = 0; });
      });
      await expect(page).toHaveScreenshot(
        `hermes-normal-en-${viewport.name}.png`,
        { animations: "disabled", maxDiffPixelRatio: 0.02 },
      );
    });
  }
}
~~~

Thus the English normal instructions and <code>hermes-normal-en-{viewport}.png</code> baselines live in the formal visual task, not F0. Add console collection to both locale branches:

~~~typescript
const consoleProblems: string[] = [];
page.on("console", (message) => {
  if (message.type() === "error" || message.type() === "warning") {
    consoleProblems.push(message.text());
  }
});
// interactions
expect(consoleProblems).toEqual([]);
~~~

- [ ] **Step 3: Generate snapshots only for review**

Run the exact five-fixture loop from Step 4 once with <code>--update-snapshots</code> added to the Playwright arguments in a clean review branch. The normal invocation generates both zh and en baselines at all four viewports. Inspect every image at original size and obtain frontend reviewer plus user acceptance. This is the only step allowed to use update mode.

- [ ] **Step 4: Run ordinary visual verification without update**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend
env -u PW_HERMES_WORKBENCH_FIXTURE -u PW_HERMES_ROLLBACK_E2E \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
QUANT_API_COMMAND="/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8766" \
npx playwright test tests/e2e/hermes-workbench.spec.ts \
  --config playwright.config.ts --workers=1 --grep @real-backend-smoke

for fixture in normal degraded offline empty long-content; do
  env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
  PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
  PW_HERMES_WORKBENCH_FIXTURE="$fixture" \
  npx playwright test tests/e2e/hermes-workbench-visual.spec.ts \
    --config playwright.config.ts --workers=1 || exit 1
done
~~~

Expected: the isolated real temporary-backend smoke and all five combined-fixture invocations pass with 0 console errors/warnings and no new snapshots. Normal produces both zh/en four-viewport checks. Fixture server logs contain only the three GET endpoint families and no mutation request; candidate visual assertions never depend on the empty temporary backend.

- [ ] **Step 5: Commit reviewed visual specs and baselines**

~~~bash
git add src/frontend/tests/e2e/hermes-workbench.spec.ts \
  src/frontend/tests/e2e/hermes-workbench-visual.spec.ts \
  src/frontend/tests/e2e/hermes-workbench-visual.spec.ts-snapshots
git commit -m "test(frontend): lock Hermes responsive and accessibility baselines"
~~~

---

