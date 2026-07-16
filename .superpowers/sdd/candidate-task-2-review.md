# Candidate Task 2 Review

**Task:** Dirfd filesystem boundary, candidate identity, and exact-byte manifest  
**Commit:** `1741f748b12c30bb9895174bb4931bb5c362cbb1`  
**Base:** `5c8188a62b395acfab2f47633e28ad25851eb843`  
**Scope:** 3 new files only (`candidate_fs.py`, `candidate_manifest.py`, `test_candidate_manifest.py`)  
**Checks run:** `pytest tests/test_candidate_manifest.py` → 78 passed; `ruff check` on the three files → clean  

**Assessment: Needs fixes**

---

## Spec Compliance

| Requirement | Status |
|---|---|
| Dirfd-only primitives; lexical walk from `/` with `O_DIRECTORY\|O_NOFOLLOW\|O_CLOEXEC` | Met |
| After first split, names + held `dir_fd` only (no `Path.open` / path-string replace for content) | Met in new modules |
| Runtime fail-closed probe for flags / `dir_fd` / `follow_symlinks=False` | Met |
| `read_regular_bytes_at`: regular file + `st_nlink == 1` + post-open identity re-check | Met |
| No-replace rename via macOS `renameatx_np(RENAME_EXCL)` / Linux `renameat2(RENAME_NOREPLACE)`; no overwrite fallback | Met |
| `_validate_candidate_id` / `_normalized_relative_path` / reserved set / casefold collisions | Met (matches brief) |
| Exact-byte digests; canonical JSON; POSIX basename file order | Met |
| Directory basename == `metadata.candidate_id` == stored `manifest.candidate_id` | Met |
| Missing `manifest.v1.json` → `CandidateMigrationRequiredError`; mismatch → corrupt | Met |
| Symlink / hardlink / FIFO / directory artifact rejection tests | Met |
| Barrier-synchronized rename for **both** candidates-root and candidate-dir | Partial — barrier only for candidate-dir; candidates-root covered by same-thread monkeypatch only |
| Held FD identity re-check before snapshot return | Met |
| Approval/legacy controls via same no-follow single-link primitive | Met (read path); binding semantics incomplete (see Important) |
| Write primitives present for Task 3 reuse | Present; untested |
| No pool/CAS/CLI/`--apply`/push scope creep | Met |

Binding constraints (dirfd-only, reject symlink/escape/non-regular, exact-byte digests, ID equality, no Path.open content/control writes in new modules) are substantially implemented. The remaining gaps are fixable defects, not a wrong architecture.

---

## Strengths

1. **Correct security model.** Absolute paths are split lexically (`os.path.abspath`, not `Path.resolve()`), then every component is opened with `O_NOFOLLOW`. That is the right shape for a candidate trust boundary on macOS and Linux.

2. **Single-link regular-file reads.** `read_regular_bytes_at` stats with `follow_symlinks=False`, rejects symlinks/non-regular/`st_nlink != 1`, re-checks dev/ino after open, and detects size change during read. Hardlink-to-outside tests cover metadata, manifest, artifacts, and controls.

3. **Identity contract is tight and shared.** `_validate_candidate_id`, `_normalized_relative_path`, reserved basenames, and casefold duplicate detection match the brief and block path escape / reserved-control-as-artifact cases.

4. **Exact-byte manifest.** `\r\n` preserved, file list sorted by POSIX basename, digest over canonical JSON (`sort_keys=True`, separators `(",", ":")`, `allow_nan=False`). Directory/metadata/stored-manifest ID equality is enforced.

5. **No-replace publish primitives.** ctypes adapters fail closed on unsupported platforms; no silent `os.rename`/`os.replace` fallback. Temp names are random single components with `O_CREAT|O_EXCL`, `fsync(file)`, rename, `fsync(parent)`.

6. **Hostile FS test depth is real.** Symlinked agent-output / agent / candidates / candidate / metadata / manifest / artifact; FIFO and directory artifacts; hardlinks; monkeypatched rename-after-open; barrier swap proving held-FD bytes stay original.

7. **Scope discipline.** Only the three assigned files; Task 3 CAS/pool wiring left alone; dirty tree paths preserved per report.

---

## Issues

### Critical

None that yield replacement/outside bytes on the tested paths. Held-FD reads and identity asserts fail closed under the barrier and monkeypatch swap scenarios.

### Important

```text
[IMPORTANT] FD leak when assert_entry_is_open_fd fails after open_directory_at
File: src/quant_system/agent/candidate_fs.py:405-428
Issue: open_absolute_directory opens next_fd, then calls assert_entry_is_open_fd.
If the assert raises, next_fd is neither stored in intermediate_fds/child_fd nor closed.
Reproduced: 50 forced assert failures → +50 open FDs (delta 50). Under rename races
this is the failure mode the code intends to hit, so the leak is on the hot integrity path
and can exhaust FDs (DoS) during hostility.
Fix: Track every successful open immediately, e.g.:

    next_fd = open_directory_at(parent_fd, name)
    try:
        assert_entry_is_open_fd(parent_fd, name, next_fd)
    except Exception:
        os.close(next_fd)
        raise
    if is_last:
        child_fd = next_fd
        ...
    else:
        intermediate_fds.append(next_fd)
```

```text
[IMPORTANT] Verified snapshot can report approval_binding="approved" with unbound lock
File: src/quant_system/agent/candidate_manifest.py:269-337, 385-397
Issue: _parse_bound_review accepts any 64-char manifest_digest and any candidate_id string.
_approval_binding_at then returns "approved" without requiring:
  - candidate_id == opened candidate / manifest.candidate_id
  - manifest_digest == current verified digest
  - digest is hex [0-9a-f]{64}
Reproduced: approved.lock with digest "0"*64 and candidate_id "factor-other-2" against
a real factor-safe-1 tree → approval_binding == "approved" and review_record.candidate_id
== "factor-other-2" while snapshot.manifest_digest is the real digest.
Consumers that trust approval_binding alone will treat an unbound/wrong lock as authorized.
Full lock write format may be Task 3, but this task defines the verified-read binding API.
Fix: In _approval_binding_at (or _verify_from_opened), only return "approved"/"rejected"
when lock.candidate_id == manifest.candidate_id and lock.manifest_digest == digest
(and digest matches r"^[0-9a-f]{64}$"). Otherwise legacy_unbound (or corrupt if you want
stricter fail-closed on structured-but-wrong locks). Add a regression test.
```

```text
[IMPORTANT] Barrier-synchronized candidates-root rename test missing
File: tests/test_candidate_manifest.py (candidates-root section ~1304; barrier ~1415)
Issue: Brief requires barrier-synchronized rename tests for both the candidates-root
entry and the candidate-directory entry after FDs are opened. Only the candidate
directory has a true two-thread barrier test. candidates-root coverage is a same-thread
monkeypatch of open_directory_at, which never races a concurrent rename against a held
FD and does not prove the "return original bytes OR raise, never replacement" contract
under concurrency for that layer.
Fix: Add a barrier test mirroring test_barrier_candidate_swap_never_returns_replacement_bytes
that opens agent→candidates (or load_verified path), swaps the candidates directory
from another thread, and asserts held-FD reads never return EVIL bytes and identity
mismatch is detected.
```

### Minor

```text
[MINOR] Stored manifest allows unknown fields
File: src/quant_system/agent/candidate_manifest.py:91-98, 371-381
Issue: CandidateManifestV1 uses default Pydantic extra-ignore. A stored manifest with
extra keys validates; comparison is model_dump-canonical, so extras are stripped and
verification succeeds. Pretty-printed stored JSON also passes (canonical re-encode).
That matches "canonical equality" but is weaker than exact-file or forbid-extra.
Fix: model_config = ConfigDict(extra="forbid") on CandidateManifestV1 / digests if
unknown keys should be corrupt.
```

```text
[MINOR] Write/rename primitives have no direct unit tests
File: src/quant_system/agent/candidate_fs.py (write_regular_exclusive_at,
atomic_write_noreplace_at, rename_directory_noreplace_at)
Issue: Task 3 will depend on these. Current suite only exercises open/read/assert paths.
EEXIST→CandidateConflictError, temp cleanup on failed rename, and exclusive create are
unchecked.
Fix: Small tests for exclusive create conflict, atomic no-replace success, and rename
conflict; optional Linux CI note remains fine.
```

```text
[MINOR] macOS EAGAIN mapped to CandidateConflictError; Linux rename path untested here
File: src/quant_system/agent/candidate_fs.py:246-250
Issue: Report already flags this. EAGAIN may not always mean "destination exists";
treating it as conflict is fail-closed for publish but may mis-signal retry vs conflict.
Acceptable for v1 if documented for Task 3 callers.
```

```text
[MINOR] open_absolute_directory post-yield assert skipped on body exception
File: src/quant_system/agent/candidate_fs.py:420-423
Issue: assert after yield runs only on clean exit. Callers that catch integrity errors
inside the with-block rely on their own asserts (load/verify do re-check). Not wrong,
but the context manager does not always fail closed on exit after a partial success path
that swallowed errors. Prefer try/finally around the exit assert if you want
exit-time identity always checked:

    try:
        yield opened
    finally:
        assert_entry_is_open_fd(...)  # or suppress only if fd already invalid
```
(Optional; verify/load already assert before return.)

```text
[MINOR] device/socket non-regular coverage
File: tests/test_candidate_manifest.py
Issue: Brief mentioned device/socket as well as FIFO; FIFO + directory are covered.
Device nodes usually need privileges — acceptable gap if noted.
```

---

## Diagnostic notes (reviewer)

```text
[HIGH] Type hints: public APIs are annotated; no material Any abuse on new surfaces.
[HIGH] Mutable defaults: none (Field(default_factory=dict) used).
[HIGH] Bare except: cleanup `except Exception: close; raise` patterns are acceptable;
      _parse_bound_review `except Exception: return None` is intentional soft-parse →
      legacy_unbound (should tighten with digest/id match as above).
[MEDIUM] No print(); domain errors used; ruff clean.
Security: no SQL/shell/eval; no hardcoded secrets; symlink/hardlink/path escape handled.
```

---

## Assessment

**Needs fixes**

Do not merge as-is for a security boundary module until the **FD leak** and **approval binding** issues are fixed. The barrier test gap for candidates-root should be closed in the same pass so the brief's concurrency contract is fully evidenced.

After fixes, re-run:

```bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_manifest.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_manifest.py tests/test_candidate_manifest.py
```

**Suggested fix order**
1. Close FDs on assert failure in `open_absolute_directory` (and any similar open-then-assert sites).
2. Bind `approved`/`rejected` to matching `candidate_id` + current `manifest_digest`.
3. Add barrier test for candidates-root swap.
4. (Optional) `extra="forbid"` on manifest models; unit tests for write/rename primitives.

Architecture and exact-byte/dirfd approach are sound; this is a fix-forward review, not a redesign.
