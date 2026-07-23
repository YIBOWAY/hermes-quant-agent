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
  D-31 status (2026-07-16 evidence): the old TUI gateway contract has drifted and
  is fail-closed; the official API Server session-read contract and platform
  server-side GET-only BFF are delivered for real session list/detail/messages.
  Candidate integrity is delivered, one authorized migration apply completed,
  and Scene-B completed Gate 1, Gate 2, Futu final receipt, human Gate 3 commit
  `524e791`, registry promotion, and cleanup. The professional frontend/read-only
  shell is delivered. Browser Gate 2 mutation was rolled back because refetching
  digest/status violated Gate 1 binding/no-refetch. Wave 3A and 3B are DONE;
  3B's ledger has delivered claim/lease/heartbeat primitives; 3C's runnable worker
  has delivered only notify/periodic-scan/expired-lease reconciliation and does not
  claim queued commands, with zero Hermes mutation/provider use. 3C.1's HQA
  Task/Attempt/payload authority, exact binding, and reverse audit are code-accepted,
  but platform migration 006 is not live-applied. A 2026-07-16 review found its
  `UNIQUE(task_id)` cardinality incompatible with multi-Attempt research; do
  not authorize or apply the current 006. D-32 selects revising never-live 006
  and redoing its full evidence; the current replay-all runner cannot safely use
  a later 007 as a patch. First freeze the v0.2 cardinality, disable implicit startup
  migration, and repeat isolated PostgreSQL/independent review. None of this may
  enable claim or dispatch.
- Slice V0 is source/formal DONE: the three-repo identity manifest, validation
  binding and independent `CLEAR` verdict are closed in
  `docs/audits/2026-07-19-v0-v2-release-closure.md`. The verdict explicitly has
  `release_authorized=false`. V1 code remediation is accepted, but live V1.2
  role/RLS remains PARTIAL: migration 006 is absent and `quant` is still
  superuser/bypassrls. V2 `DurableRunAuthority` source is accepted and pushed at
  Hermes integration `2eb5fa27790f`; it is not installed in the live upstream
  Hermes runtime, so Durable Run and every write gate remain OFF.
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
- **V4–V6 / L2a / L2b (2026-07-21…22) status for agents:** V4 live schema ACCEPT
  (006/007). V5 dark claim/dispatch ACCEPT (CLI default still `reconcile_only`).
  V6 local dark enablement ACCEPT (real HTTP adapter + local mutation flags).
  L2a-Send M1+M2 ACCEPT (composite submit-turn → store → worker → Hermes
  `L2a-pong`). L2b-Observe M1+M2 ACCEPT (command snapshot/follow + messages
  preview after deliver). L3a-Transcript M1 ACCEPT (workbench Conversation
  canvas + live `L3a-pong` bubbles). L3b-Transcript-Polish M1 ACCEPT
  (no-flicker refresh, soft stick scroll, optimistic user bubble, shared
  canvas). L4a-Task-Drawer M1 ACCEPT (read-only command Activity from
  workspace `commands[]`; Task/Attempt authority still empty). L4b-SSE-Follow
  M1 ACCEPT (shared follow spine: BFF SSE + FE EventSource/poll; Activity
  consumes spine; no assistant bodies). L5a-Hermes-Approval-Observe M1 ACCEPT
  (honest empty command-approval slot + Composer on shared spine; no
  allow/deny write; ≠ Gate 1/2/3). L5b-Authority-Projection M1 ACCEPT
  (honest empty Task/Attempt/Run/result slots + health on spine; no invented
  HQA rows). L5c-Workbench-A11y M1 ACCEPT (FE-only shell a11y contracts (region landmark, not nested main);
  marker `l5c-m1`). **V7a–V7g-B-M5 ACCEPT** (exact allow_once|deny CAS + hermetic respond_approval release/signal + hermetic Run-scoped stop with §5.5 layered receipt + durable approval projector + Domain Gate 1/2/3 surfaces + typed results on spine + Vertical A options bind hermetic fixture + authorized live Futu RO thin overlay + Vertical B hermetic factor bind + plan-confirm + Gate1 seed + Gate1 confirm dual-path + Gate2 seed cascade → cascade_stage=gate2_seeded + pending Gate2; gate_cascade_locked stays; sample/real fail-closed; no always-allow; Gates ≠ command-approval ≠ results; no Task invention from conversation.turn; no dual private poll; no catalog-on-spine; zero orders; kill_switch true; StartResearch/global ConfirmResearchPlan still dark; no auto Gate2 decide; M5 ≠ M6 auth). Plan-V6-Token-Stream-M1 ACCEPT@5788379 (SSE transcript hints-only + spine-refetch messages BFF; no bodies on follow; no provider-token passthrough). V8-M1 prep ACCEPT (docs/audits/2026-07-23-v8-m1-adversarial-acceptance-prep.md). V8-M2 hermetic suite close ACCEPT_WITH_NITS@f5d41f4 (GAP-02/08/09/11 COVERED; 01/03/07/13 PARTIAL). V8-M3 cold-start/backup-restore ACCEPT@b570f94 (GAP-14 COVERED; GAP-04 PARTIAL lite; GAP-12 DEFERRED). V8-M4 CLEAR_WITH_NITS (docs/audits/2026-07-23-v8-m4-independent-clear.md; G4 357p/5sk+271p+51; release_authorized=false). V8-M5 hermetic canary grant ACCEPT@bb67fa3 (G5/G6). V8-M6 hermetic public flag G7/G8 ACCEPT@a2953cb (public_cutovers on spine; open requires G6 acceptance; close retains facts; rails honesty; standing default OFF; GAP-17 COVERED hermetic). M6 Gate2 decide unauthorized; release_authorized=false; kill_switch true; M6 ≠ full V8 release.
  Authoritative status: `docs/README.md` + active plan; L2a ADR
  `docs/design/2026-07-22-l2a-send-thin-write-rail-adr.md`.
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
- Migration 006 was revised (Scheme A) and **live-applied 2026-07-21** with 007
  on `quantplatform` after explicit authorization. Do not re-apply obsolete
  `UNIQUE(task_id)`-only 006. Schema readiness is not write authorization.
  Additive L2a migration `008_l2a_conversation_turn_claim.sql` enables
  `conversation_turn` claim alongside research binding — apply only with
  explicit live auth and evidence.
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
    requires platform status to return the same provenance. A timeout is an
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
  tested factors. The delivered Hermes workbench remains read-only. Official API
  health/capability/session GETs do not call a provider. Chat/run and approval
  mutation stay disabled until durable recovery/evidence contracts and a
  separately approved slice land.
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
