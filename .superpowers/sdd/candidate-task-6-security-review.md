# Security Review: Candidate Task 6 (Dry-run-first migration)

**Reviewer role:** Security Reviewer (read-only)  
**Scope:** `392485ad190020c6179ad1a563a6cacf485f7e6d` → `a4252d59a3af6957fe0909215d96bd20122d1f5a`  
**Platform commit:** `a4252d5` — `feat(agent): add conflict-safe candidate root migration`  
**Files:** `candidate_migration.py` (new), `cli.py`, `tests/test_candidate_migration.py` (new)  
**Date:** 2026-07-13  

## Verdict

**Assessment: Approved**

All five critical checks pass. No CRITICAL or HIGH findings. Residual MEDIUM/LOW notes do not block merge of this dry-run-first migration surface; real `--apply` on production candidate data still requires separate human authorization.

## Critical checks

| Check | Result | Evidence |
|-------|--------|----------|
| Dry-run creates nothing | **PASS** | `audit_candidate_roots` opens roots only via `open_absolute_directory(..., create=False)`; never calls `locked_candidates_root`, backup create, staging, or manifest write. `test_dry_run_against_absent_roots_leaves_tmp_empty` asserts byte-empty `tmp_path`. CLI dry-run test asserts no `manifest.v1.json`. Live tree still only `metadata.json` + `factor.py.candidate` (no manifest). |
| Path escape + root overlap rejection | **PASS** | Every listed name goes through `_validate_candidate_id` before open/copy; invalid IDs → `corrupt`, never `copyable`. Planned-path `_paths_overlap` on legacy/canonical/(backup); held `st_dev`/`st_ino` collision checks after open. Eight overlap layouts tested; path-escape IDs parametrized. Dirfd primitives enforce single-component + `O_NOFOLLOW`. |
| `--apply` not default; backup required | **PASS** | CLI `apply: bool = False` (`--apply` opt-in). `if apply` and `backup_dir is None` → `typer.BadParameter`. `test_migrate_candidates_cli_apply_requires_backup_dir` expects non-zero exit. No `--candidates-dir` bypass; resolvers only. |
| dirfd for apply writes | **PASS** | Apply mutates only via Task-2/3 primitives: `write_regular_exclusive_at`, `mkdir_exclusive_at`, `rename_directory_noreplace_at`, `read_regular_bytes_at`, `remove_entry_tree_at`, `locked_candidates_root`. AST static test forbids `Path.open`/`Path.mkdir`/`tempfile`/`shutil.copy*`/`os.replace`/`os.rename`. Grep of migration module: no bypass imports. |
| No real candidate mutation in tests; no real `--apply` | **PASS** | All apply tests use pytest `tmp_path` only. Report states `--apply` not run on real data. Verified on disk: `data/agent_run/agent/candidates/factor-momentum_20d_reversal-323b045e4b/` still has only the two pre-migration files (mtime Jul 1). Tests: 30 passed. |

## OWASP / threat-oriented review

### Injection / path traversal

- Candidate directory names from `os.listdir(dir_fd)` only; never concatenated into absolute path strings for writes.
- `_validate_candidate_id` rejects empty, `.`/`..`, `/` `\`, absolute, non-`[a-z0-9][a-z0-9_-]*`, and reserved control names.
- File ops use `_validate_single_component` + `dir_fd` + `O_NOFOLLOW` / `O_EXCL`.
- No shell, SQL, or template evaluation.

### Broken access / approval authority

- Legacy `approved.lock` / `rejected.lock` rewritten only in staging as `legacy-*-lock` (`rename_decisions=True`).
- Canonical unversioned path moves decision locks to unbound evidence (copy exclusive + unlink) before adding manifest.
- `approval_binding` authorizes only digest-bound structured locks; `legacy_*` never grants `approved`/`rejected` authority.
- Conflict path refuses apply when digests differ; no overwrite of existing canonical bytes (`rename_directory_noreplace_at` / exclusive creates).
- Tests: conflict no-overwrite, legacy approval → `legacy_unbound`, unversioned preserves pending + artifact/metadata bytes.

### Sensitive data / secrets

- No hardcoded secrets, tokens, or credentials in the diff.
- CLI echoes JSON report (paths, digests, integrity states) — appropriate for operator audit tool; no password/PII fields.

### Misconfiguration / defaults

- Default command path is **audit-only dry-run**.
- Apply requires explicit `--apply` **and** `--backup-dir`.
- Canonical always `resolve_candidates_dir(resolve_agent_output_dir(...))`; report `canonical_dir` re-checked against agent output on apply.
- CWD-independent: env `QS_AGENT_OUTPUT_DIR` + chdir CLI test.

### Race / TOCTOU

- Apply re-checks root and per-candidate `st_dev`/`st_ino` and manifest digests under pool lock before copy/version.
- Publish re-asserts source identity and staged digest immediately before `rename_directory_noreplace_at`.
- Drift tests: replaced legacy root and replaced canonical candidate leave outside trees unchanged and block writes.

### Known dependency / logging

- No new dependencies.
- Failures surface as `migration_refused reason=...` without stack secrets.

## Residual findings (non-blocking)

### MEDIUM — Backup early-return may retain stale bytes on re-apply

**Location:** `_backup_candidate_tree` — if `backup/{bucket}/{candidate_id}` already exists, function returns without re-copy or content compare.

**Impact:** If a prior partial apply wrote a backup, then source *file bytes* change under the **same directory inode**, a fresh audit (new digest) + apply will re-verify and publish the **new** source correctly, but leave the **old** backup. Weakens disaster-recovery fidelity of “backup first,” not live canonical integrity (digest barriers still protect publish).

**Recommendation (follow-up, not merge-block):** On existing backup dir, re-read and compare expected digests/file set, or write to a unique run-id subdirectory, or refuse with explicit “stale backup” error.

### LOW — Backup root created before full legacy/canonical FD identity checks

Planned-path overlap is validated first; then `open_absolute_directory(backup, create=True)` may create an empty backup tree before legacy/canonical identity collision fails. Candidates are not mutated; operator may see an empty backup dir after a refused apply.

### LOW — Brief-listed barrier coverage incomplete in tests

Identity drift tests cover legacy root replace and canonical **candidate** replace. Explicit post-open **pool lock** swap and whole **canonical root** replace barriers are not dedicated tests (primitives re-assert lock/root identity under `locked_candidates_root` / `assert_entry_is_open_fd`).

### LOW / operational — Operator-controlled roots

`--legacy-dir`, `--agent-output-dir`, and especially `--backup-dir` are local-admin paths. Process can create directories where the OS user can write. Acceptable for a non-networked operator CLI; not a remote attack surface. No silent default write path.

### INFO — Symlink canonical root at audit

If planned canonical path is a symlink, `_path_is_dir_nofollow` treats it absent (audit may list legacy as `copyable`). Apply then fails closed on `O_NOFOLLOW` open/create of that component. Misleading audit classification only; no write through symlink.

## Critical-check detail

### 1. Dry-run creates nothing

```text
audit_candidate_roots
  → _scan_root → open_absolute_directory(path, create=False)
  → optional re-open for legacy_unbound lock presence (create=False, read-only stats)
  → returns CandidateMigrationReport(applied=False)
```

No backup, pool lock, staging, or `manifest.v1.json` creation on the audit path. Confirmed by empty-tmp test, CLI dry-run test, and live candidate listing.

### 2. Path escape + root overlap

- Lexical: component-wise `Path.parts` equality/containment (not string-prefix).
- Identity: `(st_dev, st_ino)` for existing opened roots; backup vs legacy/canonical after open.
- Escape: invalid IDs never enter `copyable`; publish/version always re-validate ID.

### 3. Apply gating

```python
apply: Annotated[bool, typer.Option("--apply", ...)] = False
...
if apply:
    if backup_dir is None:
        raise typer.BadParameter("--backup-dir is required with --apply")
```

Empty action sets (`copyable` and `canonical_unversioned` both empty) short-circuit apply without creating backup/canonical roots.

### 4. dirfd-only mutation surface

Apply write graph:

1. Backup via exclusive mkdir + exclusive regular writes under held backup dirfd  
2. Legacy→canonical: exclusive staging under pool-locked canonical dirfd → rebuild manifest → `rename_directory_noreplace_at`  
3. Unversioned: exclusive manifest create; decision lock rename via exclusive write + `os.unlink(..., dir_fd=)`  

Static AST guard + absence of path-based copy/replace APIs.

### 5. Real-data hygiene

| Control | Status |
|---------|--------|
| Tests confined to `tmp_path` | Yes |
| Real `--apply` in commit/workflow | No (report + commit message) |
| Live unversioned candidate mutated | No (still 2 files, Jul 1 mtimes) |
| Paper/live / promotion gates touched | No |

## Test security coverage (relevant)

- Conflict no-overwrite  
- Legacy tree fingerprint immutability  
- Approval → evidence only (`legacy_unbound`)  
- Unversioned manifest-only versioning  
- Absent-root dry-run empty  
- Invalid IDs without writes  
- Mutually exclusive integrity states  
- 8 root-overlap layouts fail closed  
- Legacy root + canonical candidate identity drift  
- Identical re-run no-op  
- Static bypass scan  
- CLI dry-run env root + apply-requires-backup  

## Safety alignment (Hermes / platform rules)

- No paper/live trading path, kill-switch, or promotion gate bypass.  
- Migration does **not** grant action eligibility or bound approval from legacy locks.  
- Scene-B human gates unchanged.  
- Stop-before-real-apply honored.

## Residual risk acceptance

| ID | Severity | Block merge? |
|----|----------|--------------|
| Stale backup early-return | MEDIUM | No — recovery fidelity; publish still digest-gated |
| Backup dir created on later refuse | LOW | No |
| Missing pool-lock/root barrier tests | LOW | No |
| Operator path choice | LOW/ops | No |

## Pre-real-apply checklist (operator)

1. Run dry-run JSON; review `copyable`, `conflicts`, `canonical_unversioned`, digests.  
2. Choose `--backup-dir` **outside** legacy and canonical trees (and not nested).  
3. Explicit user authorization before:
   ```bash
   ./ai-quant/bin/quant-system agent migrate-candidates \
     --apply --backup-dir /path/to/safe-backup
   ```
4. Re-audit after apply; confirm expected manifests only; no unexpected approvals.

## Summary

Task 6 implements a fail-closed, dry-run-default migration with dirfd-only applies, conflict no-overwrite, legacy immutability, and approval demotion to unbound evidence. Critical security requirements for this slice are met. Address stale-backup early-return in a follow-up if backup byte-fidelity under re-apply is required as a hard guarantee.

---

**Assessment: Approved**
