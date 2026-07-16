### Task 8: Full verification, independent code review, and documentation reconciliation

**Files:**

- Reconcile platform live docs: <code>AGENTS.md</code>, <code>README.md</code>, and <code>docs/INDEX.md</code>.
- Reconcile HQA live docs: <code>AGENTS.md</code>, <code>README.md</code>, <code>docs/README.md</code>, <code>skills/hermes/hqa-quant/SKILL.md</code>, <code>docs/design/vision-daily-life.md</code>, <code>docs/design/hermes_quant_agent_plan.md</code>, <code>docs/design/2026-07-01-roadmap-phases-0b-4.md</code>, and D-31 <code>docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md</code>.
- Do not modify historical plans, completed delivery records, archived phase docs, or checkbox history merely to make them look current.

**Interfaces:**

- Consumes every prior task.
- Produces current, evidence-backed project status; does not apply the real migration or perform a real promotion.

- [ ] **Step 1: Run focused platform safety suites**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
./ai-quant/bin/python -m pytest -q \
  tests/test_candidate_manifest.py \
  tests/test_candidate_repository.py \
  tests/test_candidate_migration.py \
  tests/test_agent_phase7.py \
  tests/test_api_agent.py \
  tests/test_agent_propose_source_file.py \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_promotion_workspace.py \
  tests/test_factor_registry_factory.py \
  tests/test_cli_experiment_provider.py \
  tests/test_cli_json_output.py \
  tests/test_api_response_models.py \
  tests/test_frontend_openapi_generation.py \
  tests/test_frontend_e2e_config.py
./ai-quant/bin/python -m ruff check src/quant_system tests
~~~

Expected: all pass.

- [ ] **Step 2: Run frontend and HQA caller gates**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
npm --prefix src/frontend run test
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
~~~

Expected: all pass.

- [ ] **Step 3: Request adversarial code review**

Use <code>superpowers:requesting-code-review</code> and the user-requested Code Reviewer agent. The review prompt must require:

~~~text
Try to approve bytes different from the reviewed manifest; race approve/reject
and candidate regeneration; use empty/dot/../../absolute/slash/backslash/reserved
candidate IDs; swap candidate root/lock/candidate entries after dirfd open; use
symlink/FIFO/path traversal; corrupt a manifest; reuse a legacy lock; mutate the
candidate between approval and compile; bypass explicit HQA Gate 2 CAS; omit Gate
3 CLI arguments; produce an incomplete intent-to-add patch; tamper base/head/scoped
bytes; contaminate the main worktree; and find any path that commits or executes
resident paper/live code. Report findings by severity with exact files.
~~~

Address accepted findings using <code>superpowers:receiving-code-review</code> and rerun the affected plus full gates.

- [ ] **Step 4: Run complete repository gates**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
./scripts/verify.sh

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest
~~~

Expected: both complete suites pass. Record exact counts from output; do not reuse historical counts.

- [ ] **Step 5: Reconcile docs and commit**

Update docs with these exact status facts:

- one repo-anchored canonical candidate root, its <code>QS_AGENT_OUTPUT_DIR</code> override, and the fact that CWD/<code>QS_DATA_DIR</code> do not relocate it;
- current real dry-run migration result;
- real data not migrated without separate authorization;
- the <code>verified</code>/<code>migration_required</code>/<code>corrupt</code> read states and <code>legacy_unbound</code> non-authority;
- Gate 2's explicit human <code>candidate-id + expected-digest + expected-status=pending + note</code> CAS command and no-refetch rule;
- Gate 3's required candidate/digest/base prepare command, four-field result, promotion-ID-only status/cleanup, explicit-only abandon, isolated review worktree, and no automatic commit;
- new Hermes approval UI remains disabled until the frontend/bridge gates.

Use each live document for its existing role: agent rules in <code>AGENTS.md</code>; user-facing commands/capabilities in root <code>README.md</code>; current execution truth in HQA <code>docs/README.md</code> and platform <code>docs/INDEX.md</code>; Hermes command wording in the installed skill source; experience language in <code>vision-daily-life.md</code>; system flow in <code>hermes_quant_agent_plan.md</code>; decision/delivery status in the active roadmap; and security/design truth in D-31. Mark this candidate baseline delivered only after fresh gates pass, while later D-31 frontend/bridge approval exposure remains pending.

Commit the two repositories separately and stage only the named files:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
git add AGENTS.md README.md docs/INDEX.md
git commit -m "docs(agent): record candidate integrity and Gate 3 delivery"
git diff --check HEAD^ HEAD

cd /Users/sunyibo/programs/Hermes-quant-agent
git add AGENTS.md README.md docs/README.md skills/hermes/hqa-quant/SKILL.md \
  docs/design/vision-daily-life.md docs/design/hermes_quant_agent_plan.md \
  docs/design/2026-07-01-roadmap-phases-0b-4.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
git commit -m "docs(agent): reconcile candidate integrity and Gate 3 delivery"
git diff --check HEAD^ HEAD
git status --short --branch
~~~

Expected: docs match current code/test evidence; unrelated dirty files remain untouched.

## Completion criteria

- API, CLI, one-shot loader, HQA, migration, and promotion all resolve the same canonical candidate through <code>resolve_agent_output_dir</code>; active candidate code has no CWD-relative <code>Path("data/agent_run")</code>, <code>QS_DATA_DIR</code> coupling, module-level candidate constant, or direct candidates-directory option.
- One shared candidate-ID validator protects creation/get/review/detail/SafetyGate/CLI/migration/promotion; empty/dot/<code>../../</code>/absolute/slash/backslash/noncanonical/reserved IDs produce zero writes, and directory/metadata/manifest IDs must agree.
- A candidate's metadata/artifacts are immutable after atomic publication.
- Same-ID retries are exactly idempotent or fail with conflict; they never overwrite.
- Candidate write/review/migration uses held no-follow dirfds, verified regular locks/controls, fsync, and no-replace publication; root/lock/candidate swaps fail closed without writing the replacement tree.
- Approval is explicit expected-digest plus <code>expected_status=pending</code> CAS, final decisions never flip, and stale/legacy approval never authorizes.
- HQA and its installed skill require human-supplied candidate ID/digest/pending/note and never refetch values during approval.
- Every compile/materialize path re-verifies exact bytes.
- The real legacy-root command remains dry-run until separately authorized.
- Until real apply is separately authorized, <code>migration_required</code>/<code>corrupt</code> candidates remain individually visible for read-only diagnosis beside <code>verified</code> items but expose no authoritative approval digest and cannot mutate or execute; legacy source bytes/types/inodes remain unchanged.
- Gate 3 prepare requires candidate ID/digest/base, emits promotion ID/worktree/patch/manifest, and creates a complete intent-to-add, binary/full-index, replay-verified three-path patch in a persistent review workspace. Status/cleanup locate it only by promotion ID, committed status replays <code>BASE..HEAD</code>, main worktree fingerprints remain unchanged, and default cleanup cannot orphan an unreferenced human commit; abandon is explicit only.
- Neither repository adds a paper/live path, automatic commit, provider call, or browser-side approval bypass.
- All listed platform/HQA live docs agree with fresh delivery evidence; historical plans remain historical.
- Focused and complete two-repository test gates pass with fresh evidence.
