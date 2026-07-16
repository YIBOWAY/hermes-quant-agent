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
