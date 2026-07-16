# Candidate Integrity Task 7 Report

**Task:** Persistent isolated Gate 3 worktree and scoped patch  
**Platform branch:** `audit-remediation-2026-06-23`  
**BASE (pre-task HEAD):** `1a6f471a39b531c403e774cdf86cc07638c1d43e`  
**Status:** COMPLETE  

## Commit

| SHA | Subject |
|-----|---------|
| `ae191bee4fbf63a6a391624bd62958046af8858c` | `feat(agent): prepare Gate 3 diffs in isolated review worktrees` |

Short: `ae191be`

**Not pushed** (controller owns platform push).

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

## What changed

### New module

- `src/quant_system/agent/promotion_workspace.py`
  - `prepare_promotion_workspace(...)` — verifies base==main HEAD, re-verifies approved candidate via `CandidatePool`, refuses dirty scoped paths (allows unrelated main dirty), exclusive promotion-root lock, detached `git worktree add`, pure materializer inside worktree, `--intent-to-add` for new files only, canonical `--binary --full-index` scoped patch, internal replay worktree apply+byte/digest check, immutable `manifest.v1.json` + mutable `state.json`, deterministic `promotion_id`
  - `promotion_status` / `cleanup_promotion_workspace` — promotion-id only; state is untrusted; bind promotion_id/manifest digest/repo identity/managed-root identity/direct-child worktree/git worktree registration; reviewed-commit requires clean worktree, one commit beyond base, named local branch, exact three-path set, blob digests, candidate re-verify, and `BASE..HEAD` patch byte equality (not empty worktree diff)
  - Default cleanup requires durable reviewed evidence; `--abandon` force-removes worktree and retains audit state `abandoned`
  - No branch/commit/push/merge; Git only via argument arrays + `shell=False`
  - Managed worktree root: `tempfile.gettempdir()/ai-quant-platform-gate3-worktrees` (overrideable via kwargs / `resolve_managed_worktree_root`)
  - Promotion records: `resolve_agent_output_dir()/agent/promotions/{promotion_id}/`

### CLI

- `agent promote-candidate` exact contract: required `--candidate-id`, `--expected-digest`, `--base-commit` only
  - stdout: JSON `{promotion_id, worktree, patch, manifest}`
  - stderr: human next steps (named branch `codex/promotion-{id}`, scoped stage/commit)
- `agent promotion-status --promotion-id`
- `agent cleanup-promotion --promotion-id [--abandon]`
- No public library/tests/repo/worktree/agent-output path options; no `promote_candidate(` call in `cli.py`

### Pure materializer

- `promote.py` remains git/process-free internal materializer; docstring updated to state public Gate 3 is the workspace orchestrator

### Tests

- `tests/test_promotion_workspace.py` (43 tests): isolation vs main dirty, candidate drift, base mismatch, scoped collision/dirty, idempotency, deterministic patch/manifest across roots, three-path patch replay, status commit-range patch, tamper rejection, uncommitted/detached cleanup refusal, named-branch cleanup, abandon audit retain, 16 state-injection refuse cases (default + abandon), invalid promotion IDs, CLI help/missing-option exit 2, CLI success JSON, AST no materializer call
- `tests/test_agent_promote.py` CLI tests updated for prepare-only public contract

## Test summary

```bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_promote.py \
  tests/test_promotion_workspace.py \
  tests/test_agent_promotion.py
./ai-quant/bin/python -m ruff check \
  src/quant_system/agent/promote.py \
  src/quant_system/agent/promotion_workspace.py \
  tests/test_promotion_workspace.py
./ai-quant/bin/quant-system agent promote-candidate --help
./ai-quant/bin/quant-system agent promotion-status --help
./ai-quant/bin/quant-system agent cleanup-promotion --help
```

**Result:** 95 passed; ruff clean; help contracts match required options only; `grep promote_candidate(` on `cli.py` finds no materializer call.

## Concerns

- Managed worktree root is process-temp-dir based (`/var/folders/...` on macOS). Durable across reboots only if the OS temp root retains it; operators should cleanup or abandon after review. Acceptable for local Gate 3; production hardening could pin a cache path later without changing the public CLI.
- Status/cleanup tests inject via explicit kwargs; production CLI always uses fixed `resolve_platform_repo()` + `resolve_managed_worktree_root()` + resolver agent root (no path overrides).
- Idempotent prepare requires the existing managed worktree to still be present; if an operator manually deletes only the worktree, re-prepare of the same facts refuses until abandon/manual state repair.
