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
  are all delivered. The current delivery record is
  `docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md`.
  D-31 wave status (2026-07-14 evidence): Hermes gateway capability contract is
  delivered with chat still fail-closed; candidate integrity and scoped Gate 3
  are code-delivered on the platform; HQA Scene-B persists an exact-source
  Gate 1 confirmation and binds it to the candidate manifest before its Gate 2
  CAS caller can approve; the professional frontend/read-only shell is delivered.
  Real Hermes chat/provider evidence, Hermes approval mutations, unified results,
  and legacy-page retirement remain intentionally blocked. Do not infer work from
  an older plan or backlog. The platform frontend plan is the Slice 0-8
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
  authorizes. Real migration remains dry-run until separately authorized.
- HQA may run one-shot research backtests through digest-reverified approved
  candidates, but resident paper/live paths must only use promoted, registered,
  tested factors. The delivered Hermes workbench remains read-only; its approval
  mutation stays disabled until a separately approved bridge/approval slice lands.
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
