# AGENTS.md

Rules for AI agents working in this repository.

## Project Role

- `Hermes-quant-agent` is the active orchestration/COO layer for the local
  `/Users/sunyibo/programs/ai-quant-platform` backend.
- Start at `docs/README.md`; it distinguishes the product roadmap, the current
  cross-repo implementation plan, queued work, and historical material.
- The product roadmap is `docs/design/2026-07-01-roadmap-phases-0b-4.md`.
  The current implementation plan is
  `docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md`; execute only its
  current next slice. Slices 9A through 9G and the read-only mini 9H artifact
  shelf are delivered; full 9H cron/notify is the next slice and remains queued
  until a bite-sized plan is written from current source facts. The platform frontend
  plan is the Slice 0-8
  record and future UI backlog. The 2026-07-07 Phase 1a-4 implementation plan is
  superseded material and must not be followed task-by-task.
- Treat `ai-quant-platform/docs/phases/phase_15_iteration_roadmap.md` as
  reference material only. Do not use it as an independent product roadmap.

## Safety Rules

- Keep Phase 0/1a read-only or proposal-only unless a plan explicitly says
  otherwise.
- Never bypass `paper_trading`, `live_trading_enabled=false`, `kill_switch`,
  or human approval gates.
- Scene-B end-to-end promotion uses three human gates: formula confirmation,
  candidate source approval, and promotion diff review/commit. All three are
  implemented (Gate 3 = platform `agent promote-candidate`, which writes a
  working-tree diff only — never commits; the human `git diff` review + commit
  IS Gate 3).
- HQA may run one-shot research backtests through approved candidates, but
  resident paper/live paths must only use promoted, registered, tested factors.
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
- Do not infer current progress from an old plan's unchecked boxes. Reconcile
  `docs/README.md`, the active plan, git state, tests, and the running process.
- Preserve user and generated changes in the dirty worktree; do not revert
  unrelated files.
- If `.codegraph/` is absent, skip CodeGraph for this repo; the platform repo
  has CodeGraph and can use it for cross-file code questions.
