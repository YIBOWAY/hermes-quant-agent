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

