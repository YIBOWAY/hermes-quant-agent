# Candidate Integrity Task 2 Report

**Task:** Dirfd filesystem boundary, candidate identity, and exact-byte manifest  
**Platform branch:** `audit-remediation-2026-06-23`  
**BASE:** `5c8188a62b395acfab2f47633e28ad25851eb843`  
**Status:** COMPLETE  

## Commit

| SHA | Subject |
|-----|---------|
| `1741f748b12c30bb9895174bb4931bb5c362cbb1` | `feat(agent): bind candidates through a safe exact-byte filesystem boundary` |

Short: `1741f74`

**Not pushed** (controller owns platform push).

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

## What changed

### New modules

- `src/quant_system/agent/candidate_fs.py`
  - Domain errors: `CandidateIntegrityError`, `CandidateConflictError`
  - Runtime fail-closed probe for `O_NOFOLLOW` / `O_DIRECTORY` / `O_CLOEXEC` / `dir_fd` / `follow_symlinks=False`
  - `OpenedDirectory` + `open_absolute_directory` (lexical walk from `/`)
  - `open_directory_at`, `assert_entry_is_open_fd`, `read_regular_bytes_at` (`st_nlink == 1`, regular file only)
  - `write_regular_exclusive_at`, `atomic_write_noreplace_at`, `rename_directory_noreplace_at`
  - No-replace rename via macOS `renameatx_np(RENAME_EXCL)` / Linux `renameat2(RENAME_NOREPLACE)` ctypes adapter (no overwrite fallback)

- `src/quant_system/agent/candidate_manifest.py`
  - Shared identity: `_validate_candidate_id`, `_normalized_relative_path`, `_RESERVED_CANDIDATE_COMPONENTS`, casefold collisions
  - `canonical_json_bytes`, `CandidateFileDigest`, `CandidateManifestV1`, `VerifiedCandidateSnapshot`
  - `build_candidate_manifest` — exact metadata/artifact bytes, POSIX basename file order, SHA-256 digest of canonical manifest JSON
  - `verify_candidate_directory` / `load_verified_candidate_snapshot` — stored `manifest.v1.json` equality; missing → `CandidateMigrationRequiredError`; hardlink/symlink/type/id mismatch → corrupt
  - Approval binding read via same no-follow single-link primitive (`pending` / structured bound / `legacy_unbound`)

- `tests/test_candidate_manifest.py`
  - Identity, exact-byte sort/digest, ID mismatch
  - Unsafe/reserved artifact paths, casefold duplicates, reserved controls
  - Symlinked agent-output / agent / candidates / candidate / metadata / manifest / artifact
  - FIFO/directory non-regular artifacts
  - Hardlink-to-outside for metadata, manifest, artifacts, and approval/legacy controls
  - Barrier and monkeypatched rename-after-open tests (never returns replacement bytes)
  - Migration-required vs verified snapshot load through agent root

## Test summary

```bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_manifest.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_manifest.py tests/test_candidate_manifest.py
```

**Result:** 78 passed; ruff clean.

Contracts verified:
- Candidate IDs are lowercase single non-reserved components
- Manifest binds exact bytes (`\r\n` preserved) and sorts POSIX basenames
- Directory / metadata / stored-manifest `candidate_id` equality
- Symlinks, hardlinks (`st_nlink != 1`), FIFO/dir artifacts rejected
- Held-FD identity re-check after open; rename/swap never yields replacement bytes
- Missing `manifest.v1.json` → migration_required; matching stored manifest → verified snapshot with artifact_bytes

## Concerns / follow-ups

1. **Task 3 owns repository CAS** — pool lock, atomic publish, review CAS, and wiring of `CandidatePool` / SafetyGate / CLI not done here (as required).
2. **Structured approved.lock schema** is only partially recognized for binding (`schema_version` + 64-char digest); full lock write/format is Task 3.
3. **`VerifiedCandidateSnapshot.candidate_dir` is retained for path display** but consumers must use `artifact_bytes` only; no enforcement beyond docs/types yet.
4. **macOS `renameatx_np` EAGAIN** is mapped to conflict alongside EEXIST; Linux path untested on this host.
5. **No real candidate data mutation**, no `--apply`, no paper/live, no push.

## Files in commit (3)

```
src/quant_system/agent/candidate_fs.py       (new)
src/quant_system/agent/candidate_manifest.py (new)
tests/test_candidate_manifest.py            (new)
```

---

## Review fix-forward (Important findings)

**Review:** `.superpowers/sdd/candidate-task-2-review.md`  
**Status:** FIXED (Important blockers)

### Fix commit

| SHA | Subject |
|-----|---------|
| `cb4d7e0f06352cc6a52a3320f2c3478fe5fb1803` | `fix(agent): harden candidate dirfd and approval binding` |

Short: `cb4d7e0`  
**Base for this fix:** `1741f748b12c30bb9895174bb4931bb5c362cbb1`  
**Not pushed.**

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

### Fixes applied

1. **FD leak** (`candidate_fs.open_absolute_directory`): after `open_directory_at`, if `assert_entry_is_open_fd` fails, close `next_fd` before re-raising so rename-race assert failures cannot exhaust FDs.

2. **Approval binding** (`candidate_manifest._approval_binding_at` / `_parse_bound_review`):
   - Digest must match `^[0-9a-f]{64}$` (lowercase hex only).
   - `approved` / `rejected` only when lock `candidate_id == manifest.candidate_id` and lock `manifest_digest ==` current verified digest.
   - Wrong ID, zero/stale digest, uppercase hex, or unstructured payload → `legacy_unbound` (never authorize).

3. **Barrier candidates-root test:** `test_barrier_candidates_root_swap_never_returns_replacement_bytes` — two-thread barrier swap of the `candidates` directory after held FDs are open; held-FD reads stay original (`Z\r\n`), never `EVIL-ROOT-BARRIER`; identity mismatch detected.

4. **Regression:** `test_approved_lock_requires_matching_id_and_digest` covers unbound/wrong-id/stale/uppercase and matching authorize path.

### Re-test

```bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_manifest.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_manifest.py tests/test_candidate_manifest.py
```

**Result:** 80 passed; ruff clean.

### Remaining concerns (unchanged / still optional)

- Minor review items not required this pass: `extra="forbid"` on manifest models; unit tests for write/rename primitives; macOS EAGAIN→conflict mapping documentation for Task 3.
- Task 3 still owns CAS/pool/CLI lock write path.
