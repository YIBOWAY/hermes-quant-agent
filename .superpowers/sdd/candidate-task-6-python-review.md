# Candidate Task 6 — Python Quality + Spec Review

**Task:** Dry-run-first legacy root audit and migration  
**Scope:** `candidate_migration.py`, `cli.py` (`migrate-candidates`), `tests/test_candidate_migration.py`  
**Base..HEAD:** `392485ad`..`a4252d5`  
**Checks run:** `pytest tests/test_candidate_migration.py` (30 passed), `ruff check` (clean); mypy not installed in platform venv  
**Assessment: Needs fixes**

---

## Summary

The migration design is largely sound and matches the brief’s safety model: dry-run is create=False/read-only, apply is dual-gated (`--apply` + `--backup-dir`), roots are checked for planned-path overlap and held-FD identity, publish uses exclusive staging + `rename_directory_noreplace_at`, legacy trees are never mutated, and legacy decisions become unbound evidence rather than authority. Tests cover the four core brief scenarios, invalid IDs, integrity states, eight root-overlap layouts, two identity-drift barriers, CLI dry-run/env root, and an AST path-bypass scan.

However, a few **HIGH** correctness/spec gaps block approval: incomplete-backup idempotency without re-verification, missing barrier tests the brief explicitly requires, and several oversized apply helpers that bury the safety sequence.

---

## Findings

### [HIGH] Incomplete backup treated as complete on retry
File: `src/quant_system/agent/candidate_migration.py:517-519`
Issue: `_backup_candidate_tree` returns early if `backup/<bucket>/<candidate_id>` already exists, without comparing entry names/bytes/digests to the held source FD. A crash after `mkdir_exclusive_at` and mid-`_copy_regular_entries` leaves a partial tree; a later apply skips re-backup and can still publish. Spec requires a complete, fsynced backup before canonical publication.
Fix: Always stage backup under an exclusive temp name (e.g. `.staging-backup-*`), copy + fsync, verify file set/bytes (or digest) against source, then `rename_directory_noreplace_at` into the final backup id. If final id exists, re-open and verify completeness; only then treat as idempotent no-op—or replace via a verified staging rename path that never overwrites an existing final id without matching content.

### [HIGH] Barrier tests incomplete vs brief
File: `tests/test_candidate_migration.py` (identity drift section ~379-423)
Issue: Brief requires barrier tests that replace **legacy root, canonical root, pool lock, or canonical candidate entry** after open. Present: legacy root replace, canonical *candidate* replace. Missing: **canonical root** identity drift and **pool lock** swap/replace after open/audit. Spec also says apply must detect identity drift and leave replacement/outside trees unchanged.
Fix: Add tests that (1) replace the canonical candidates root directory after audit (new inode), (2) replace/swap `.candidate-pool.lock` after audit/open, assert `CandidateIntegrityError`/`CandidateMigrationConflict`, no manifest/publish, and fingerprint equality for legacy + replacement trees.

### [HIGH] Oversized safety-critical functions
File: `src/quant_system/agent/candidate_migration.py`
Issue: Several public/core helpers exceed the 50-line review threshold and mix validation, IO, and control flow:
- `apply_candidate_migration` ~163 lines
- `_publish_from_legacy` ~137 lines
- `audit_candidate_roots` ~119 lines
- `_version_canonical_unversioned` ~98 lines
- `_observe_candidate` ~95 lines
This makes the “backup → re-verify → stage → publish” sequence harder to audit and easier to regress.
Fix: Extract pure helpers, e.g. `_open_legacy_if_needed`, `_assert_root_identities`, `_classify_merged_items`, `_stage_and_publish_candidate`, `_migrate_decision_locks_to_unbound`, keeping apply as an ordered checklist of named steps.

### [MEDIUM] Manual context-manager enter/exit for legacy root
File: `src/quant_system/agent/candidate_migration.py:830-931`
Issue: `legacy_cm = open_absolute_directory(...); legacy_root = legacy_cm.__enter__()` with hand-rolled `except`/`finally` `__exit__` is brittle (easy to double-exit, mask errors, or skip cleanup on future edits). Cleanup uses broad `except Exception` before re-raise.
Fix: Use `contextlib.ExitStack`: `stack.enter_context(open_absolute_directory(...))` under the backup `with`, and let ExitStack own teardown. Catch only the integrity/conflict types expected at that boundary.

### [MEDIUM] `_scan_root` return type lies
File: `src/quant_system/agent/candidate_migration.py:329-346`
Issue: Signature promises `OpenedDirectory | None` as the first tuple element, but always returns `None` (scan closes the CM before return). Call sites immediately `del` the value. Dead API surface / misleading types.
Fix: Return `tuple[dict[str, CandidateMigrationItem], tuple[int, int] | None]` only.

### [MEDIUM] `legacy_unbound` only observed on the legacy root
File: `src/quant_system/agent/candidate_migration.py:421-447`
Issue: Unbound/legacy decision detection re-opens **legacy** only. Canonical-only unversioned candidates that still carry `approved.lock` / `rejected.lock` (or already `legacy-*.lock`) never appear in `report.legacy_unbound`, even though apply will rewrite them to unbound evidence. Report field is incomplete for the machine’s real dry-run case (canonical_unversioned).
Fix: During the initial `_observe_candidate` / classification pass (or a single re-open of each present root), record decision-lock presence on both sides into `legacy_unbound` when binding would be non-authoritative.

### [MEDIUM] Decision-lock “rename” is copy+unlink (crash window)
File: `src/quant_system/agent/candidate_migration.py:747-758`
Issue: Unversioned path writes `legacy-*.lock` then unlinks `approved.lock`/`rejected.lock`. Crash between steps leaves both; authority stays non-granting (good—binding code treats multi-control / unbound locks as `legacy_unbound`), but tree is dirty and not the intended single evidence file. Also if `legacy-approved.lock` already exists, the branch skips and leaves `approved.lock` in place.
Fix: Prefer same-dirfd exclusive create of evidence + unlink of authority name under the pool lock, then re-read controls and fail closed if more than one decision name remains before writing `manifest.v1.json`. Document the intentional non-atomic rename constraint if primitives forbid `renameat` for files.

### [MEDIUM] Backup/source decision-name collision when both lock forms exist
File: `src/quant_system/agent/candidate_migration.py:489-499`
Issue: With `rename_decisions=True`, `approved.lock` is rewritten as `legacy-approved.lock`. If the source already contains both `approved.lock` and `legacy-approved.lock`, the second exclusive write fails mid-stage. Fail-closed is correct, but classification could mark such trees `corrupt` at audit time instead of `copyable`.
Fix: In `_observe_candidate` / pre-copy validation, if more than one decision lock name is present (or both authority + legacy forms), mark `corrupt` or exclude from `copyable` with an explicit error code.

### [MEDIUM] Private cross-module imports
File: `src/quant_system/agent/candidate_migration.py:33-38`
Issue: Depends on `_build_manifest_from_opened`, `_validate_candidate_id`, `_verify_from_opened` (underscore-private). Acceptable short-term for dirfd reuse; fragile if manifest internals move.
Fix: Re-export stable held-fd helpers from `candidate_manifest` / `candidate_fs` public API (or a small `candidate_io` façade) used by pool + migration.

### [MEDIUM] Dead / noisy control flow
File: `src/quant_system/agent/candidate_migration.py:245-247, 266, 290-295, 308`
Issue: No-op `if snapshot.approval_binding == "legacy_unbound": pass`; `del manifest`; unreachable branch in `_merge_items` (`verified and verified` inside a `migration_required` arm); `locations=locations  # type: ignore[arg-type]`.
Fix: Delete dead code; type `locations` as `list[Literal["legacy", "canonical"]]` via a small helper that preserves the literal union.

### [MEDIUM] macOS `/var` vs `/private/var` lexical overlap gap
File: `src/quant_system/agent/candidate_migration.py:104-117` (and report note)
Issue: Overlap uses `os.path.abspath` parts, not open-FD identity, for absent backup paths. Distinct lexical forms of the same directory can bypass planned-path checks; existing roots are still caught by `st_dev/st_ino`. Residual risk mainly for not-yet-created backup vs existing trees via aliased paths.
Fix: After opening/creating backup, always compare backup identity to legacy/canonical identities (already done when those are open). For pre-create checks, also compare `Path.resolve()` only when `strict=False` and document no-symlink policy—or require backup parent to exist and open it for identity comparison before create.

### [LOW] CLI apply error path is good; message is free-form
File: `src/quant_system/cli.py` (`agent_migrate_candidates`)
Issue: Refusals print `migration_refused reason=...` and exit 1; dry-run JSON is clean. Fine for operators; not structured JSON on failure.
Fix: Optional: emit JSON `{"applied": false, "error": ...}` for machine consumers. Non-blocking.

### [LOW] Brief listed `candidate_fs.py` as modify; intentionally unchanged
File: report “Unchanged intentionally”
Issue: Acceptable if Task 2/3 primitives already cover exclusive writes/renames (they do). No new bypass surface is a plus.
Fix: None required; keep report note.

---

## Spec checklist

| Requirement | Status |
|---|---|
| `audit_candidate_roots` read-only; canonical via `resolve_candidates_dir(resolve_agent_output_dir(...))` | **Met** (audit uses agent_output → `resolve_candidates_dir`; create=False) |
| Report: copyable / identical / conflicts / canonical_unversioned / legacy_unbound + integrity states | **Mostly met** (`legacy_unbound` legacy-root-only; see MEDIUM) |
| Apply refuses conflicts / source fact drift | **Met** |
| Unversioned: manifest only; no metadata/artifact byte change; no authority grant | **Met** (tests) |
| CLI dry-run default; `--apply` requires `--backup-dir`; no `--candidates-dir` | **Met** |
| Dry-run creates no root/lock/backup/manifest/temp | **Met** (test + real dry-run) |
| Invalid IDs never copied | **Met** |
| Three distinct non-overlapping roots (planned + FD) | **Met** (8 layout tests) |
| Backup complete + fsync before publish | **Gap** (idempotent skip without verify) |
| Publish via noreplace dirfd primitives; no Path.open/mkdir/tempfile/shutil.copy/os.replace/os.rename | **Met** (AST test + source review) |
| Barrier tests: legacy root, canonical root, pool lock, candidate entry | **Partial** (legacy root + candidate only) |
| Identical re-run no-op | **Met** |
| Real dry-run only; no real `--apply` | **Met** (per report) |
| HQA wrapper env inheritance | **Out of platform commit** (CLI chdir + `QS_AGENT_OUTPUT_DIR` covered) |

---

## Security / error-handling notes (no CRITICAL)

- No SQL/shell/`eval`/`yaml.load`/hardcoded secrets.
- Path traversal: candidate names pass `_validate_candidate_id`; roots walked with O_NOFOLLOW primitives from Task 2/3.
- Symlinks in candidate trees rejected on copy (`S_ISLNK` → integrity error).
- Exceptions are mostly specific (`CandidateIntegrityError`, `CandidateMigrationConflict`); remaining broad `except Exception` is re-raise-after-cleanup only.
- Resources use context managers for roots; per-candidate FDs closed in `finally`.
- Approval path preserves evidence without granting authority (`legacy_unbound` / non-binding locks).

---

## What looks strong

- Conflict fail-closed and no-overwrite publish path.
- Legacy fingerprint immutability on success and failure (tested).
- Staging name uses `secrets.token_hex`; exclusive mkdir; digest re-check before and after stage.
- Static AST guard against the brief’s forbidden bypasses.
- CLI refuses apply without backup; CWD-independent canonical root via env resolver.
- Real machine dry-run left the pending candidate without `manifest.v1.json` (good operational discipline).

---

## Approval criteria

| Level | Result |
|---|---|
| CRITICAL | None |
| HIGH | 3 (incomplete backup skip; missing barrier tests; oversized core functions) |
| MEDIUM | Several (CM style, legacy_unbound coverage, dead code, private imports, lock rename window) |

**Assessment: Needs fixes**

### Minimum fix set to re-review toward Approve

1. Make backup creation verify-complete (or exclusive staging + verify) before any canonical mutation; never trust a pre-existing backup dir by name alone.
2. Add canonical-root and pool-lock identity-drift barrier tests (and implement detection if anything is missing).
3. Optionally extract apply/publish helpers so the safety sequence is reviewable in &lt;50-line steps (can be same PR or immediate follow-up if 1–2 land first).

Do **not** run real `--apply` until after fixes and a fresh dry-run JSON review.
