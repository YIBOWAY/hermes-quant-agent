# AGENTS.md

Rules for AI agents working in this repository.

## Project Role

- **Current local operations snapshot (2026-08-09):** Hermes official source
  `2446c8bb6755` is integrated at live branch commit `a4bac87463fd`, including
  bounded macOS cold-start socket-drain hardening. Normal Mac
  startup is the Platform runtime's `bash scripts/local_mac_stack.sh start`,
  which manages Docker plus Hermes/backend/frontend/connector LaunchAgents.
  Do not make service lifetime depend on an AI-tool terminal. D-33 adds a fifth
  project-owned LaunchAgent for the paper-factor automation driver. Local trust
  (2026-08-01) bypasses only the candidate-admission **identity ritual**
  (preflight evidence, three-repo digests, clean checkout, connector ceremony)
  and reports `admission_mode=local_trust` without candidate identity. It does
  not authorize factor promotion. Factor automation is a separate,
  source-default-OFF, dual-Flag path: the inspected owner runtime explicitly
  enabled both pairs on 2026-08-10 after the full suites and cold-start check;
  when both HQA and Platform pairs are exactly
  enabled it replaces Gate 1/2/3 with digest-bound machine policy for
  `paper_only` factors only. The manual Scene-B path and every live-trading,
  kill-switch, migration, and public-release boundary remain independent.
- **D-34 runtime snapshot (2026-08-12):** migration 030–032 are applied exactly
  once after owner backup and isolated restore; the current Platform runtime is
  `237b4b4`. The enabled D-34
  LaunchAgent reuses the installed Hermes xAI OAuth session through the persistent
  local proxy on `127.0.0.1:8645`;
  the research chain does not require a separate embedding provider. One real
  Futu → Grok/RD-Agent → Qlib → Platform replay → Artifact → paper canary
  cycle completed with exact-input comparison accepted and canary allocation
  below 1% NAV. A full Docker/database/LaunchAgent cold restart preserved the
  Mandate, jobs, Artifact, canary and budget without duplicates. D-33 maintenance
  and trading now select only `automation_source=d33`, while D-34 selects only
  `automation_source=d34`. Durable failure acceptance covers Futu unavailable,
  tampered job input, research timeout, Docker exit 137, and expired external-effect
  leases without leaking a lease or duplicating work. The 10-cycle/5-trading-day
  soak remains open at 1/10 cycles and 1/5 observation days; the first natural
  signal exposed and retained an `account_frozen` failure before order creation.
  `237b4b4` includes the `2db9bdf` scoped frozen-account authority fix and now
  projects the durable 10-cycle/5-observation-day time gate through effective
  safety and `/hermes`; unchanged intraday P&L records at most one observation
  per Shanghai date. It permits the shared frozen paper account only through
  current active-Mandate D-34 `paper_only` authority while leaving the account
  kill switch true; the next natural trading window remains required runtime
  evidence. This is not live eligibility. See
  `docs/plans/2026-08-11-d34-mandate-dual-engine-paper.md`.
  The owner has standing authorization for normal reversible local development,
  migrations, configuration, service/LaunchAgent restarts, tests, test data and
  local commits; do not pause to request those actions again. Live trading,
  automatic GitHub push and unrecoverable deletion remain outside that standing
  authorization.
- **Checkout role boundary:** development is allowed only in the primary HQA
  and Platform checkouts or purpose-named source worktrees under
  `/Users/sunyibo/programs/.worktrees/`. Both checkouts under
  `data/_runtime/agent-v02-work/` are deployment mirrors: fetch and
  fast-forward only; never edit, commit, rebase, or push from them.

- `Hermes-quant-agent` is the active orchestration/COO layer for the local
  `/Users/sunyibo/programs/ai-quant-platform` backend.
- Start at `docs/README.md`; it distinguishes the product roadmap, completed
  cross-repo delivery records, the drafted first implementation wave, and historical material.
- The product roadmap is `docs/design/2026-07-01-roadmap-phases-0b-4.md`.
  The completed Phase 1a-4 v2 implementation record is
  `docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md`; Slices 9A through 9H
  are all delivered. D-32 continues to govern Agent v0.2 Web Chat. D-33's
  approved paper-automation implementation and acceptance record is
  `docs/plans/2026-08-10-full-automation-paper-path.md`; its operator contract is
  `docs/runbooks/full-automation-paper.md`.
  D-34's current source implementation plan is
  `docs/plans/2026-08-11-d34-mandate-dual-engine-paper.md`; it does not supersede
  D-32 public Web Chat work and is not runtime acceptance evidence.
  `docs/superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md` is the
  predecessor Wave 3 delivery record and blocker input, not an active queue;
  the full 9H record is also completed historical delivery evidence.
  D-32 freezes the target as a real Agent v0.2 with complete `/hermes` Web Chat.
  Discord remains an independently usable Hermes-native channel; do not build a
  temporary web chat, Discord/TUI bridge, direct-Hermes composer, or
  `/api/agent/tasks` fallback. Internal slices stay dark and the public composer
  remains OFF until the v0.2 plan's full release gate passes. Discord/historical
  sessions are Web read-only; Web writes use a new managed Hermes Session, and
  continuing external context requires an explicit fork with immutable lineage.
  The 2026-07-16 GET-only/reconcile-only/never-live-006 description is
  **historical evidence**, not current instructions. Do not use it as NEXT.
- **Agent v0.2 operator boundary (2026-08-10 snapshot):** migration 006–029 was
  live in the inspected `quantplatform`; 028 was applied exactly once after
  backup/isolated restore (marker/version each 1, target triggers 2). Do not
  re-apply it. Migration 029 was subsequently applied exactly once after its
  own backup and isolated restore rehearsal; it is the append-only automatic
  promote/demote quota authority and must not be replayed. Two bounded private
  AlphaZeroBeta runs reached real
  UI/Session/dispatch/provider/approval/durable-Run/direct-PDF/full-text/DB
  milestones, but **both failed paper intake** and were revoked; connector
  cleanup is `reconcile_only`. The earlier approval-projection failure remains
  separate FAIL evidence. Full evidence is in
  `docs/audits/2026-07-31-alphazerobeta-paper-research-web-e2e.md`.
  - A `succeeded` Command/Run is not paper-research acceptance. The 2026-08-01
    retest trace recorded `web_search=0` and one failed `web_extract`, while
    model prose claimed web search. Reproducibility and the non-actionable verdict
    are `UNVERIFIED / NOT ACCEPTED`; factor/backtest/Gate/result are
    `NOT EVALUATED`, not `EXPECTED_NOT_REACHED`.
  - Before another paper candidate, runtime must bind digest-bound
    `execution_contract=hqa.paper_intake/v1`, emit typed no-body tool receipts,
    invoke the HQA subprocess verifier, and fail before `mark_succeeded` when
    the contract is unmet. Skill 1.18.5 hardening alone did not enforce this.
    Do not invent a factor or trust model prose to make the test look broader.
  - HQA research claim bodies (paper title plus ordered universe) remain only in
    the encrypted Intent Payload Store; public/workflow projections carry
    digests. Claim binding is Attempt-1-only and completion re-verifies exact
    lineage. If an actionable paper needs an ordered universe, stop for explicit
    user input; never infer one.
  - `release_authorized`, `public_write_authorized` and
    `public_chat_write_ready` were all false after cleanup. Release status is a
    durable runtime fact, never a docs flag. This docs-only commit changes HQA
    runtime identity, so any new candidate/release must refresh clean three-repo
    HEADs, suites and sealed evidence; never reuse the revoked candidate or old
    manifest.
- Slice V0/V1/V2 close-out records under `docs/audits/` remain historical
  provenance. Their old runtime commits, roles, PIDs, “candidate not installed”
  and write-gate conclusions must not override the 2026-08-01 snapshot above.
- Slice V3's foundation was source-accepted and installed locally in dark mode
  at historical HQA `121926388d86`; current installed identity is the exact
  runtime recorded by the latest audit, not that old anchor. See
  `docs/audits/2026-07-19-agent-v0-2-v3-acceptance.md` and
  `docs/runbooks/agent-v0-2-v3-authorities.md`. `IntentPayloadStore` owns encrypted
  bodies/TTL/tombstones; `WorkflowAuthority` owns Task/Attempt facts. Hermes may
  only call `show|events|audit|rebuild` on the workflow surface; payload
  `put|bind_resolve|probe` use `python -m hqa.intent_payload_cli` (platform must
  never `import hqa`). `probe` is non-creating; ordinary writes cannot create a
  key. Operator-only `initialize-key` requires exact runtime/preflight binding
  and is never exposed to BFF/worker/skill/retry. Recovery temp/uv-cache stay
  under owner-controlled `0700`; private `HOME` is not interpreter authority,
  which comes from exact uv Python 3.11 or `HQA_UV_MANAGED_PYTHON_ROOT`.
  The retention cron is local
  `--no-agent` and must stay free of provider, HTTP, database and trading calls.
  V3 alone did not enable Web writes; later V6 local dark + L2a did under
  separate local authorization (public cutover still OFF).
- V4–V8 M1–M6 details remain dated delivery evidence. Current work starts from
  the safe dark state above: first close the paper-intake runtime P1, then
  complete the still-unproven multi-turn, restart, exact-message fork, Run-stop,
  Vertical A and actionable-paper Gate browser flows. Then refresh
  identities/suites/sealed preflight and use a **new**
  explicitly authorized private candidate; do not re-run migration 028. Only an
  accepted exact candidate plus the full release Gate may precede a separately
  authorized stamp/public cutover and rollback smoke. Authoritative status is
  `docs/README.md` plus the active plan.
- Hermes updates are operator-controlled and periodic/manual. The no-agent
  compatibility watcher may report drift but must never pull, merge, install,
  restart or enable gates. The upstream Hermes 40k full suite is not an Agent
  v0.2 release gate. Wave
  3E-A has delivered and locally accepted the read-only Unified Results catalog,
  details and exact-link projection; independent Hermes research Run results and
  full results cutover remain blocked. Wave 3F has only a page-scoped,
  reversible Agent Studio redirect mechanism that defaults OFF; exact-bound audit
  parity, user cutover approval, the other three legacy pages, and all global
  legacy redirects remain blocked. Do not infer work from an older plan or
  backlog. The platform frontend plan is the Slice 0-8
  delivery record, not the active backlog. The 2026-07-07 Phase 1a-4
  implementation plan is superseded material and must not be followed task-by-task.
- Treat `ai-quant-platform/docs/phases/phase_15_iteration_roadmap.md` as
  reference material only. Do not use it as an independent product roadmap.
- The quark_program three-project integration spec is
  `docs/superpowers/specs/2026-08-10-quark-program-integration-design.md`
  (P1 Asia Radar + `/market-cross-section` delivered; P2/P3 are research-only
  tracks). Its Phase 1.5 review findings (§2.8b) were all fixed and
  re-verified on 2026-08-11; Phase 2 (local indices + leader mapping) is the
  next quark slice.

## Safety Rules

- Keep Phase 0/1a read-only or proposal-only unless a plan explicitly says
  otherwise.
- Agent v0.2 development may use final production modules behind dark gates.
  **Public** `chat_write_ready` / public composer stay OFF until V8. Local
  single-user dark enablement may open settings-gated mutation/composer and
  supervised dispatch under the trading kill switch — that is not public cutover
  and not Plan-V6 full-UI acceptance. A fake Hermes adapter is for hermetic
  tests only, never a temporary public user path.
- Migrations 006 through 028 were present in the explicitly authorized
  2026-08-01 live `quantplatform` snapshot. Migration 028 was applied once after
  backup/isolated restore; do not re-apply it or any earlier migration. Recheck
  live metadata before acting, and require separate authorization for every
  future migration. Migration 015 narrows runtime managed-session provisioning to
  exact columns and must fail closed on ACL drift. Migration 022 makes both
  selected source/fork point and Hermes-canonical resolved parent mandatory;
  023 separates the durable conversation root from the resolved Run tip; 024
  records approval/stop outcome CAS and consumes the exact control outbox; 025
  binds managed Session/Command writes to the current paper epoch plus the
  active candidate or accepted release; 026 seals research claim/start/continue
  digests through Gate 1/2/3 and splits completion into claim-less v1 versus
  exact-lineage v2; 027 expands only the bounded candidate TTL ceiling to two
  hours and grants no new capability; migration 028 requires
  canonical default paper authority with exact raw safety consistency and
  rejects candidate writes at a stale paper-authority epoch.
  Schema readiness and the constrained-role canary are not public write
  authorization.
- Treat the local `~/.hermes/hermes-agent` checkout as a third owned dependency
  for v0.2 Durable Run work. Pin source/install/runtime identity and develop in a
  controlled branch/worktree; do not patch an unidentified live checkout in
  place. Platform projections must never counterfeit missing Hermes canonical
  Run/event/provider/approval/stop facts.
- Never bypass `paper_trading`, `live_trading_enabled=false`, `kill_switch`,
  or the applicable manual/machine policy gate.
- The supported **manual** HQA Scene-B path uses three human gates: formula confirmation,
  candidate source approval, and promotion diff review/commit. All three are
  implemented in the HQA wrappers; raw platform APIs/CLI remain generic
  primitives and do not independently prove HQA Gate 1 provenance. D-33's
  dual-Flag automatic paper path is one exception: it uses `reviewer=auto`,
  `registration=auto_promote`, a versioned policy digest, verified final-backtest
  evidence, two-phase commit, local ff-only land, and immutable
  `promotion_scope=paper_only`. It never auto-pushes and cannot populate the
  live registry. D-34 is a second, separate paper-only exception: an active
  Mandate may autonomously run Futu → RD-Agent/Qlib → Platform replay →
  Artifact/Policy → canary, but execution is still rechecked against the
  durable Mandate, emergency stop, budget, digest and paper exposure policies.
  D-34 artifacts have no live upgrade operation. The following manual rules
  continue to apply to manual Scene-B and every live qualification. For the
  final paper task, plan confirmation is a separate human stop and is not Gate
  1; the coordinator must pause independently at plan confirmation and Gates
  1/2/3, and it cannot complete the Task before the human Gate 3 commit.
  - Gate 1 is enforced by the HQA Scene-B wrapper: the human supplies the
    SHA-256 of the exact reviewed source plus a non-empty confirmation note;
    HQA stages those bytes read-only and persists a confirmation and exact
    candidate/manifest binding. A raw platform review is only the Gate 2
    primitive and is not, by itself, Scene-B Gate 1 evidence.
  - Gate 2 is explicit human CAS:
    `candidate-id + expected-digest + expected-status=pending + note`.
    HQA and the installed skill never list/refetch/substitute those values
    while approving. `list` is informational only; `detail` advertises an
    approval command only when the exact Gate 1 binding is present.
  - Gate 3 is entered through HQA `factor_repro_cli promote --candidate-id
    --expected-digest --final-backtest-receipt --base-commit`, which revalidates
    the exact Gate 1 binding and a content-addressed successful `--final`
    one-shot backtest receipt for the same candidate/digest
    before delegating to the platform primitive. That receipt must bind a real
    provider and the safe-read config/summary/report in one unique, non-overwriting
    experiment namespace. It prepares an isolated managed review worktree and a
    four-field `{promotion_id, worktree, patch, manifest}` payload only —
    never commits. Status/cleanup use `--promotion-id` only; abandon is
    explicit. HQA verifies the actual three-file dirty set/bytes/modes/patch and
    requires platform status schema 1.1 to return the same final-receipt
    provenance. A timeout is an
    unknown outcome and must use the printed recovery evidence. The human
    `git diff` review + commit IS Gate 3 completion. Direct
    platform `agent promote-candidate` is a generic primitive, not the supported
    Scene-B entry point.
- Canonical candidates live under the platform repo-anchored
  `data/agent_run/agent/candidates` (override only via `QS_AGENT_OUTPUT_DIR`).
  CWD/`QS_DATA_DIR` do not relocate them. Read states are
  `verified` / `migration_required` / `corrupt`; `legacy_unbound` never
  authorizes. Wave 2 completed one explicitly authorized real apply; every
  later migration/apply still requires separate authorization.
- HQA may run one-shot research backtests through digest-reverified approved
  candidates, but resident paper/live paths must only use promoted, registered,
  tested factors. The final Hermes workbench source includes managed write
  paths, but public mutation remains fail-closed until the runtime-bound release
  stamp/cutover, connector liveness and **full** browser DoD pass. Official API
  health/capability/session GETs do not call a provider. Do not downgrade to a
  GET-only fallback or claim the release-candidate UI is already public.
- Opportunity decisions never create or upgrade action eligibility. Link an
  action only by exact platform signal/execution IDs validated through the
  bounded observations seam; ticker/symbol similarity is never causal proof.

## Local Commands

- HQA tests: `./.venv/bin/python -m pytest` (use the venv `python` entrypoint;
  the generated `pytest` console script may resolve through `python3` and lose
  the exact uv-managed interpreter path required by recovery tests)
- Install Hermes wrappers: `bash scripts/install.sh`
- Persistent Mac stack:
  `bash /Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/scripts/local_mac_stack.sh start`
- Controlled Hermes update:
  `~/.hermes/scripts/hqa-hermes-update.sh check` then explicit `apply`
- Platform CLI path used by wrappers:
  `/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system`

## Collaboration

- Prefer docs/plans first, then implementation.
- Do not infer current progress or a next slice from an old plan's unchecked
  boxes. Reconcile `docs/README.md`, the current delivery record, git state,
  tests, and the running process.
- Preserve user and generated changes in the dirty worktree; do not revert
  unrelated files.
- If `.codegraph/` is absent, skip CodeGraph for this repo; the platform repo
  has CodeGraph and can use it for cross-file code questions.
