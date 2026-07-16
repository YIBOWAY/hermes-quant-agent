# Candidate Task 6 — Python Re-review (post HIGH fixes)

**Task:** Dry-run-first legacy root audit and migration  
**Scope:** Remediation commit `1a6f471` on top of feat `a4252d5`  
**Base..HEAD:** `392485ad`..`1a6f471`  
**Prior review:** `.superpowers/sdd/candidate-task-6-python-review.md` (Needs fixes)  
**Prior blocking HIGH:** incomplete backup trust; missing canonical-root / pool-lock barriers  
**Checks run:** `pytest tests/test_candidate_migration.py` (**34 passed**), `ruff check` (clean); bandit/mypy not installed in platform venv  
**Assessment: Approved**

---

## Summary

The two correctness HIGHs that blocked the first review are fixed and covered by tests.

1. **Backup completeness** — `_backup_candidate_tree` no longer treats a pre-existing backup directory as complete by name alone. Source payloads are read through the held FD; an existing final id is opened and byte/name-set verified via `_backup_matches_source`; only an exact match is an idempotent no-op. Incomplete/mismatched trees are removed and replaced through exclusive `.staging-backup-*` staging, copy, fsync, staged verify, `rename_directory_noreplace_at`, and a final held-fd re-verify before callers may publish.

2. **Barrier coverage** — Brief-required identity-drift barriers now include **legacy root**, **canonical candidate entry**, **canonical candidates root**, and **pool lock** (symlink swap). Apply also probes canonical root identity with `create=False` *before* `locked_candidates_root`, so a replaced root fails closed without creating `.candidate-pool.lock`. Pool-lock symlink rejection is enforced by Task-2 `O_NOFOLLOW` + regular single-link checks in `locked_candidates_root`.

The third prior HIGH (oversized apply/publish helpers) remains as a **non-blocking maintainability follow-up** — the first review’s minimum fix set treated extraction as optional once backup verify + barriers landed, and the remediation report correctly deferred full decomposition.

No new CRITICAL or HIGH correctness issues found in the remediation.

---

## Prior HIGH disposition

| Prior HIGH | Status | Evidence |
|---|---|---|
| Incomplete backup treated as complete on retry | **Fixed** | `_list_regular_payloads` / `_backup_matches_source` / `_stage_verified_backup`; early name-only return removed; tests `test_incomplete_backup_is_not_treated_as_complete`, `test_complete_matching_backup_is_idempotent_noop_for_backup` |
| Barrier tests missing canonical root + pool lock | **Fixed** | `test_apply_detects_canonical_root_identity_drift`, `test_apply_detects_pool_lock_swap_after_audit`; pre-lock identity probe in `apply_candidate_migration` |
| Oversized safety-critical functions | **Deferred (non-blocking)** | Partial helper extract only; `apply_candidate_migration` ~192, `_publish_from_legacy` ~137, `audit_candidate_roots` ~119 still above 50-line threshold — tracked as MEDIUM follow-up |

---

## Findings (this re-review)

### [MEDIUM] Oversized apply/publish helpers (deferred from prior HIGH)
File: `src/quant_system/agent/candidate_migration.py`
Issue: Core apply path is still long multi-phase control flow (`apply_candidate_migration` ~192 lines, `_publish_from_legacy` ~137, `_version_canonical_unversioned` ~98, `audit_candidate_roots` ~119). Backup path extraction improved reviewability of the prior bug, but the full “open roots → re-verify → backup → stage → publish” checklist is still harder to audit than named &lt;50-line steps.
Fix: Extract ordered pure/IO steps (`_open_legacy_if_needed`, `_assert_root_identities`, `_stage_and_publish_candidate`, etc.) in a follow-up; not required to re-block this remediation.

### [MEDIUM] Remaining items unchanged from first review
File: `src/quant_system/agent/candidate_migration.py` (various)
Issue: Still present and non-blocking for this re-review:
- Manual `legacy_cm.__enter__` / `__exit__` instead of `ExitStack`
- `_scan_root` return type carries a always-`None` opened handle
- `legacy_unbound` observed primarily on the legacy root
- Decision-lock “rename” is copy+unlink (dirty crash window; authority stays non-granting)
- Multi decision-lock forms not classified `corrupt` at audit
- Private cross-module imports (`_build_manifest_from_opened`, etc.)
- Dead/noisy control flow (`pass` branches, `# type: ignore`)
- macOS `/var` vs `/private/var` lexical planned-path gap for absent backups
Fix: Same as first review; none re-introduced regressions in the fix commit.

### No new CRITICAL / HIGH

- No SQL/shell/`eval`/unsafe YAML/hardcoded secrets.
- No return-to-name-only backup trust.
- Incomplete backup restage still uses exclusive dirfd primitives; publish remains after verified backup.
- Tests assert legacy fingerprint immutability and no manifest on barrier failure.

---

## Spec checklist (re-check)

| Requirement | Status |
|---|---|
| Backup complete + fsync + verify before publish; never trust name-only existing backup | **Met** |
| Barrier tests: legacy root, canonical root, pool lock, candidate entry | **Met** |
| Apply detects identity drift; leaves replacement/outside trees unchanged | **Met** (tests) |
| Pre-lock fail-closed on replaced canonical root (no spurious pool lock create) | **Met** |
| Dry-run read-only; `--apply` + `--backup-dir`; no path bypasses | **Met** (unchanged; AST test still present) |
| Conflicts refuse overwrite; legacy never mutated | **Met** |
| Identical re-run no-op | **Met** |
| Real `--apply` not run without user auth | **Met** (per report) |

---

## Test / tool results

```text
./ai-quant/bin/python -m pytest -q tests/test_candidate_migration.py
# 34 passed

./ai-quant/bin/python -m ruff check \
  src/quant_system/agent/candidate_migration.py \
  tests/test_candidate_migration.py
# All checks passed
```

New coverage added by remediation:
- incomplete backup restage + successful publish
- complete matching backup reused without rewrite
- canonical root inode replace after audit
- pool lock symlink swap after audit

---

## Approval criteria

| Level | Result |
|---|---|
| CRITICAL | None |
| HIGH (blocking correctness) | **None remaining** — prior backup + barrier HIGHs fixed |
| MEDIUM | Deferred size extract + first-review residuals |

**Assessment: Approved**

### Operational note

Do **not** run real `--apply` until the user authorizes mutation after a fresh dry-run JSON review and a non-overlapping `--backup-dir` outside legacy and canonical trees.
