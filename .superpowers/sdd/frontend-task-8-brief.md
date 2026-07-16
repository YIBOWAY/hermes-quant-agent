### Task 8: Reversible default-home cutover without old-page removal

**Files:**

- Create <code>components/dashboard/LegacyDashboard.tsx</code>.
- Create <code>tests/e2e/hermes-rollback.spec.ts</code>.
- Modify <code>app/layout.tsx</code>.
- Modify <code>app/page.tsx</code>.
- Modify <code>components/Sidebar.tsx</code>, <code>TopBar.tsx</code>, and <code>LocaleToggle.tsx</code>.
- Modify <code>lib/navConfig.ts</code> and <code>navConfig.test.ts</code>.
- Modify <code>playwright.config.ts</code>: optional second rollback frontend process.
- Modify <code>tests/e2e/navigation-layout.spec.ts</code>, <code>locale-toggle.spec.ts</code>, and <code>visual.spec.ts</code>.
- Delete obsolete duplicate root baselines <code>tests/e2e/visual.spec.ts-snapshots/home-desktop-chromium-darwin.png</code> and <code>home-mobile-chromium-darwin.png</code>; Task 7's locale-aware Hermes baselines cover the redirected home.

**Interfaces:**

- Root server redirect preserves locale and the complete repeated query string using <code>getServerLocale()</code> and <code>hermesHomeHref()</code>; the browser-retained hash is covered by E2E.
- <code>buildNavSections({ shellEnabled: true })</code> makes Hermes the single home entry. <code>buildNavSections({ shellEnabled: false })</code> restores Dashboard as the home entry and keeps Hermes as a separate read-only entry.
- <code>QS_HERMES_SHELL_ENABLED=false</code> renders the old Dashboard at locale roots and changes desktop/mobile home navigation back to Dashboard. Direct <code>/hermes</code> and its read-only subroutes remain available.
- Factor Lab, Backtester, Experiments, and Agent Studio remain navigable.
- Rollback acceptance runs a second real Next.js frontend process with the flag false and proves browser back/forward does not enter a redirect loop.

- [ ] **Step 1: Add locale/rollback/nav RED tests**

~~~typescript
it("switches only the home entry while retaining Hermes and legacy research", () => {
  const enabled = buildNavSections({ shellEnabled: true })
    .flatMap((section) => section.items);
  expect(enabled[0]).toMatchObject({ id: "hermes", href: "/hermes" });
  expect(enabled.some((item) => item.id === "dashboard")).toBe(false);

  const rolledBack = buildNavSections({ shellEnabled: false })
    .flatMap((section) => section.items);
  expect(rolledBack[0]).toMatchObject({ id: "dashboard", href: "/" });
  expect(rolledBack).toEqual(expect.arrayContaining([
    expect.objectContaining({ id: "hermes", href: "/hermes" }),
  ]));
  for (const items of [enabled, rolledBack]) {
    expect(items.map((item) => item.id)).toEqual(expect.arrayContaining([
      "factorLab", "backtester", "experiments", "agentStudio",
    ]));
  }
});
~~~

Playwright:

~~~typescript
await page.goto("/zh");
await expect(page).toHaveURL(/\/zh\/hermes$/);
await page.goto("/en?source=bookmark&tag=a&tag=b#root-marker");
await expect(page).toHaveURL(
  /\/en\/hermes\?source=bookmark&tag=a&tag=b#root-marker$/,
);
~~~

Keep this repeated-query-plus-hash locale-root test; the fragment is not sent to the server, so <code>hermesHomeHref</code> must not manufacture or strip it and the real browser redirect must retain it. In <code>locale-toggle.spec.ts</code>, start at <code>/en/hermes?source=bookmark&tag=a&tag=b#approval</code>, switch to Chinese, and assert the resulting URL is <code>/zh/hermes?source=bookmark&tag=a&tag=b#approval</code>. Keep the settings and prediction-market locale cases unchanged.

In <code>hermes-rollback.spec.ts</code>, prefix every test title with <code>@rollback</code>, skip the file explicitly unless <code>PW_HERMES_ROLLBACK_E2E=1</code>, target <code>http://127.0.0.1:${PW_HERMES_ROLLBACK_PORT}</code>, and assert all of the following against the real second process: <code>/zh?source=rollback</code> renders the old “仪表盘” heading without redirect; desktop and mobile home entries are Dashboard/仪表盘; the separate Hermes entry opens <code>/zh/hermes</code>; that page remains read-only with a disabled composer; clicking home returns to Dashboard; then <code>page.goBack()</code> and <code>page.goForward()</code> each settle once on the expected Dashboard/Hermes URL and content. A timeout, repeated redirect, or URL oscillation fails the test.

- [ ] **Step 2: Run and confirm RED**

Run:

~~~bash
npm --prefix src/frontend test -- lib/navConfig.test.ts \
  lib/hermes/featureFlags.test.ts

cd src/frontend
env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
PW_HERMES_WORKBENCH_FIXTURE=normal \
PW_HERMES_ROLLBACK_E2E=1 PW_HERMES_ROLLBACK_PORT=3003 \
npx playwright test tests/e2e/hermes-rollback.spec.ts \
  tests/e2e/navigation-layout.spec.ts tests/e2e/locale-toggle.spec.ts \
  --config playwright.config.ts --workers=1
~~~

Expected: nav modes and root redirect are absent, and Playwright cannot start/reach the rollback frontend yet.

- [ ] **Step 3: Extract legacy dashboard and add server redirect**

Move the current root component without changing its internals to <code>LegacyDashboard.tsx</code>. Root becomes:

~~~tsx
import { redirect } from "next/navigation";
import { LegacyDashboard } from "@/components/dashboard/LegacyDashboard";
import { hermesFeatureFlags } from "@/lib/hermes/featureFlags";
import {
  hermesHomeHref,
  type HermesSearchParams,
} from "@/lib/hermes/routes";
import { getServerLocale } from "@/lib/serverLocale";

type HomePageProps = {
  searchParams: Promise<HermesSearchParams>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  if (!hermesFeatureFlags().shell) {
    return <LegacyDashboard />;
  }
  const resolvedSearchParams = await searchParams;
  const locale = await getServerLocale(resolvedSearchParams);
  redirect(hermesHomeHref(locale, resolvedSearchParams));
}
~~~

Keep both <code>dashboard</code> and <code>hermes</code> in <code>NavItemId</code>. Replace the one static research list with <code>buildNavSections({ shellEnabled })</code>: enabled mode starts with Hermes and omits Dashboard; rollback mode starts with Dashboard and then includes Hermes. Keep every old four-page item and the Sidebar backtest CTA.

In <code>app/layout.tsx</code>, call <code>hermesFeatureFlags()</code> on the server and pass only <code>shellEnabled={flags.shell}</code> to <code>Sidebar</code> and <code>TopBar</code>; both desktop and mobile menus must build the same mode-specific navigation. Do not expose the flag as <code>NEXT_PUBLIC_*</code>.

In <code>LocaleToggle.tsx</code>, build the anchor from <code>usePathname()</code> plus <code>useSearchParams().toString()</code>, and on click append the current <code>window.location.hash</code> before <code>window.location.assign()</code>. Wrap it in a <code>Suspense</code> boundary in <code>TopBar.tsx</code> with a fixed-size, non-interactive locale fallback so production builds do not trigger a missing-Suspense CSR bailout. This preserves query/hash without using either as a feature switch.

Refactor <code>playwright.config.ts</code> so the existing prepared frontend command can be generated for any port. When <code>PW_HERMES_ROLLBACK_E2E=1</code>, start an additional prepared frontend at the validated <code>PW_HERMES_ROLLBACK_PORT</code> with the same loopback backend URL and <code>QS_HERMES_SHELL_ENABLED="false"</code>; pin the primary frontend to <code>QS_HERMES_SHELL_ENABLED="true"</code>. Neither value is public. Keep backend, primary frontend, and rollback frontend as three Playwright <code>webServer</code> entries so the rollback test exercises actual server-side rendering and redirects.

Remove the two root cases from <code>visual.spec.ts</code> and their two old snapshot files rather than blind-updating duplicate baselines; Task 7 already reviews the resulting Hermes page in both locales and all four viewports.

- [ ] **Step 4: Run old-consumer protection and cutover E2E**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend
env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
PW_HERMES_WORKBENCH_FIXTURE=normal \
PW_HERMES_ROLLBACK_E2E=1 PW_HERMES_ROLLBACK_PORT=3003 \
npx playwright test \
  tests/e2e/hermes-workbench.spec.ts \
  tests/e2e/hermes-rollback.spec.ts \
  tests/e2e/navigation-layout.spec.ts \
  tests/e2e/locale-toggle.spec.ts \
  --config playwright.config.ts --workers=1

env -u PW_HERMES_WORKBENCH_FIXTURE -u PW_HERMES_ROLLBACK_E2E \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
QUANT_API_COMMAND="/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8766" \
npx playwright test \
  tests/e2e/run-detail-routes.spec.ts \
  tests/e2e/experiments-workbench.spec.ts \
  tests/e2e/brief-archive.spec.ts \
  --config playwright.config.ts --workers=1
~~~

Expected: enabled roots redirect with repeated query/hash intact; rollback roots and navigation render Dashboard; direct rollback-process Hermes stays read-only; back/forward settles without a loop; old dynamic links and old four pages still work. Candidate assertions run only in the first, combined-fixture invocation.

- [ ] **Step 5: Commit**

~~~bash
git add src/frontend/app/layout.tsx src/frontend/app/page.tsx \
  src/frontend/components/dashboard \
  src/frontend/components/Sidebar.tsx src/frontend/components/TopBar.tsx \
  src/frontend/components/LocaleToggle.tsx \
  src/frontend/lib/navConfig.ts src/frontend/lib/navConfig.test.ts \
  src/frontend/playwright.config.ts \
  src/frontend/tests/e2e/hermes-rollback.spec.ts \
  src/frontend/tests/e2e/navigation-layout.spec.ts \
  src/frontend/tests/e2e/locale-toggle.spec.ts src/frontend/tests/e2e/visual.spec.ts
git add -u src/frontend/tests/e2e/visual.spec.ts-snapshots/home-desktop-chromium-darwin.png \
  src/frontend/tests/e2e/visual.spec.ts-snapshots/home-mobile-chromium-darwin.png
git commit -m "feat(frontend): make Hermes the reversible default research home"
~~~

---

