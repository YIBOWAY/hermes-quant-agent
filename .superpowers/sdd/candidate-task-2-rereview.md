# Candidate Task 2 Re-Review

**Task:** Dirfd filesystem boundary, candidate identity, and exact-byte manifest  
**Commits:** `1741f74` (feat) + `cb4d7e0` (fix)  
**HEAD:** `cb4d7e0f06352cc6a52a3320f2c3478fe5fb1803`  
**Base:** `5c8188a62b395acfab2f47633e28ad25851eb843`  
**Prior review:** `.superpowers/sdd/candidate-task-2-review.md` → Needs fixes  
**Updated report:** `.superpowers/sdd/candidate-task-2-report.md`  
**Scope:** same 3 files (`candidate_fs.py`, `candidate_manifest.py`, `test_candidate_manifest.py`)  
**Checks run:** `pytest tests/test_candidate_manifest.py` → 80 passed; `ruff check` on the three files → clean  

**Assessment: Approved**

---

## Spec Compliance

| Requirement | Status |
|---|---|
| Dirfd-only primitives; lexical walk from `/` with `O_DIRECTORY\|O_NOFOLLOW\|O_CLOEXEC` | Met |
| After first split, names + held `dir_fd` only | Met |
| Runtime fail-closed probe for flags / `dir_fd` / `follow_symlinks=False` | Met |
| `read_regular_bytes_at`: regular file + `st_nlink == 1` + post-open identity re-check | Met |
| No-replace rename (macOS `renameatx_np` / Linux `renameat2`); no overwrite fallback | Met |
| `_validate_candidate_id` / `_normalized_relative_path` / reserved set / casefold | Met |
| Exact-byte digests; canonical JSON; POSIX basename file order | Met |
| Directory basename == `metadata.candidate_id` == stored `manifest.candidate_id` | Met |
| Missing `manifest.v1.json` → migration_required; mismatch → corrupt | Met |
| Symlink / hardlink / FIFO / directory artifact rejection tests | Met |
| Barrier-synchronized rename for **both** candidates-root and candidate-dir | **Met** (fixed) |
| Held FD identity re-check before snapshot return | Met |
| Approval/legacy controls via no-follow single-link primitive; bind only when ID+digest match | **Met** (fixed) |
| Write primitives present for Task 3 reuse | Present; still untested (Minor, optional) |
| No pool/CAS/CLI/`--apply`/push scope creep | Met |

All binding constraints from the brief are now met for this task's scope.

---

## Prior Important findings — verification

### 1. FD leak when `assert_entry_is_open_fd` fails — FIXED

**Where:** `candidate_fs.open_absolute_directory` (`cb4d7e0`)

```python
next_fd = open_directory_at(parent_fd, name)
try:
    assert_entry_is_open_fd(parent_fd, name, next_fd)
except Exception:
    with suppress(OSError):
        os.close(next_fd)
    raise
```

- Matches the suggested fix shape.
- Successful opens still land in `child_fd` / `intermediate_fds` and are closed in the outer `finally`.
- Reproduced: 50 forced `assert_entry_is_open_fd` failures → **FD delta 0** (was +50 before).

### 2. `approval_binding="approved"` without binding — FIXED

**Where:** `candidate_manifest._parse_bound_review` / `_approval_binding_at` / `_verify_from_opened`

| Check | Behavior after fix |
|---|---|
| Digest format | `^[0-9a-f]{64}$` only (`_HEX_DIGEST`); uppercase/`len==64` alone rejected |
| ID match | `parsed[0].candidate_id == candidate_id` (from verified manifest) |
| Digest match | `parsed[1] == manifest_digest` (current verified digest) |
| Unbound / wrong / unstructured | `legacy_unbound`, `review_record is None` — never authorize |
| Matching lock | `approved` / `rejected` with structured `ReviewRecord` |

Call site always passes verified identity:

```python
binding, review_record = _approval_binding_at(
    opened.fd,
    candidate_id=manifest.candidate_id,
    manifest_digest=digest,
)
```

Regression: `test_approved_lock_requires_matching_id_and_digest` covers wrong-id+zero-digest, stale digest, uppercase hex, and matching authorize path. **Passed.**

### 3. Barrier-synchronized candidates-root rename test — FIXED

**Where:** `test_barrier_candidates_root_swap_never_returns_replacement_bytes`

- Two-thread `threading.Barrier` after `agent` and `candidates` FDs are opened.
- Swapper renames original candidates root out and replacement root in.
- Reader asserts held-FD `z.py.candidate` bytes stay original (`Z\r\n`), never `EVIL-ROOT-BARRIER`.
- Identity mismatch on `assert_entry_is_open_fd(agent_fd, "candidates", candidates_fd)` (or exit assert) is required.
- Path-visible replacement still exists (proves the swap happened). **Passed.**

Together with existing `test_barrier_candidate_swap_never_returns_replacement_bytes`, the brief's concurrency contract is fully evidenced for both layers.

---

## Remaining issues

### Critical

None.

### Important

None remaining from the prior review. No new Important defects found in the fix commit.

### Minor (unchanged, optional — not blocking)

```text
[MINOR] Stored manifest allows unknown fields
File: src/quant_system/agent/candidate_manifest.py
Issue: CandidateManifestV1 default extra-ignore; extras stripped by model_dump-canonical compare.
Fix (optional): ConfigDict(extra="forbid") if unknown keys should be corrupt.
```

```text
[MINOR] Write/rename primitives have no direct unit tests
File: src/quant_system/agent/candidate_fs.py
Issue: Task 3 depends on write_regular_exclusive_at / atomic_write_noreplace_at /
rename_directory_noreplace_at; suite still read-path heavy.
Fix (optional): exclusive-create conflict, atomic no-replace success, rename conflict tests.
```

```text
[MINOR] macOS EAGAIN mapped to CandidateConflictError; Linux rename path untested here
File: src/quant_system/agent/candidate_fs.py
Issue: Fail-closed for publish; document for Task 3 callers (retry vs conflict).
```

```text
[MINOR] open_absolute_directory post-yield assert skipped on body exception
File: src/quant_system/agent/candidate_fs.py
Issue: Exit identity assert only on clean yield exit; verify/load re-check before return.
Optional try/finally hardening.
```

```text
[MINOR] device/socket non-regular coverage
File: tests/test_candidate_manifest.py
Issue: FIFO + directory covered; device nodes usually need privileges — acceptable gap.
```

---

## Diagnostic notes

```text
Security: FD leak closed; approval authorize path bound to ID+digest; barrier proves
          held-FD reads never return replacement bytes at candidates-root layer.
[HIGH] Type hints: public APIs annotated; _parse_bound_review return type updated.
[HIGH] No mutable defaults; no bare-except swallow of integrity failures on authorize path.
[MEDIUM] ruff clean; no print(); domain errors retained.
Scope: fix commit touches only the three Task 2 files; no CAS/pool/CLI/`--apply`.
```

---

## Assessment: Approved

All three prior **Important** blockers are fixed and regression-covered:

1. Assert-failure path closes `next_fd` (FD delta 0 under forced failures).
2. `approved`/`rejected` require matching `candidate_id` + current lowercase-hex `manifest_digest`.
3. Barrier test covers candidates-root concurrent rename; held-FD path never returns `EVIL-ROOT-BARRIER`.

**80 tests passed; ruff clean.** Remaining items are optional Minors (extra=forbid, write-primitive unit tests, EAGAIN docs) suitable for Task 3 follow-up — not merge blockers for this security-boundary module.

Task 2 is ready to accept.
