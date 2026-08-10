# Git branch consolidation — 2026-08-10

## Decision

Use `codex/agent-v0-2-release@10a2402b4559` as the consolidation base because
the installed HQA wrappers and clean runtime HQA clone both execute that line.
Publish the accepted result as the repository's first remote `main`; `main`, not
a dated `codex/*` branch, is the sole forward development line.

This is repository governance only. It does not change trading, migration,
candidate, human-gate, connector, or public-release authorization.

## Pre-mutation runtime check

- Runtime HQA clone:
  `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent`
  was clean on `codex/agent-v0-2-release@10a2402b4559`.
- Runtime Platform clone:
  `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform`
  was on its own repository's `codex/agent-v0-2-release@f3b346babddd`, contained
  the separate full-stack remediation worktree changes, and continued to own the
  backend, frontend, and connector processes. Its Git state is outside this
  consolidation and was not changed.

## Recovery anchors

Every pre-consolidation head is retained by a pushed annotated tag:

- `archive/pre-consolidation-main-20260810`
- `archive/pre-consolidation-full-9h-20260810`
- `archive/pre-consolidation-agent-v0-2-release-20260810`
- `archive/pre-consolidation-preserve-paper-research-wip-20260810`
- `archive/pre-consolidation-v4-v7-remediation-20260810`
- `archive/pre-consolidation-phase-1a4-9g-20260810`
- `archive/pre-consolidation-agent-v0-2-limited-device-20260810`

The complete local Git bundle is
`/Users/sunyibo/programs/.git-backups/Hermes-quant-agent-pre-consolidation-20260810.bundle`;
`git bundle verify` reports a complete history.

## Salvage audit

| Source | Decision | Evidence |
|---|---|---|
| local `main@d6179fd` | Migrate | The one unique Quark integration design was cherry-picked as `8c8ac1b`. |
| `codex/full-9h` eight unique commits | Archive, do not replay | The capability series pins Hermes 0.19.0 rather than the current controlled runtime; the test-only commit globally replaces `shutil.rmtree` and conditionally skips socket tests; dated ops/docs snapshots are superseded. The v0.3 drafts remain reachable through the archive tag. |
| `codex/v4-v7-remediation` | Archive, do not replay | One commit is patch-equivalent to release. Durable Run, prompt isolation, Gate 1/3 provenance, final receipt recovery, error redaction, and linked-worktree support are present in later, larger release implementations and tests. |
| `codex/preserve-paper-research-wip-20260809@76b552f` | No replay required | The updater implementation, wrapper, runbook, and core tests have byte-identical blobs in release commit `f71feb0`; the release then added further CLI/test hardening. |
| `103b4f5` | No replay required | Patch-equivalent updater hardening is already on release. |
| `ded8ee1` | Archive only | It explicitly preserves an unfinished paper-research attestation migration and is not an accepted forward change. |
| `codex/phase-1a4-9g` and remote limited-device | Retire | Both have zero commits outside `codex/full-9h`; recovery tags retain their exact heads. |

## Publication and verification gate

Before changing the GitHub default branch or deleting any branch:

1. run the complete HQA test suite from the isolated consolidation worktree;
2. require a clean index and `git diff --check`;
3. publish the accepted consolidation commit as remote `main`;
4. switch the clean runtime HQA clone to the exact accepted `main`, reinstall
   wrappers, and verify the persistent stack without changing the Platform
   checkout;
5. only then retire the old remote branches.

The archive tags and bundle are recovery evidence, not release authorization.

## Consolidation validation result

- The isolated consolidation worktree differs from release source only by the
  Quark design and this branch-governance documentation.
- Full HQA pytest completed with `2163 passed, 4 skipped, 2 failed`. The only
  failures were the already-known live approval grant waits:
  `test_approval_single_use_and_digest_mismatch` and
  `test_expired_grant_rejected_without_consuming`.
- Running those same two tests directly in the untouched
  `codex/agent-v0-2-release@10a2402b4559` worktree produced the same failures
  after the same 45-second grant waits. They are a pre-existing runtime/test
  blocker, not a consolidation regression.
- The consolidation is therefore acceptable for branch-topology convergence
  with no new source failure. It must not be described as a fully green HQA
  release, and the approval flake remains open after publication.
