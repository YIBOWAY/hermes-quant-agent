# Candidate Integrity Task 6 Report

**Task:** Dry-run-first legacy root audit and migration  
**Platform branch:** `audit-remediation-2026-06-23`  
**BASE (pre-task HEAD):** `392485ad190020c6179ad1a563a6cacf485f7e6d`  
**Status:** COMPLETE  

## Commit

| SHA | Subject |
|-----|---------|
| `a4252d59a3af6957fe0909215d96bd20122d1f5a` | `feat(agent): add conflict-safe candidate root migration` |

Short: `a4252d5`

**Not pushed** (controller owns platform push).  
**`--apply` not run** on real candidate data (user has not authorized mutation).

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

## What changed

### New module

- `src/quant_system/agent/candidate_migration.py`
  - `audit_candidate_roots(*, legacy_dir, agent_output_dir) -> CandidateMigrationReport` — read-only; opens roots with `create=False`; creates no root/lock/backup/manifest/temp
  - Canonical always `resolve_candidates_dir(resolve_agent_output_dir(...))` (via report agent_output_dir + `resolve_candidates_dir`)
  - Report fields: roots, `copyable` / `identical` / `conflicts` / `canonical_unversioned` / `legacy_unbound`, per-item integrity (`verified` | `migration_required` | `corrupt`), root/candidate identities + digests for drift checks
  - `apply_candidate_migration(report, backup_dir)` refuses when `conflicts` non-empty or source facts/identities drift
  - Legacy→canonical copy: backup first, exclusive staging, decision locks rewritten only in staging as `legacy-*-lock`, rebuild `manifest.v1.json`, `rename_directory_noreplace_at` publish
  - Canonical unversioned: backup complete dir, re-verify under pool lock, move legacy decision locks to unbound evidence, exclusive add of `manifest.v1.json` without changing metadata/artifact bytes
  - Root overlap: planned lexical abspath equality/containment + held `st_dev/st_ino` for existing roots (legacy/canonical/backup must be three distinct non-overlapping trees)
  - No `Path.open` / `Path.mkdir` / `tempfile` / path-based `shutil.copy*` / `os.replace` / overwrite `os.rename` (AST static test)

### CLI

- `agent migrate-candidates` defaults to dry-run JSON
- `--apply` requires `--backup-dir`
- Resolvers: `resolve_legacy_candidates_dir` + `resolve_agent_output_dir` only (no `--candidates-dir` bypass)
- CWD-independent: CLI test chdirs outside repo with `QS_AGENT_OUTPUT_DIR` and observes the same canonical root

### Tests

- `tests/test_candidate_migration.py` (30 tests): conflict no-overwrite, legacy immutability, legacy approval → `legacy_unbound`, unversioned manifest-only versioning, absent-root dry-run empty tree, invalid IDs, mutually exclusive integrity states, 8 root-overlap layouts, identity drift barriers, identical re-run no-op, static bypass scan, CLI dry-run + apply-requires-backup

### Unchanged intentionally

- `src/quant_system/agent/candidate_fs.py` — existing Task-2/3 primitives sufficient; no new bypass surface needed

## Real dry-run (this machine only)

```bash
./ai-quant/bin/quant-system agent migrate-candidates
```

**Result (summarized):**
- `legacy_dir`: `/Users/sunyibo/programs/ai-quant-platform/data/agent/candidates` (**absent**)
- `canonical_dir`: `/Users/sunyibo/programs/ai-quant-platform/data/agent_run/agent/candidates`
- `copyable`: `[]`
- `conflicts`: `[]`
- `identical`: `[]`
- `canonical_unversioned`: `["factor-momentum_20d_reversal-323b045e4b"]`
- `items[0].integrity_state`: `migration_required`
- `items[0].canonical_manifest_digest`: `294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558`
- `applied`: `false`
- Candidate files unchanged: still only `metadata.json` + `factor.py.candidate` (no `manifest.v1.json`)

## Test summary

```bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_migration.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/candidate_migration.py \
  tests/test_candidate_migration.py src/quant_system/cli.py
./ai-quant/bin/quant-system agent migrate-candidates
```

**Result:** 30 passed; ruff clean; dry-run JSON as above.

## Concerns / follow-ups

1. **Real `--apply` still needs explicit user authorization** with a chosen non-overlapping `--backup-dir` (e.g. outside both legacy and canonical trees). Recommended after dry-run review:
   ```bash
   ./ai-quant/bin/quant-system agent migrate-candidates \
     --apply --backup-dir /path/to/safe-backup
   ```
   Expected effect: add `manifest.v1.json` only to `factor-momentum_20d_reversal-323b045e4b` while preserving bytes and pending binding.
2. **HQA wrapper env-inheritance** assertion mentioned in the brief is covered on the platform CLI side (`QS_AGENT_OUTPUT_DIR` + chdir); no HQA code change required for Task 6.
3. **macOS `/var` vs `/private/var`:** audit/apply use lexical `abspath` + dirfd identity; pytest tmp paths are under `/private/var` and pass.
4. **No paper/live, no push, no real candidate mutation.**

## Files in commit (3)

```
src/quant_system/agent/candidate_migration.py  (new)
src/quant_system/cli.py
tests/test_candidate_migration.py              (new)
```

---

## Python review remediation (2026-07-13)

**Review:** `.superpowers/sdd/candidate-task-6-python-review.md` (Needs fixes)  
**Security:** Approved (no change required for this remediation)  
**Status:** HIGH findings fixed; not pushed; no real `--apply`

### Commit

| SHA | Subject |
|-----|---------|
| `1a6f471a39b531c403e774cdf86cc07638c1d43e` | `fix(agent): verify migration backups and root barrier coverage` |

Short: `1a6f471`  
Parent (Task 6 feat): `a4252d59a3af6957fe0909215d96bd20122d1f5a`

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

### Fixes landed

1. **Incomplete backup no longer treated as complete**
   - `_backup_candidate_tree` no longer returns early on name existence alone.
   - New helpers: `_list_regular_payloads`, `_backup_matches_source`, `_stage_verified_backup`.
   - Flow: read source payloads via held FD → if final backup id exists, open and verify exact name/byte set → only then idempotent no-op; incomplete/mismatched trees are removed and replaced via exclusive `.staging-backup-*` + copy + fsync + verify + `rename_directory_noreplace_at` + final held-fd re-verify.
   - Publish still only proceeds after backup path returns (verified complete).

2. **Barrier tests + pre-lock canonical root probe**
   - Added `test_apply_detects_canonical_root_identity_drift` (replace candidates root inode after audit).
   - Added `test_apply_detects_pool_lock_swap_after_audit` (symlink swap of `.candidate-pool.lock`).
   - Added incomplete/complete backup tests.
   - Apply now probes canonical root identity with `create=False` *before* `locked_candidates_root`, so a replaced root fails closed without creating `.candidate-pool.lock`.

3. **Optional extract** — partial only: backup path split into smaller pure/helpers; full apply/publish decomposition deferred (MEDIUM follow-up).

### Tests

```bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_migration.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/candidate_migration.py \
  tests/test_candidate_migration.py
```

**Result:** 34 passed; ruff clean.

### Remaining follow-ups (not blocking this fix)

- MEDIUM items from python review (ExitStack CM style, `legacy_unbound` on canonical, decision-lock rename window, dead code, private imports, macOS `/var` lexical gap).
- Optional further extract of `apply_candidate_migration` / `_publish_from_legacy` into &lt;50-line steps.
- Real `--apply` still requires explicit user authorization after a fresh dry-run JSON review.
