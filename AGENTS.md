# AGENTS.md

Rules for AI agents working in this repository.

## Project Role

- `Hermes-quant-agent` is the active orchestration/COO layer for the local
  `/Users/sunyibo/programs/ai-quant-platform` backend.
- The single active roadmap is
  `docs/design/2026-07-01-roadmap-phases-0b-4.md`; Phase 1a-3 (close-the-loop,
  incl. `agent promote-candidate` Gate-3 + anti-overfit guardrails) and D-25
  (latency triple: read-only pre-authorization, HQA skill card, async notify
  + artifact-first) are delivered. The next build slice is
  `docs/superpowers/plans/2026-07-07-phase-1a-4-research-employees.md`
  (research-employee expansion: missed-opportunity tracker, portfolio risk
  daily, market-foresight + prediction ledger).
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

## Local Commands

- HQA tests: `./.venv/bin/pytest`
- Install Hermes wrappers: `bash scripts/install.sh`
- Platform CLI path used by wrappers:
  `/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system`

## Collaboration

- Prefer docs/plans first, then implementation.
- Preserve user and generated changes in the dirty worktree; do not revert
  unrelated files.
- If `.codegraph/` is absent, skip CodeGraph for this repo; the platform repo
  has CodeGraph and can use it for cross-file code questions.
