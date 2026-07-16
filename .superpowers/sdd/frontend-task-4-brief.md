### Task 4: Responsive shell, internal navigation, and single safety message

**Files:**

- Create shell component files and <code>app/hermes/layout.tsx</code>.
- Modify <code>app/hermes/page.tsx</code>: remove the existing duplicate inner safety warning before this milestone is accepted.
- Create <code>tests/e2e/helpers/hermes-page-gates.ts</code> and <code>tests/e2e/hermes-workbench.spec.ts</code>.
- Modify <code>app/globals.css</code>, <code>lib/design-tokens.test.ts</code>.
- Modify <code>components/Sidebar.tsx</code>.
- Modify <code>components/TopBar.tsx</code> and <code>components/LocaleToggle.tsx</code>.
- Modify <code>components/SafetyStrip.tsx</code>.
- Modify <code>components/hermes/ComposerDock.tsx</code>.

**Interfaces:**

- Shell consumes locale, read data, and the static <code>deliveryState="blocked_in_this_slice"</code>; it never performs a mutation or live capability lookup.
- Internal nav has Today, Conversation, Tasks, Approvals, Results. Conversation is visibly unavailable because chat is hard false in this slice.
- Task 3's combined fixtures and GET-only server are the deterministic backend for every Task 4-6 semantic assertion; a separate real temporary-platform-backend smoke remains in Task 7.

- [ ] **Step 1: Add token and shell RED contracts**

In <code>design-tokens.test.ts</code> assert:

~~~typescript
expect(css).toContain("--spacing-hermes-composer-min: 64px");
expect(css).toContain("--spacing-hermes-content-max: 1180px");
expect(css).toContain("--color-hermes-attention:");
expect(css).toContain("--color-hermes-canvas:");
expect(css).toContain(".app-touch-target");
expect(css).toContain(":focus-visible");
expect(css).toContain("@media (prefers-reduced-motion: reduce)");
~~~

Create <code>hermes-page-gates.ts</code> with <code>installLoopbackOnlyGuard(page)</code>, <code>assertFullPageTargetsAndFocus(page)</code>, <code>assertReducedMotion(page)</code>, <code>assertNoHorizontalOverflow(page, viewportWidth)</code>, and <code>assertTechnicalDetailDoesNotHijackScroll(page)</code>. The network guard permits only <code>127.0.0.1</code>/<code>localhost</code> and fails the test with the requested URL for every other browser request. The target/focus gate enumerates every visible <code>a[href]</code>, enabled or disabled <code>button</code>, <code>input</code>, <code>select</code>, <code>textarea</code>, <code>summary</code>, and explicit button/link role across TopBar, LocaleToggle, Sidebar/mobile navigation, Hermes internal navigation, and page content; each bounding box must be at least 44×44 CSS pixels. It then walks enabled focusable elements with the keyboard <code>Tab</code> key in DOM/reading order and requires a non-transparent outline or box-shadow at every stop. At mobile width it opens the mobile navigation, gates its visible controls, closes it, and verifies focus returns to the menu button. The reduced-motion gate emulates <code>reducedMotion: "reduce"</code> and asserts computed animation/transition durations are effectively zero for the complete page. The overflow helper asserts both <code>document.documentElement.scrollWidth &lt;= viewportWidth</code> and every <code>[data-page-scroll-region]</code> has <code>scrollWidth &lt;= clientWidth</code>. The scroll helper opens and closes an already-visible result <code>&lt;details&gt;</code>, checks <code>scrollTop</code> stays within one CSS pixel, and restores the original open/scroll state.

Add Playwright assertions to the new workbench spec, prefix every combined-fixture-dependent test title with <code>@combined-fixture</code>, and install the network guard before navigation:

~~~typescript
const externalRequests = await installLoopbackOnlyGuard(page);
await page.goto("/zh/hermes");
await expect(page.getByTestId("global-safety-strip")).toHaveCount(1);
await expect(page.getByRole("status").filter({ hasText: "仅模拟" })).toHaveCount(1);
await expect(page.locator("main").getByText("仅模拟 · 不存在实盘路径", { exact: true }))
  .toHaveCount(0);
await expect(page.locator("main [data-global-safety-strip]")).toHaveCount(0);
await expect(page.getByRole("navigation", { name: "Hermes 工作台" })).toBeVisible();
await expect(page.getByRole("link", { name: "今日" })).toBeVisible();
await expect(page.getByText("本交付未连接 Hermes 写入能力")).toBeVisible();
await expect(page.getByTestId("hermes-capability-notice"))
  .toHaveAttribute("data-delivery-state", "blocked_in_this_slice");
await expect(page.getByRole("textbox", { name: "和 Hermes 对话" })).toBeDisabled();
await assertFullPageTargetsAndFocus(page);
await assertReducedMotion(page);
await assertNoHorizontalOverflow(page, page.viewportSize()!.width);
expect(externalRequests).toEqual([]);
~~~

- [ ] **Step 2: Run unit and Playwright tests and confirm RED**

Run:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
npm --prefix src/frontend test -- lib/design-tokens.test.ts \
  lib/hermes/featureFlags.test.ts

cd src/frontend
env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
PW_HERMES_WORKBENCH_FIXTURE=normal \
npx playwright test tests/e2e/hermes-workbench.spec.ts \
  --config playwright.config.ts --workers=1
~~~

Expected: production CSS/token assertions fail and the workbench shell/capability/full-page assertions fail. The backend is Task 3's normal GET-only fixture, including its verified pending candidate; it is not an empty temporary platform backend.

- [ ] **Step 3: Implement the approved F1 shell exactly**

Add semantic tokens to <code>@theme</code>. Add these production, not test-only, CSS contracts and apply <code>app-touch-target</code> to every global-shell control plus the Hermes controls selected by the full-page gate:

~~~css
.app-touch-target {
  min-width: 44px;
  min-height: 44px;
}

:where(a[href], button, input, select, textarea, summary, [role="button"]):focus-visible {
  outline: 2px solid var(--color-info);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
~~~

Change the current sub-44px interactive classes in <code>TopBar.tsx</code> to at least 44px, including the menu button, search input, Hermes link, and Settings link. Apply the same minimum to both <code>LocaleToggle.tsx</code> anchors and every Sidebar CTA/navigation/footer link. Do not depend on padding text to accidentally reach the threshold.

Create <code>HermesInternalNav</code> using localized route helpers and <code>aria-current</code>. Create <code>HermesCapabilityNotice</code> with one concise message for the literal <code>blocked_in_this_slice</code> delivery state; do not accept health, probe, gateway, or capability-response props and do not repeat the safety banner.

Mark the one Hermes content scroller with <code>data-page-scroll-region</code>; this is a stable semantic test hook for overflow/scroll behavior, not a fixture selector or update control.

Remove the Sidebar footer whose copy says paper-only. Keep the global <code>SafetyStrip</code> and all existing old-page navigation entries.

Add <code>role="status"</code>, <code>data-global-safety-strip</code>, <code>data-testid="global-safety-strip"</code>, and <code>aria-label={desktopStatus}</code> to the outer <code>SafetyStrip</code> element. In this same Task 4 commit, delete the warning <code>Card</code>, <code>ShieldCheck</code> import, <code>safetyTitle</code>, and <code>safetyBody</code> from <code>app/hermes/page.tsx</code>. Do not add a second live announcement or safety-styled card inside Hermes; the global banner must be visually and structurally unique before Task 4 passes.

Keep <code>ComposerDock</code> submit logic:

~~~typescript
const submitEnabled = !disabled && allowSubmit;
~~~

and render it with <code>disabled={true}</code>, <code>allowSubmit={false}</code> from every F2 route. No <code>fetch</code>, mutation hook, EventSource, WebSocket, or <code>apiPost</code> may appear in the component.

- [ ] **Step 4: Run static and normal-fixture full-page gates**

Run:

~~~bash
npm --prefix src/frontend test -- lib/design-tokens.test.ts \
  lib/safetyStripResponsive.test.ts lib/hermes/featureFlags.test.ts
node --test src/frontend/tests/support/hermes-fixture-api.test.mjs
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
! rg -n "fetch\(|apiPost|WebSocket|EventSource" \
  src/frontend/components/hermes src/frontend/app/hermes
! rg -n "QS_HERMES_(CHAT|EXECUTION|UNIFIED_RESULTS|LEGACY_REDIRECTS)_ENABLED" \
  src/frontend --glob '!**/*.test.*'

cd src/frontend
env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
PW_HERMES_WORKBENCH_FIXTURE=normal \
npx playwright test tests/e2e/hermes-workbench.spec.ts \
  --config playwright.config.ts --workers=1
~~~

Expected: tests/type/lint and the normal combined-fixture E2E pass; both <code>! rg</code> commands succeed only because no production mutation/stream path or non-shell env hook is found; browser requests are loopback-only; the fixture server log contains GET requests only.

- [ ] **Step 5: Commit**

~~~bash
git add src/frontend/app/globals.css src/frontend/app/hermes/layout.tsx \
  src/frontend/app/hermes/page.tsx \
  src/frontend/components/Sidebar.tsx src/frontend/components/TopBar.tsx \
  src/frontend/components/LocaleToggle.tsx \
  src/frontend/components/SafetyStrip.tsx \
  src/frontend/components/hermes/shell \
  src/frontend/components/hermes/ComposerDock.tsx \
  src/frontend/lib/design-tokens.test.ts \
  src/frontend/tests/e2e/helpers/hermes-page-gates.ts \
  src/frontend/tests/e2e/hermes-workbench.spec.ts
git commit -m "feat(frontend): add approved responsive Hermes workbench shell"
~~~

---

