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
  are all delivered. The current implementation/delivery record is
  `docs/superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md`; the full
  9H record is completed historical delivery evidence, not the active queue.
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
  but platform migration 006 is not live-applied; this must not enable claim or
  dispatch. Wave 3D chat remains BLOCKED. Wave
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
