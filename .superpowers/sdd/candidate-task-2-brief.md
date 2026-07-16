### Task 2: Dirfd filesystem boundary, candidate identity, and exact-byte manifest

**Files:**

- Create: <code>src/quant_system/agent/candidate_fs.py</code>
- Create: <code>src/quant_system/agent/candidate_manifest.py</code>
- Create: <code>tests/test_candidate_manifest.py</code>

**Interfaces:**

- Produces the manifest/snapshot interfaces defined above plus shared dirfd primitives used unchanged by repository write/review and migration.
- All filesystem trust starts by lexically splitting an absolute path and opening every component from <code>/</code> with <code>O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC</code>. After that first split, candidate filesystem code uses names plus held <code>dir_fd</code>s only—never <code>Path.open()</code>, <code>Path.mkdir()</code>, <code>tempfile</code> with a path-string directory, path-based <code>os.replace()</code>, or a re-resolved pathname.
- <code>_validate_candidate_id</code> is the only candidate-ID validator. Creation, <code>get</code>, review, API detail, <code>SafetyGate</code>, CLI, migration, and promotion all call it before filesystem access.
- V1 candidate IDs are lowercase canonical ASCII single components. Artifact/control names are canonical ASCII single components and are compared by <code>casefold()</code> for duplicate/reserved collisions so the contract is identical on case-sensitive Linux and the supported default case-insensitive macOS filesystem. Nested IDs/artifacts are deliberately rejected so every metadata/artifact/control operation is relative to one held directory FD; a later schema version is required before nesting.
- A verified snapshot proves <code>candidate directory basename == metadata.candidate_id == manifest.candidate_id</code> and carries the exact verified artifact bytes. Later code never reopens the source via <code>snapshot.candidate_dir / name</code>.
- Manifest JSON is canonical UTF-8 with sorted keys and separators <code>(",", ":")</code>; file list order is explicit POSIX basename order.

- [ ] **Step 1: Write failing identity, exact-byte, and hostile-filesystem tests**

~~~python
from __future__ import annotations

import json
import os

import pytest

from quant_system.agent.candidate_manifest import (
    CandidateIntegrityError,
    _validate_candidate_id,
    build_candidate_manifest,
    canonical_json_bytes,
)


def _candidate(root):
    root.mkdir()
    metadata = {
        "candidate_id": root.name,
        "artifact_type": "factor",
        "goal": "safe",
        "universe": ["SPY"],
        "files": ["z.py.candidate", "a.json"],
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2), encoding="utf-8"
    )
    (root / "z.py.candidate").write_bytes(b"Z\r\n")
    (root / "a.json").write_bytes(b"{\"a\":1}\n")
    return metadata


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        ".",
        "..",
        "../escape",
        "../../escape",
        "/tmp/escape",
        "nested/id",
        r"nested\id",
        " leading",
        "trailing ",
        "metadata.json",
        "manifest.v1.json",
        "UPPERCASE-ID",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
    ],
)
def test_candidate_id_is_one_canonical_nonreserved_component(bad_id) -> None:
    with pytest.raises(CandidateIntegrityError):
        _validate_candidate_id(bad_id)


def test_manifest_binds_exact_bytes_and_sorts_posix_paths(tmp_path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)

    manifest, digest, artifact_bytes = build_candidate_manifest(candidate)

    assert manifest.candidate_id == candidate.name
    assert [item.path for item in manifest.files] == ["a.json", "z.py.candidate"]
    assert manifest.files[1].size_bytes == 3
    assert artifact_bytes["z.py.candidate"] == b"Z\r\n"
    assert digest == __import__("hashlib").sha256(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    ).hexdigest()


def test_directory_metadata_and_stored_manifest_ids_must_match(tmp_path) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    metadata["candidate_id"] = "factor-other-2"
    (candidate / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CandidateIntegrityError, match="candidate_id"):
        build_candidate_manifest(candidate)
~~~

Retain the existing unsafe metadata-file-path cases and add separate tests for duplicate basenames, absolute/<code>..</code>/slash/backslash paths, every reserved control basename, a symlinked agent-output root, symlinked <code>agent</code> or <code>candidates</code> root, symlinked candidate directory, symlinked <code>metadata.json</code>/<code>manifest.v1.json</code>/artifact, and FIFO/device/socket/non-regular files. Add a stored-manifest test where directory and metadata agree but <code>manifest.candidate_id</code> differs.

Add case-insensitive collision tests: <code>Approved.lock</code> is reserved, <code>Metadata.json</code>/<code>MANIFEST.V1.JSON</code> are reserved, and metadata listing both <code>A.py</code> and <code>a.py</code> is corrupt even on a case-sensitive test filesystem. Add hardlink-to-outside tests for <code>metadata.json</code>, <code>manifest.v1.json</code>, every artifact, and approval/rejection/legacy control; safe reads require <code>st_nlink == 1</code>, so legacy hardlinks are <code>corrupt</code> and outside bytes are never accepted.

Use barrier-synchronized rename tests for both the candidates-root entry and candidate-directory entry after their FDs are opened. Each test must prove the read either returns bytes from the held original inode or raises <code>CandidateIntegrityError</code>; it must never read replacement/outside bytes. Assert held/opened directory <code>st_dev/st_ino</code> still matches its parent's current no-follow entry before a snapshot is returned.

- [ ] **Step 2: Run and confirm RED**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_candidate_manifest.py</code>

Expected: both new modules fail to import.

- [ ] **Step 3: Implement the shared dirfd boundary and strict manifest construction**

Define the shared identity rules exactly:

~~~python
_SAFE_CANDIDATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_RESERVED_CANDIDATE_COMPONENTS = frozenset(
    {
        "metadata.json",
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
    }
)


def _validate_candidate_id(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or PurePosixPath(value).is_absolute()
        or _SAFE_CANDIDATE_ID.fullmatch(value) is None
        or value in _RESERVED_CANDIDATE_COMPONENTS
    ):
        raise CandidateIntegrityError("candidate_id is not a canonical component")
    return value


def _normalized_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or len(path.parts) != 1
        or str(path) != value
        or not value.isascii()
        or path.name.casefold()
        in {name.casefold() for name in _RESERVED_CANDIDATE_COMPONENTS}
    ):
        raise CandidateIntegrityError("candidate file path is not canonical")
    return path


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
~~~

In <code>candidate_fs.py</code>, require <code>os.O_NOFOLLOW</code>, <code>os.O_DIRECTORY</code>, <code>dir_fd</code>, and <code>follow_symlinks=False</code> support at import/first use; fail closed on any unsupported runtime. Implement these primitives and use no path-string mutation behind them:

~~~python
@dataclass
class OpenedDirectory:
    fd: int
    parent_fd: int
    name: str
    st_dev: int
    st_ino: int


@contextmanager
def open_absolute_directory(path: Path, *, create: bool) -> Iterator[OpenedDirectory]: ...

def open_directory_at(parent_fd: int, name: str) -> int: ...
def read_regular_bytes_at(parent_fd: int, name: str) -> bytes: ...
def assert_entry_is_open_fd(parent_fd: int, name: str, opened_fd: int) -> None: ...
def write_regular_exclusive_at(parent_fd: int, name: str, payload: bytes) -> None: ...
def atomic_write_noreplace_at(parent_fd: int, name: str, payload: bytes) -> None: ...
def rename_directory_noreplace_at(
    source_parent_fd: int, source_name: str, destination_parent_fd: int, destination_name: str
) -> None: ...
~~~

<code>open_absolute_directory</code> starts with an FD for <code>/</code>, then opens or creates one lexical component at a time relative to the held parent. Creation uses <code>os.mkdir(component, dir_fd=parent_fd)</code>, handles an <code>EEXIST</code> race by no-follow opening the entry, and verifies <code>fstat</code> is a directory. <code>read_regular_bytes_at</code> uses <code>O_RDONLY | O_NOFOLLOW | O_CLOEXEC</code>, then requires regular-file <code>fstat</code> and <code>st_nlink == 1</code> before reading. Every temporary/control file uses a random single-component name, <code>O_CREAT | O_EXCL | O_NOFOLLOW</code>, <code>fsync(file)</code>, no-replace rename relative to the same held parent FD, and <code>fsync(parent_fd)</code>.

Implement no-replace rename explicitly with Linux <code>renameat2(..., RENAME_NOREPLACE)</code> and macOS <code>renameatx_np(..., RENAME_EXCL)</code> via a small <code>ctypes</code> adapter; map <code>EEXIST</code> to the domain conflict and fail closed on other platforms. Do not silently fall back to overwrite-capable <code>os.rename</code>/<code>os.replace</code>.

Build a candidate manifest only from exact <code>metadata.json</code> bytes and the ordered single-component files named by metadata, all read relative to a held candidate FD. Validate the directory entry through <code>_validate_candidate_id</code>; require directory/metadata ID equality before building. Reject any artifact whose casefolded name is duplicated or collides with a casefolded reserved control name. For verified reads, parse stored <code>manifest.v1.json</code>, require its ID equality, rebuild from current exact bytes, and require canonical manifest bytes and digest equality. Read approval/legacy controls through the same no-follow, single-link regular-file primitive. Return the already-read artifact bytes in <code>VerifiedCandidateSnapshot</code>; preview, compile, and materialization consumers use those bytes only.

The same builder may compute non-authoritative observed evidence for a safely read unversioned candidate; missing <code>manifest.v1.json</code> alone means <code>migration_required</code>, while any identity/path/type/byte mismatch means <code>corrupt</code>.

- [ ] **Step 4: Run manifest tests and static checks**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_manifest.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_manifest.py tests/test_candidate_manifest.py
~~~

Expected: all pass, including root/candidate swap and identity-mismatch cases.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_manifest.py tests/test_candidate_manifest.py
git commit -m "feat(agent): bind candidates through a safe exact-byte filesystem boundary"
~~~

---

