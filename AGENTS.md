# AGENTS.md

Rules for AI agents working in this repository.

## Project Role

- `Hermes-quant-agent` is the active orchestration/COO layer for the local
  `/Users/sunyibo/programs/ai-quant-platform` backend.
- Start at `docs/README.md`; it distinguishes the product roadmap, completed
  cross-repo delivery records, the drafted first implementation wave, and historical material.
- The product roadmap is `docs/design/2026-07-01-roadmap-phases-0b-4.md`.
  The completed Phase 1a-4 v2 implementation record is
  `docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md`; Slices 9A through 9H
  are all delivered. The only active implementation plan is
  `docs/superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md`.
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
- **Agent v0.2 release-candidate status (2026-07-24):**
  - Platform code baseline `2b2ad32` has since added sealed-artifact release
    admission and authoritative external-session exact-message fork backend;
    the release branch is still completing the frontend fork UI. Bind the final
    clean Platform HEAD only after that work closes.
  - HQA code baseline is `5370fd4`. Hermes managed-session baseline `ccd6eb0`
    has since added the required capabilities endpoint contract. Final release
    evidence must bind the actual clean three-repo HEADs, not these historical
    code anchors.
  - Revised migrations 006 through 015 are live. Migration 015 exact
    provisioning-column grants, ACL-drift fail-closed checks and the constrained
    runtime-role managed-session canary are accepted. Schema readiness never
    implies public write authorization.
  - The real paper-factor path completed exact Gate 1, Gate 2 CAS, Futu final
    receipt `backtest-32a022e60947473be481a2404d85646d`, human Gate 3 commit
    `7ad6a92`, registry promotion and cleanup. It is an operational US ETF proxy
    for the paper, **not** a full country-level reproduction. This backend/CLI
    evidence does not substitute for the final `/hermes` browser vertical.
  - Public release stamp/cutover, connector daemon/liveness, `/hermes`
    multi-turn/restart/exact-message-fork and both browser verticals remain
    pending. Do not write `release_authorized=true`, `chat_write_ready=true` or
    Agent v0.2 DONE before those facts exist.
- Slice V0/V1/V2 close-out records under `docs/audits/` remain historical
  provenance. Their old runtime commits, roles, PIDs, “candidate not installed”
  and write-gate conclusions must not override the 2026-07-24 release-candidate
  record above.
- Slice V3 is source-accepted and installed locally in dark mode at HQA
  `121926388d86`; see `docs/audits/2026-07-19-agent-v0-2-v3-acceptance.md` and
  `docs/runbooks/agent-v0-2-v3-authorities.md`. `IntentPayloadStore` owns encrypted
  bodies/TTL/tombstones; `WorkflowAuthority` owns Task/Attempt facts. Hermes may
  only call `show|events|audit|rebuild` on the workflow surface; payload put /
  bind_resolve go through `python -m hqa.intent_payload_cli` (platform subprocess
  port — platform must never `import hqa`). The retention cron is local
  `--no-agent` and must stay free of provider, HTTP, database and trading calls.
  V3 alone did not enable Web writes; later V6 local dark + L2a did under
  separate local authorization (public cutover still OFF).
- V4–V8 M1–M6 details remain dated delivery evidence. The current order is:
  finish the final UI/contract; refresh full/focused suites; seal exact test and
  real-flow artifacts; open the final runtime-bound release stamp/cutover;
  start and verify connector liveness; execute complete browser E2E; then
  re-seal docs and runtime identity. Authoritative status is `docs/README.md`
  plus the active plan.
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

## Safety Rules

- Keep Phase 0/1a read-only or proposal-only unless a plan explicitly says
  otherwise.
- Agent v0.2 development may use final production modules behind dark gates.
  **Public** `chat_write_ready` / public composer stay OFF until V8. Local
  single-user dark enablement may open settings-gated mutation/composer and
  supervised dispatch under the trading kill switch — that is not public cutover
  and not Plan-V6 full-UI acceptance. A fake Hermes adapter is for hermetic
  tests only, never a temporary public user path.
- Migrations 006 through 015 have been applied to live `quantplatform` under
  explicit authorization. Do not re-apply the obsolete `UNIQUE(task_id)`-only
  006 or treat an old replay plan as current. Migration 015 narrows runtime
  managed-session provisioning to exact columns and must fail closed on ACL
  drift. Schema readiness and the constrained-role canary are not public write
  authorization; every future migration still needs separate authorization and
  evidence.
- Treat the local `~/.hermes/hermes-agent` checkout as a third owned dependency
  for v0.2 Durable Run work. Pin source/install/runtime identity and develop in a
  controlled branch/worktree; do not patch an unidentified live checkout in
  place. Platform projections must never counterfeit missing Hermes canonical
  Run/event/provider/approval/stop facts.
- Never bypass `paper_trading`, `live_trading_enabled=false`, `kill_switch`,
  or human approval gates.
- The supported HQA Scene-B path uses three human gates: formula confirmation,
  candidate source approval, and promotion diff review/commit. All three are
  implemented in the HQA wrappers; raw platform APIs/CLI remain generic
  primitives and do not independently prove HQA Gate 1 provenance.
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
  stamp/cutover, connector liveness and browser E2E pass. Official API
  health/capability/session GETs do not call a provider. Do not downgrade to a
  GET-only fallback or claim the release-candidate UI is already public.
- Opportunity decisions never create or upgrade action eligibility. Link an
  action only by exact platform signal/execution IDs validated through the
  bounded observations seam; ticker/symbol similarity is never causal proof.

## Local Commands

- HQA tests: `./.venv/bin/pytest`
- Install Hermes wrappers: `bash scripts/install.sh`
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
