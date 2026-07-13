# Hermes Professional Frontend and Read-Only Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a professionally reviewed, responsive Hermes visual system and ship a truthful read-only default workbench that makes action, exceptions, current work, recent results, and the disabled/offline conversation boundary understandable within five seconds.

**Architecture:** F0/F1 live as versioned design artifacts outside the Next.js bundle and require written user approval before any production component is created. After approval, the platform derives a pure view model from the existing 9H feed and candidate read API, renders a responsive Hermes shell with one global safety strip, and exposes honest read-only Today/Tasks/Approvals/Results views. Root redirect is the final task and remains reversible through one server-side shell flag; the other four capabilities are code-level delivery facts fixed off, because this wave has no platform getter or route that can carry the separate HQA capability contract into F2.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript 5.9, Tailwind CSS 4 semantic tokens, lucide-react, Vitest node tests for pure view models, Playwright Chromium for interaction/accessibility/visual coverage, static HTML/CSS/JavaScript for F0/F1.

## Global Constraints

- A professional frontend agent must own F0/F1 and production visual implementation; an independent frontend/UX reviewer reviews F1 and F2.
- The existing brainstorming preview validates information architecture only and must not be translated directly into production code.
- F0 must show 2-3 genuinely different high-fidelity directions at 1440, 1280, 768, and 390 widths; never use scaled-down screenshots that hide content.
- Written user approval is required after F0 and again after the clickable F1 state prototype. Stop at either gate until approval is present in the design README.
- Only the global <code>SafetyStrip</code> may display the paper/live/kill/API banner. Remove the Hermes duplicate card and the Sidebar's duplicate paper-only footer.
- Normal automation compresses to one line; only failure, staleness, degradation, quota/fallback, or required human action expands.
- Source status appears once. cron, run IDs, freshness timestamps, paths, and raw errors live in collapsed technical detail.
- The platform candidate is labeled “研究审批项 / Research approval item”; market-foresight candidates are “市场预测提案 / Market prediction proposals”.
- The production composer remains non-submitting. No call to Hermes, <code>/api/agent/tasks</code>, provider, research engine, paper account, broker, or live route is introduced.
- <code>QS_HERMES_SHELL_ENABLED</code> is the only configurable capability in this slice. <code>chat</code>, <code>execution</code>, <code>unifiedResults</code>, and <code>legacyRedirects</code> are literal <code>false</code> even if similarly named environment variables are <code>true</code>.
- F2 capability copy consumes the static delivery fact <code>blocked_in_this_slice</code>. It must not claim or imply a live Hermes capability probe, gateway status, or platform capability read; no such platform adapter exists in this wave.
- Root becomes <code>/hermes</code> only after F2 passes user/reviewer, four-viewport, locale, keyboard, console, and visual gates.
- Preserve locale prefix, query string, browser history, existing deep links, and old four page entries until later parity slices.
- Tests are hermetic: database and AI-HOT off, isolated temp data, fixed 9H feed/candidate fixtures, no external network.
- The production shell, including TopBar, locale controls, Sidebar, and page content, must provide 44px targets, visible keyboard focus, and reduced-motion behavior; these are production CSS rules plus full-page E2E gates, not prototype-only checks.
- Do not run <code>--update-snapshots</code> as part of ordinary verification. Snapshot updates are a separate human-reviewed action.
- Preserve existing platform dirty files and HQA <code>.superpowers/</code>.
- F0/F1 may run in parallel with the safety plans, but Task 3 production work waits until candidate-integrity Task 5 has shipped its digest-aware API types; never invent a temporary candidate contract.
- Tasks 1-8 execute from <code>/Users/sunyibo/programs/ai-quant-platform</code> unless a command explicitly changes directory. Task 9 names each repository before staging or verification.

---

## Execution order

1. Task 1 stops at the F0 written user gate; only an approved direction enters Task 2.
2. Task 2 stops at the F1 written user gate. In parallel, the separate candidate-integrity plan may advance, but this plan cannot enter Task 3 until that plan's Task 5 digest-aware API/frontend types are committed and verified.
3. Task 3 freezes types, hard-off capability facts, combined fixtures, GET-only server, and Playwright selection. Tasks 4, 5, and 6 consume those exact contracts in order.
4. Task 7 locks production visual/accessibility evidence. Only after its reviewer/user gate passes may Task 8 cut over the default home and prove rollback with the second frontend.
5. Task 9 Steps 1-4 may run after Task 8, but Task 9 Step 5 is the single serialized shared-docs owner and must wait until the gateway capability plan's Task 4 and the candidate-integrity plan's Task 8 have completed their code, independent review, verification, and repository-local docs commits. Only then re-read both repositories' HEAD/status and live evidence, reconcile all three plans' final truth, and make this plan's two separate repository-local docs commits.

---

## File map

### F0/F1 design artifacts in the platform repository

- Create <code>docs/design/hermes-workbench/README.md</code>: design status, directions, review evidence, selected direction, written gates.
- Create <code>docs/design/hermes-workbench/f0/shared.css</code>.
- Create <code>docs/design/hermes-workbench/f0/direction-a.html</code>: “COO desk”, action/status-first.
- Create <code>docs/design/hermes-workbench/f0/direction-b.html</code>: “research timeline”, change/progress-first.
- Create <code>docs/design/hermes-workbench/f0/direction-c.html</code>: “quiet split canvas”, conversation/result-first while preserving idle overview.
- Create <code>docs/design/hermes-workbench/f1/prototype.html</code> and <code>prototype.css</code>.
- Create five strict state catalogs under <code>docs/design/hermes-workbench/f1/states/</code>: <code>home.json</code>, <code>conversation.json</code>, <code>tasks.json</code>, <code>approvals.json</code>, <code>results.json</code>.

These files are never imported from <code>app/</code>, <code>components/</code>, <code>lib/</code>, or <code>public/</code>.

### Production state and copy

- Create <code>src/frontend/lib/hermes/types.ts</code>: read-only view-model types.
- Create <code>src/frontend/lib/hermes/viewModel.ts</code> and <code>viewModel.test.ts</code>: pure derivation from 9H feed/candidates.
- Create <code>src/frontend/lib/hermes/viewModelFixtures.ts</code>: typed deterministic fixtures shared by the pure view-model tests.
- Create <code>src/frontend/lib/hermes/copy.ts</code>: all new en/zh workbench copy.
- Create <code>src/frontend/lib/hermes/routes.ts</code> and <code>routes.test.ts</code>: internal routes and legacy intent helpers.
- Create <code>src/frontend/lib/hermes/featureFlags.ts</code> and <code>featureFlags.test.ts</code>: shell on/rollback, four non-shell capabilities hard off, and static <code>blocked_in_this_slice</code> delivery state.
- Create <code>src/frontend/lib/hermes/candidatePresentation.ts</code> and <code>candidatePresentation.test.ts</code>: exhaustive digest-aware binding presentation.

### Production shell

- Create <code>src/frontend/app/hermes/layout.tsx</code>.
- Modify <code>src/frontend/app/hermes/page.tsx</code>.
- Create <code>src/frontend/app/hermes/tasks/page.tsx</code>.
- Create <code>src/frontend/app/hermes/approvals/page.tsx</code>.
- Create <code>src/frontend/app/hermes/results/page.tsx</code>.
- Create <code>src/frontend/components/hermes/shell/HermesWorkbenchShell.tsx</code>, <code>HermesInternalNav.tsx</code>, and <code>HermesCapabilityNotice.tsx</code>.
- Create <code>src/frontend/components/hermes/today/HermesTodayView.tsx</code>, <code>AttentionSummary.tsx</code>, <code>RecentResults.tsx</code>, and <code>AutomationSummary.tsx</code>.
- Split <code>ArtifactShelf.tsx</code> into <code>components/hermes/artifacts/</code> focused renderers while preserving existing feed contracts.
- Modify <code>ComposerDock.tsx</code>: professional responsive visuals and truthful capability copy; still no network submit.
- Modify <code>components/hermes/index.ts</code>.

### App shell and rollback

- Modify <code>app/layout.tsx</code>: resolve the server-only shell flag and pass the selected home mode to desktop/mobile navigation.
- Modify <code>components/Sidebar.tsx</code>: remove duplicate paper footer; keep old research links through later parity slices.
- Modify <code>components/TopBar.tsx</code>: receive the home mode and make every visible top/mobile navigation control at least 44px.
- Modify <code>components/LocaleToggle.tsx</code>: preserve query/hash during locale changes and make each locale target at least 44px.
- Modify <code>components/SafetyStrip.tsx</code>: make the one global safety banner the explicit status landmark.
- Modify <code>app/globals.css</code> and <code>lib/design-tokens.test.ts</code>: additive Hermes semantic tokens plus production focus, 44px-target, and reduced-motion contracts.
- Create <code>components/dashboard/LegacyDashboard.tsx</code> from current root implementation.
- Modify <code>app/page.tsx</code>: locale-preserving server redirect when shell flag is on; legacy dashboard when explicitly rolled back.
- Modify <code>lib/navConfig.ts</code> and <code>navConfig.test.ts</code>: Hermes is the single home entry when enabled; rollback restores Dashboard as home while retaining independently reachable Hermes and the old four pages.

### Hermetic tests

- Keep <code>tests/fixtures/hermes-artifacts.v1.json</code>.
- Create <code>tests/fixtures/hermes-workbench/normal.json</code>, <code>degraded.json</code>, <code>offline.json</code>, <code>empty.json</code>, and <code>long-content.json</code>.
- Create <code>tests/support/hermes-fixture-api.mjs</code>: loopback GET-only fixture API for production-shell visual tests; no platform/database/provider process.
- Create <code>tests/support/hermes-fixture-api.test.mjs</code>: exact endpoint, method, fixture-name, and no-side-effect contracts.
- Create <code>tests/e2e/helpers/hermes-page-gates.ts</code>: reusable loopback-only, focus, target-size, reduced-motion, overflow, and console gates for the complete rendered page.
- Create <code>tests/e2e/hermes-workbench.spec.ts</code>.
- Create <code>tests/e2e/hermes-workbench-visual.spec.ts</code> and four reviewed snapshots per locale/state set selected below.
- Create <code>tests/e2e/hermes-rollback.spec.ts</code>: a real second-frontend-process rollback and browser-history test.
- Modify <code>tests/e2e/navigation-layout.spec.ts</code>, <code>locale-toggle.spec.ts</code>, <code>visual.spec.ts</code>, and <code>playwright.config.ts</code>.

## Production interfaces

~~~typescript
import type {
  AgentCandidatesResponse,
  HermesArtifactShelfEnvelope,
} from "@/lib/api";

export type HermesAttentionItem = {
  id: string;
  kind: "approval" | "failure" | "stale" | "offline" | "degraded";
  title: string;
  summary: string;
  href?: string;
};

export type HermesResultSummary = {
  id: string;
  kind: string;
  title: string;
  summary: string;
  status: string;
  occurredAt: string;
  href?: string;
  limitations: string[];
};

export type HermesTechnicalSource = {
  id: string;
  label: string;
  status: "available" | "degraded" | "unavailable";
  lastSyncedAt?: string;
  details: Array<{ label: string; value: string }>;
};

export type HermesAutomationSummary = {
  healthy: number;
  total: number;
  status: "healthy" | "attention" | "unavailable";
  exceptions: Array<{
    jobId: string;
    status: string;
    reason: string;
  }>;
};

export type HermesTodayModel = {
  state: "empty" | "normal" | "degraded" | "offline";
  attention: HermesAttentionItem[];
  automation: HermesAutomationSummary;
  recentResults: HermesResultSummary[];
  technical: HermesTechnicalSource[];
};

export function buildHermesTodayModel(input: {
  artifacts: HermesArtifactShelfEnvelope;
  candidates: AgentCandidatesResponse;
}): HermesTodayModel;

export type HermesDeliveryState = "blocked_in_this_slice";

export type HermesFeatureFlags = {
  shell: boolean;
  chat: false;
  execution: false;
  unifiedResults: false;
  legacyRedirects: false;
  deliveryState: HermesDeliveryState;
};
~~~

---

### Task 1: F0 professional visual directions

**Files:**

- Create all <code>docs/design/hermes-workbench/f0/</code> files.
- Create <code>docs/design/hermes-workbench/README.md</code>.

**Interfaces:**

- Consumes the approved D-31 information architecture and real 9H field lengths.
- Produces three directly browsable, full-size directions with identical content/state coverage.

- [ ] **Step 1: Dispatch the professional design agent with a fixed brief**

The executing agent must use the <code>web-design-engineer</code> skill and receive this exact brief:

~~~text
Design three high-fidelity directions for the approved Hermes unified research
workbench. Do not reuse or trace the .superpowers brainstorming preview. Use the
platform's real dark theme/token/font/icon vocabulary, real Chinese and English
copy, long run IDs, one failed automation, one pending approval, one recent
factor result, and an honest disabled conversation boundary.

Every direction must show:
1. idle Today view,
2. active conversation/execution composition,
3. approval state,
4. factor/backtest/experiment result composition,
5. 1440, 1280, 768 and 390 responsive behavior without scaling the whole UI.

Direction A: COO desk — action and status first.
Direction B: research timeline — change and progress first.
Direction C: quiet split canvas — conversation and result first, but idle mode
still answers safety/action/current-work/recent-result in five seconds.

Only the global top SafetyStrip may show paper/live/kill/API. Normal automation
compresses to one row. Technical cron/run/path details are collapsed.
~~~

- [ ] **Step 2: Implement a shared full-size frame**

Create <code>shared.css</code> with real responsive breakpoints, not transform scaling:

~~~css
:root {
  color-scheme: dark;
  --bg: #0c0d10;
  --surface: #13151a;
  --surface-2: #181b21;
  --line: #2a2e37;
  --text: #f1f3f6;
  --muted: #9ca3af;
  --hermes: #8b7cf6;
  --warning: #f5b942;
  --danger: #f06a6a;
  --success: #55c98f;
  font-family: Inter, "PingFang SC", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; background: var(--bg); color: var(--text); }
.safety { height: 36px; display: grid; place-items: center; border-bottom: 1px solid #5c451c; }
.prototype { min-height: calc(100vh - 36px); display: grid; }
button, a, input, textarea { min-height: 44px; }
:focus-visible { outline: 2px solid var(--hermes); outline-offset: 3px; }
@media (max-width: 1279px) { .secondary-panel { display: none; } }
@media (max-width: 767px) {
  .desktop-only { display: none !important; }
  .prototype { display: block; }
  .content { padding: 16px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
~~~

Each direction imports only this local stylesheet plus its additive direction rules.

- [ ] **Step 3: Build each direction with the same realistic content**

Each HTML file must include these exact visible facts so comparison is about hierarchy, not content:

~~~html
<div class="safety" role="status">
  仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK
</div>
<main class="prototype">
  <section aria-labelledby="today-title">
    <p>7 月 13 日 · 今日</p>
    <h1 id="today-title">1 项需要你确认，其余研究运行正常</h1>
    <article>
      <h2>研究审批项</h2>
      <p>factor-momentum_20d_reversal-323b045e4b</p>
      <button type="button">查看准确摘要</button>
    </article>
    <article>
      <h2>自动化 3/4 正常</h2>
      <p>weekly_review 已过期；最近成功 2026-07-05T01:00:11Z</p>
      <details><summary>技术详情</summary><code>0 9 * * 0 · run weekly-review-2026-07-13-01</code></details>
    </article>
    <article>
      <h2>最近结果</h2>
      <p>AAPL 风险与新因子计划 · completed_degraded</p>
    </article>
  </section>
  <section aria-label="Hermes conversation">
    <textarea aria-label="和 Hermes 对话" disabled>真实 Hermes 写入能力尚未通过</textarea>
    <button type="button" disabled>发送</button>
  </section>
</main>
~~~

Add active/approval/result toggles inside each file using local JavaScript and semantic buttons. Do not load any CDN or remote asset.

- [ ] **Step 4: Verify four real viewports**

Serve the platform repository read-only:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
~~~

Inspect every direction at 1440×900, 1280×800, 768×1024, and 390×844. At each width verify:

~~~text
document.documentElement.scrollWidth <= window.innerWidth
all interactive targets >= 44 CSS pixels
focus order follows visible reading order
no safety message is duplicated inside the content
normal automation never expands into four equal cards
~~~

- [ ] **Step 5: Independent review, user gate, and commit**

Have a separate frontend/UX reviewer record pass/fail for hierarchy, long Chinese text, long IDs, reduced motion, contrast, and viewport behavior in <code>docs/design/hermes-workbench/README.md</code>.

Then stop and obtain written user selection. After approval, add an <code>F0 decision</code> section containing: status <code>approved</code>; the exact selected filename stem that exists under <code>f0/</code>; approver <code>user</code>; the verbatim output of <code>date +%F</code>; and only the adjustments explicitly requested by the user. Never pre-fill a direction or invent adjustments.

Do not write “approved” before the user says so. After approval:

~~~bash
git add docs/design/hermes-workbench
git commit -m "docs(frontend): approve Hermes high-fidelity visual direction"
~~~

---

### Task 2: F1 clickable full-state prototype

**Files:**

- Create <code>docs/design/hermes-workbench/f1/prototype.html</code>.
- Create <code>docs/design/hermes-workbench/f1/prototype.css</code>.
- Create five JSON state catalogs.
- Modify <code>docs/design/hermes-workbench/README.md</code>.

**Interfaces:**

- Consumes the exact selected F0 direction and user adjustments.
- Produces a keyboard-operable local prototype covering the complete state matrix; no production import or network.

- [ ] **Step 1: Define complete strict state catalogs**

Each JSON file has this root shape:

~~~json
{
  "schema_version": "1.0",
  "surface": "home",
  "default_state": "normal",
  "states": [
    {
      "id": "normal",
      "title": "1 项需要你确认，其余研究运行正常",
      "status": "available",
      "announcements": [],
      "actions": [{"id": "approval-1", "label": "查看准确摘要"}],
      "technical": [{"label": "source", "value": "automation_status"}]
    }
  ]
}
~~~

Use these exact state IDs:

- home: <code>empty/loading/normal/degraded/hermes_offline</code>
- conversation: <code>sending/queued/streaming/reconnecting/stopping/reconciling/failed/quota/fallback</code>
- tasks: <code>queued/running/waiting_gate/stop_requested/reconciling/completed/partial/failed/stopped</code>
- approvals: <code>available/approved/rejected/expired/stale/digest_mismatch</code>
- results: <code>loading/partial/no_data/audit_warning/source_missing</code>

Each state must include Chinese/English copy, one long error, and non-color status text.

- [ ] **Step 2: Implement state navigation and the full research walkthrough**

Prototype navigation must traverse:

~~~text
提出目标
→ Hermes 结构化计划
→ Gate 1 formula/plan confirmation
→ streaming execution with real event labels
→ completed_degraded result
→ Gate 2 exact manifest summary
→ Gate 3 scoped diff summary
~~~

The prototype uses only the exact local catalogs <code>fetch("./states/home.json")</code>, <code>conversation.json</code>, <code>tasks.json</code>, <code>approvals.json</code>, and <code>results.json</code>, plus DOM APIs. It must not submit a form or contact localhost services. Include a visible “prototype data” label outside the simulated product chrome so it cannot be mistaken for a live session.

- [ ] **Step 3: Add keyboard and responsive acceptance script**

In prototype JavaScript, provide state buttons with <code>aria-pressed</code>, restore focus after modal-like approval detail closes, and announce state transitions through one <code>aria-live="polite"</code> region. On mobile, order content as status → conversation → plan/execution → result → composer.

- [ ] **Step 4: Independent review and written user gate**

The independent reviewer clicks the complete walkthrough at all four viewports and records:

~~~markdown
## F1 review

- Full lifecycle: pass
- State catalog: pass
- 1440/1280/768/390: pass
- Keyboard-only: pass
- Reduced motion: pass
- Horizontal overflow: none
- Console errors/warnings: 0/0
~~~

Then stop for written user approval. Record the actual approval in the README; do not create anything under <code>src/frontend/app</code>, <code>components</code>, or <code>lib</code> before it.

- [ ] **Step 5: Commit approved prototype**

~~~bash
git add docs/design/hermes-workbench/f1 docs/design/hermes-workbench/README.md
git commit -m "docs(frontend): approve Hermes full-state interaction prototype"
~~~

---

### Task 3: Pure read-only view model and feature flags

**Files:**

- Create <code>src/frontend/lib/hermes/types.ts</code>.
- Create <code>src/frontend/lib/hermes/viewModel.ts</code>.
- Create <code>src/frontend/lib/hermes/viewModel.test.ts</code>.
- Create <code>src/frontend/lib/hermes/viewModelFixtures.ts</code>.
- Create <code>src/frontend/lib/hermes/featureFlags.ts</code>.
- Create <code>src/frontend/lib/hermes/featureFlags.test.ts</code>.
- Create <code>src/frontend/lib/hermes/copy.ts</code>.
- Create <code>src/frontend/lib/hermes/routes.ts</code> and <code>routes.test.ts</code>.
- Create the five combined JSON fixtures under <code>src/frontend/tests/fixtures/hermes-workbench/</code>.
- Create <code>src/frontend/tests/support/hermes-fixture-api.mjs</code> and <code>hermes-fixture-api.test.mjs</code>.
- Modify <code>src/frontend/playwright.config.ts</code>: validated test-process-only fixture selection and GET-only backend command.

**Interfaces:**

- Produces the locked types and <code>buildHermesTodayModel</code>.
- Produces combined API fixtures and a loopback GET-only server before any production-shell E2E depends on candidates or artifacts.
- <code>shell=true</code> by default and is the only environment-configurable flag. The four non-shell capabilities are hard <code>false</code>; delivery state is always <code>blocked_in_this_slice</code>.

- [ ] **Step 1: Write view-model RED tests**

~~~typescript
import { describe, expect, it } from "vitest";
import type { AgentCandidatesResponse } from "@/lib/api";
import { buildHermesTodayModel } from "./viewModel";
import {
  candidateFixture,
  degradedArtifacts,
  healthyArtifacts,
  noArtifacts,
} from "./viewModelFixtures";

describe("buildHermesTodayModel", () => {
  it("compresses healthy automation to one summary and emits no normal job cards", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: { candidates: [] },
    });
    expect(model.automation).toMatchObject({
      healthy: 4,
      total: 4,
      status: "healthy",
      exceptions: [],
    });
    expect(model.attention).toEqual([]);
  });

  it("promotes only failed/stale jobs and research approvals to attention", () => {
    const model = buildHermesTodayModel({
      artifacts: degradedArtifacts,
      candidates: {
        candidates: [candidateFixture({
          candidate_id: "factor-long-approval-id",
          artifact_type: "factor",
          goal: "Evaluate a deterministic reversal factor",
          universe: ["AAPL"],
          status: "pending",
          manifest_digest: "a".repeat(64),
          observed_manifest_digest: null,
          approval_binding: "pending",
          integrity_state: "verified",
          approval_enabled: true,
          integrity_error_code: null,
        })],
      } satisfies AgentCandidatesResponse,
    });
    expect(model.state).toBe("degraded");
    expect(model.attention.map((item) => item.kind)).toEqual(["approval", "stale"]);
    expect(model.automation.exceptions).toHaveLength(1);
  });

  it("distinguishes empty feed from unavailable Hermes sources", () => {
    expect(buildHermesTodayModel({
      artifacts: noArtifacts("empty"),
      candidates: { candidates: [] },
    }).state).toBe("empty");
    expect(buildHermesTodayModel({
      artifacts: noArtifacts("unavailable"),
      candidates: { candidates: [] },
    }).state).toBe("offline");
  });

  it("shows unversioned candidates as migration attention, never approval", () => {
    const model = buildHermesTodayModel({
      artifacts: healthyArtifacts,
      candidates: {
        candidates: [candidateFixture({
          candidate_id: "legacy-pending",
          artifact_type: "factor",
          goal: "Migrate an unversioned factor candidate",
          universe: ["AAPL"],
          status: "pending",
          manifest_digest: null,
          observed_manifest_digest: "b".repeat(64),
          approval_binding: "pending",
          integrity_state: "migration_required",
          approval_enabled: false,
          integrity_error_code: null,
        })],
      } satisfies AgentCandidatesResponse,
    });
    expect(model.attention).toEqual([
      expect.objectContaining({ kind: "degraded", id: "legacy-pending" }),
    ]);
  });
});
~~~

Put fixture builders in <code>viewModelFixtures.ts</code>; keep them under <code>lib/hermes</code> so Vitest's current <code>lib/**/*.test.ts</code> include pattern executes the tests. The shared builder must enumerate every required field from candidate-integrity Task 5, including required nullable fields:

~~~typescript
import type { AgentCandidatesResponse } from "@/lib/api";

type CandidateReadItem = AgentCandidatesResponse["candidates"][number];

export function candidateFixture(
  overrides: Partial<CandidateReadItem> = {},
): CandidateReadItem {
  return {
    candidate_id: "factor-complete-fixture",
    artifact_type: "factor",
    goal: "Evaluate a deterministic factor",
    universe: ["AAPL"],
    status: "pending",
    integrity_state: "verified",
    manifest_digest: "a".repeat(64),
    observed_manifest_digest: null,
    approval_binding: "pending",
    approval_enabled: true,
    integrity_error_code: null,
    ...overrides,
  } satisfies CandidateReadItem;
}
~~~

Do not hand-write partial candidate literals elsewhere. A corrupt candidate still supplies every required key with <code>artifact_type</code>, <code>goal</code>, <code>universe</code>, <code>status</code>, <code>manifest_digest</code>, <code>observed_manifest_digest</code>, and <code>approval_binding</code> explicitly <code>null</code> as required by the locked read contract.

In <code>featureFlags.test.ts</code>, add the env-true negative contract explicitly:

~~~typescript
import { describe, expect, it } from "vitest";
import { hermesFeatureFlags } from "./featureFlags";

const attemptedCapabilityOverrides = {
  QS_HERMES_SHELL_ENABLED: "true",
  QS_HERMES_CHAT_ENABLED: "true",
  QS_HERMES_EXECUTION_ENABLED: "true",
  QS_HERMES_UNIFIED_RESULTS_ENABLED: "true",
  QS_HERMES_LEGACY_REDIRECTS_ENABLED: "true",
} as NodeJS.ProcessEnv;

describe("hermesFeatureFlags", () => {
  it("allows only the shell flag to vary in this slice", () => {
    expect(hermesFeatureFlags(attemptedCapabilityOverrides)).toEqual({
      shell: true,
      chat: false,
      execution: false,
      unifiedResults: false,
      legacyRedirects: false,
      deliveryState: "blocked_in_this_slice",
    });
    expect(hermesFeatureFlags({
      ...attemptedCapabilityOverrides,
      QS_HERMES_SHELL_ENABLED: "false",
    })).toEqual({
      shell: false,
      chat: false,
      execution: false,
      unifiedResults: false,
      legacyRedirects: false,
      deliveryState: "blocked_in_this_slice",
    });
  });
});
~~~

In <code>hermes-fixture-api.test.mjs</code>, import the server factory and shared <code>validateCombinedFixture</code>, bind it to an ephemeral <code>127.0.0.1</code> port, and assert all five exact fixture names load; the three exact GET routes return their corresponding complete object plus <code>Cache-Control: no-store</code>; an unknown GET returns 404; POST/PUT/PATCH/DELETE return 405 with unchanged fixture bytes; an unknown fixture is rejected before <code>listen()</code>. Also assert every fixture has exactly <code>schema_version</code>, <code>health</code>, <code>artifacts</code>, and <code>candidates</code> at the root. For each required candidate key locked above, clone a fixture, delete that key, and assert the same validator rejects it; explicitly cover <code>goal</code>, <code>universe</code>, and all required nullable keys so JSON cannot silently drift from the typed builder. Finally, spawn <code>npx playwright test --list</code> twice with <code>PW_HERMES_WORKBENCH_FIXTURE=normal</code>: once adding <code>QUANT_API_COMMAND</code> and once adding <code>PW_REUSE_SERVER=1</code>. Both must exit non-zero with the stable message <code>fixture mode cannot reuse or override the backend</code> before any server starts.

- [ ] **Step 2: Run and confirm RED**

Run:

~~~bash
npm --prefix src/frontend test -- lib/hermes/viewModel.test.ts \
  lib/hermes/featureFlags.test.ts lib/hermes/routes.test.ts
node --test src/frontend/tests/support/hermes-fixture-api.test.mjs
~~~

Expected: TypeScript modules do not exist and the Node test cannot import the fixture server.

- [ ] **Step 3: Implement deterministic derivation and flags**

Use:

~~~typescript
export function hermesFeatureFlags(
  env: NodeJS.ProcessEnv = process.env,
): HermesFeatureFlags {
  return {
    shell: env.QS_HERMES_SHELL_ENABLED !== "false",
    chat: false,
    execution: false,
    unifiedResults: false,
    legacyRedirects: false,
    deliveryState: "blocked_in_this_slice",
  } as const;
}
~~~

Do not read, normalize, or forward any non-shell capability environment variable in production. <code>blocked_in_this_slice</code> is a versioned delivery fact, not the result of a live probe. This slice must not add a platform capability getter, API route, HQA contract reader, browser fetch, or health-field inference.

The view model:

- picks the latest automation artifact by <code>occurred_at</code>;
- counts only exact known four job IDs;
- adds exceptions only for <code>failed/stale/never_run</code> or degraded notification status;
- maps only verified, approval-enabled pending candidates to approval attention; <code>migration_required</code>, <code>corrupt</code>, and legacy-unbound items become non-actionable degraded attention and never market predictions;
- derives state from source/feed truth, never from timers;
- keeps technical facts separate from user summaries.
- sorts attention deterministically by approval, failure, stale, offline, degraded, then stable ID; no filesystem or response order may change the visible priority.

Routes export:

~~~typescript
import { localizePath, type Locale } from "@/lib/locale";

export const hermesRoutes = {
  today: "/hermes",
  tasks: "/hermes/tasks",
  approvals: "/hermes/approvals",
  results: "/hermes/results",
} as const;

export type HermesSearchParams = Record<
  string,
  string | string[] | undefined
>;

export function hermesHomeHref(
  locale: Locale,
  searchParams: HermesSearchParams,
): string {
  const query = new URLSearchParams();
  for (const key of Object.keys(searchParams).sort()) {
    const values = searchParams[key];
    for (const value of Array.isArray(values) ? values : [values]) {
      if (value !== undefined) query.append(key, value);
    }
  }
  const suffix = query.size ? `?${query.toString()}` : "";
  return localizePath(`/hermes${suffix}`, locale);
}
~~~

Add route tests for no-query, one-query, repeated-query, Chinese/English locale, and deterministic key ordering. Conversation is rendered as an <code>aria-disabled</code> internal-nav item with no href while chat is unavailable; do not create a dead <code>/hermes/conversation</code> link.

- [ ] **Step 4: Implement the combined fixtures and GET-only server**

Each JSON file has exactly <code>schema_version</code>, <code>health</code>, <code>artifacts</code>, and <code>candidates</code>. The last three are complete valid responses for <code>GET /api/health</code>, <code>GET /api/hermes/artifacts</code>, and <code>GET /api/agent/candidates</code> after candidate-integrity Task 5. Every candidate object contains all eleven required <code>CandidateReadItem</code> keys; nullable means “required key whose value may be null,” never an omitted key:

- <code>normal</code>: healthy four-job automation, meaningful 9H results, and one verified pending factor with an authoritative 64-character <code>manifest_digest</code> and <code>approval_enabled=true</code>.
- <code>degraded</code>: exactly one stale/failed automation exception plus one <code>migration_required</code> item whose observed digest is never approval authority.
- <code>offline</code>: complete unavailable health/feed responses and a valid candidate-list envelope.
- <code>empty</code>: available empty feed and an empty candidate list.
- <code>long-content</code>: valid degraded data with a 64-character digest, long Run ID, long Chinese and English error text, and limitations.

Implement <code>validateCombinedFixture(payload)</code>, <code>loadFixture(name)</code>, and <code>createFixtureServer(fixture)</code> as named exports in <code>hermes-fixture-api.mjs</code>, plus the CLI <code>node ... &lt;port&gt; &lt;fixture&gt;</code>. <code>loadFixture</code> must run the one shared validator before returning, and the server must accept only that validated object; no alternate unvalidated JSON path exists. Use only Node's HTTP/filesystem standard library, bind only <code>127.0.0.1</code>, serve only the three exact GET endpoints, emit <code>Cache-Control: no-store</code>, return 404 for other GETs and 405 for every non-GET, and log only method/path/status. Reject an unknown or contract-invalid fixture before opening a socket. Import no platform/HQA production module and open no database/provider/process.

In <code>playwright.config.ts</code>, validate optional <code>PW_HERMES_WORKBENCH_FIXTURE</code> against the same five-name allowlist before creating <code>webServer</code>. If fixture mode coexists with either <code>QUANT_API_COMMAND</code> or <code>PW_REUSE_SERVER=1</code>, throw <code>Error("fixture mode cannot reuse or override the backend")</code> before opening a process or socket. Otherwise fixture mode unconditionally uses <code>node src/frontend/tests/support/hermes-fixture-api.mjs ${backendPort} ${fixture}</code>; only non-fixture real-smoke mode may honor <code>QUANT_API_COMMAND</code> or reuse. Keep the fixture name only in the Playwright process/config metadata: never put it in the frontend server environment, Next public environment, browser storage, URL, or production module.

- [ ] **Step 5: Run pure and fixture-server tests**

Run:

~~~bash
npm --prefix src/frontend test -- lib/hermes/viewModel.test.ts \
  lib/hermes/featureFlags.test.ts lib/hermes/routes.test.ts
node --test src/frontend/tests/support/hermes-fixture-api.test.mjs
npm --prefix src/frontend run type-check
~~~

Expected: pass.

- [ ] **Step 6: Commit**

~~~bash
git add src/frontend/lib/hermes \
  src/frontend/tests/fixtures/hermes-workbench \
  src/frontend/tests/support/hermes-fixture-api.mjs \
  src/frontend/tests/support/hermes-fixture-api.test.mjs \
  src/frontend/playwright.config.ts
git commit -m "feat(frontend): derive truthful Hermes read-only workbench state"
~~~

---

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

### Task 9: Full verification, professional review, and docs reconciliation

**Files:**

- Modify platform <code>docs/INDEX.md</code> and frontend design docs.
- Modify HQA <code>docs/README.md</code> and D-31 status.

**Interfaces:**

- Produces a code-delivered F2 read-only shell; chat/execution/unified-results/legacy-redirects remain hard false and capability notice remains the static <code>blocked_in_this_slice</code> delivery fact.
- Verification is partitioned deliberately: complete non-fixture legacy coverage uses the real isolated temporary backend; candidate semantics and visuals use combined GET-only fixtures; rollback uses a simultaneous second frontend process.
- Final shared-doc reconciliation is serialized after gateway Task 4 and candidate Task 8; it never commits an unfinished sibling plan's status or overwrites their completed evidence.

- [ ] **Step 1: Run all frontend static gates**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
npm --prefix src/frontend run test
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
node --test src/frontend/tests/support/hermes-fixture-api.test.mjs
! rg -n "QS_HERMES_(CHAT|EXECUTION|UNIFIED_RESULTS|LEGACY_REDIRECTS)_ENABLED" \
  src/frontend --glob '!**/*.test.*'
! rg -n "AgentTaskForm|useMutation|apiPost|/api/agent/tasks|WebSocket|EventSource" \
  src/frontend/app/hermes src/frontend/components/hermes
~~~

Expected: all commands pass and both searches return no matches. The full unit suite includes the env-true negative flag test and exhaustive approval-binding tone test. Stop the existing dev server before build if its build directory is shared, then restart it only for smoke.

- [ ] **Step 2: Run complete hermetic E2E**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend
env -u PW_HERMES_WORKBENCH_FIXTURE -u PW_HERMES_ROLLBACK_E2E \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
QUANT_API_COMMAND="/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8766" \
npx playwright test --config playwright.config.ts --workers=1 \
  --grep-invert "@combined-fixture|@rollback"

for fixture in normal degraded; do
  env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
  PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
  PW_HERMES_WORKBENCH_FIXTURE="$fixture" \
  npx playwright test tests/e2e/hermes-workbench.spec.ts \
    --config playwright.config.ts --workers=1 \
    --grep @combined-fixture || exit 1
done

for fixture in normal degraded offline empty long-content; do
  env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
  PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
  PW_HERMES_WORKBENCH_FIXTURE="$fixture" \
  npx playwright test tests/e2e/hermes-workbench-visual.spec.ts \
    --config playwright.config.ts --workers=1 \
    --grep @combined-fixture || exit 1
done

env -u QUANT_API_COMMAND -u PW_REUSE_SERVER \
PW_E2E=1 PW_BACKEND_PORT=8766 PW_FRONTEND_PORT=3002 \
PW_HERMES_WORKBENCH_FIXTURE=normal \
PW_HERMES_ROLLBACK_E2E=1 PW_HERMES_ROLLBACK_PORT=3003 \
npx playwright test tests/e2e/hermes-rollback.spec.ts \
  tests/e2e/navigation-layout.spec.ts tests/e2e/locale-toggle.spec.ts \
  --config playwright.config.ts --workers=1
~~~

Tag every test that requires a combined fixture, including the visual matrix, with <code>@combined-fixture</code>; tag only the data-agnostic real Hermes case <code>@real-backend-smoke</code>; tag second-process tests <code>@rollback</code>. The first command excludes both fixture and rollback tests, and the dedicated final command supplies the rollback environment. Expected: the partitioned commands cover the complete suite without real DB/provider/paper/live use, all candidate assertions consume explicit fixtures, English normal runs at all four viewports, rollback uses the second frontend, and no ordinary command creates or updates a snapshot.

- [ ] **Step 3: Independent frontend/UX and code review**

Use the professional frontend agent plus a separate reviewer and <code>superpowers:requesting-code-review</code>. Require original-size review at all four viewports and report:

~~~text
Five-second comprehension; one safety message; action/exception hierarchy;
normal automation compression; Chinese/English long content; keyboard/focus;
44px touch targets; reduced motion; no scroll hijack; 0 console issues; disabled
composer honesty; static blocked_in_this_slice capability truth; non-shell env
overrides remain ineffective; enabled/rollback navigation; no old deep-link
regression; no mutation path.
~~~

Address accepted findings and rerun static plus E2E gates.

- [ ] **Step 4: Local read-only runtime smoke**

With the existing backend/frontend and Docker database, visit the enabled process:

~~~text
/zh/hermes
/zh/hermes/tasks
/zh/hermes/approvals
/zh/hermes/results
/en/hermes
/
/zh
~~~

Then rerun Task 8's <code>PW_HERMES_ROLLBACK_E2E=1</code> command so Playwright starts the second frontend with <code>QS_HERMES_SHELL_ENABLED=false</code>. On that second process verify <code>/zh</code> is Dashboard, both navigation surfaces use Dashboard as home, <code>/zh/hermes</code> remains independently read-only, and back/forward settles without a redirect loop. On the enabled process verify real 9H reads, root redirect, repeated query/hash locale behavior, and one safety strip. Do not send a prompt, approve a candidate, run research, or call a provider.

- [ ] **Step 5: Reconcile status and commit**

Before editing either shared status surface, verify the cross-plan barrier:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
git status --short --branch
git log --oneline -n 12

cd /Users/sunyibo/programs/Hermes-quant-agent
git status --short --branch
git log --oneline -n 12
~~~

Re-read the current platform <code>docs/INDEX.md</code>, HQA <code>docs/README.md</code>, D-31 spec, gateway Task 4 delivery/review evidence, candidate Task 8 delivery/review evidence, and this plan's Steps 1-4 outputs from the current HEADs. Stop without editing shared docs if either sibling task is incomplete, its docs commit is absent, its review is unresolved, or either shared status file has an unexplained concurrent diff. Do not infer completion from old checkboxes or pre-barrier notes.

After the barrier passes, this Task 9 executor is the sole reconciliation owner. Preserve the sibling plans' already-committed facts verbatim, add only this frontend delivery's new evidence, and record the fresh HEADs, exact test counts, process URLs, and smoke date used for the reconciliation.

Document:

- F0/F1 approval evidence and selected direction;
- F2 read-only shell delivered;
- enabled root/navigation now Hermes; rollback root/navigation returns to Dashboard while direct Hermes remains read-only;
- chat/execution/unified dynamic results/legacy redirects are literal false even under env=true attempts;
- capability notice is the static <code>blocked_in_this_slice</code> delivery fact because this wave has no platform capability-contract getter/route;
- old four pages retained pending parity;
- exact current test counts and smoke date;
- Hermes gateway capability blockers from the separate contract plan.

Commit the two repositories separately and stage only the named status files:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
git diff --check -- docs/INDEX.md docs/design/hermes-workbench/README.md
git add docs/INDEX.md docs/design/hermes-workbench/README.md
git diff --cached --check
git commit -m "docs(frontend): record Hermes read-only shell delivery"
git status --short --branch

cd /Users/sunyibo/programs/Hermes-quant-agent
git diff --check -- docs/README.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
git add docs/README.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
git diff --cached --check
git commit -m "docs(frontend): reconcile Hermes read-only shell delivery"
git status --short --branch
~~~

The platform docs commit must finish before changing repository, and the HQA docs commit must contain no platform path. Do not stage this plan, unrelated dirty/generated files, or cross-repository changes in either final docs commit.

## Completion criteria

- F0 and F1 each have explicit user approval and independent frontend/UX review.
- Production code reflects the approved prototype, not the brainstorming thumbnail.
- One global safety status is visible and no duplicate paper-only message remains.
- Today view prioritizes attention/exceptions, compresses healthy automation, and hides technical fields by default.
- Tasks/Approvals/Results are useful, honest, read-only, and mutation-free.
- Composer clearly explains why it is unavailable and cannot make any network submission.
- 1440/1280/768/390, Chinese/English, long content, full-page 44px/focus, reduced motion, console, and overflow gates pass.
- <code>/</code> and locale roots enter Hermes only after approval; repeated query/hash survives; <code>QS_HERMES_SHELL_ENABLED=false</code> returns both root and home navigation to Dashboard while direct <code>/hermes</code> remains read-only.
- Factor Lab, Backtester, Experiments, Agent Studio, deep links, API/CLI/engines/artifacts, and safety gates remain available.
- Chat, execution, unified dynamic result migration, and legacy redirects are literal false under env=true attempts, report <code>blocked_in_this_slice</code> without a fake live probe, and require later independently written plans.
