"""Content-addressed Git repository recovery packages and restore drills."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit

_ADMIN_FILES = (
    "ORIG_HEAD",
    "FETCH_HEAD",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "BISECT_HEAD",
    "AUTO_MERGE",
    "MERGE_AUTOSTASH",
    "MERGE_MSG",
    "MERGE_MODE",
    "COMMIT_EDITMSG",
    "SQUASH_MSG",
)
_INDEX_NAME = "recovery-files.json"
_PACKAGE_FILES = (
    "bundle.bundle",
    "identity.json",
    "index.bin",
    "tracked-worktree.tar",
    "untracked-worktree.tar",
)
_CLOSURE_PACKAGE_FILES = (
    "identity.json",
    "refs.txt",
    "pseudo-refs.txt",
    "status-v2-z.bin",
    "index.bin",
    "index-stages.txt",
    "staged.patch",
    "unstaged.patch",
    "untracked.tar",
    "worktree-list.txt",
    "submodules.txt",
    "bundle.bundle",
    "restore-receipt.json",
)
_HEX_OBJECT = re.compile(rb"(?<![0-9a-f])(?:[0-9a-f]{40}|[0-9a-f]{64})(?![0-9a-f])")
_MAX_DELIBERATE_EXCLUSIONS = 100_000
_MAX_UNTRACKED_FILES = 100_000
_MAX_UNTRACKED_BYTES = 4 * 1024 * 1024 * 1024
_MAX_REHEARSAL_FILES = 100_000
_MAX_REHEARSAL_BYTES = 4 * 1024 * 1024 * 1024
_CLOSED_REBUILD_PROJECTS = {
    "hqa": {
        "distribution_name": "hermes-quant-agent",
        "import_name": "hqa",
        "source_package": "hqa",
    },
    "platform": {
        "distribution_name": "quant-system",
        "import_name": "quant_system",
        "source_package": "src/quant_system",
    },
}
_CLOSED_REBUILD_SCHEMA = "hqa.repository-closed-rebuild.v2"
_CLOSED_REBUILD_ROOT = ".venv"
_CLOSED_REBUILD_PROJECT = ".venv/rebuild-project"
_CLOSED_REBUILD_ENVIRONMENT = ".venv/runtime"
_CLOSED_REBUILD_VIRTUALENV_PTH = b"import _virtualenv"
_CLOSED_REBUILD_COMMAND_TIMEOUT_SECONDS = 600
_CLOSED_REBUILD_PROBE_TIMEOUT_SECONDS = 60
_SANDBOX_PREFLIGHT_TIMEOUT_SECONDS = 15
_TIMEOUT_TERM_GRACE_SECONDS = 5
_UV_EXECUTABLE = Path("/opt/homebrew/bin/uv")
_CLOSURE_IDENTITY_COMPARISON_FIELDS = (
    "admin_files",
    "config",
    "head_object_id",
    "head_symbolic_ref",
    "index",
    "object_format",
    "refs",
    "required_objects",
    "stages",
    "status",
    "tracked",
    "untracked",
)
_CLOSURE_ARTIFACT_COMPARISON_FIELDS = (
    "refs.txt",
    "status-v2-z.bin",
    "index-stages.txt",
    "staged.patch",
    "unstaged.patch",
    "untracked.tar",
    "submodules.txt",
    "submodule-command-exit",
    "index.bin-final",
)
_IDENTITY_KEYS = {
    "admin_files",
    "config",
    "deliberate_exclusions",
    "head_object_id",
    "head_symbolic_ref",
    "index",
    "object_format",
    "refs",
    "required_objects",
    "schema_version",
    "stages",
    "status",
    "tracked",
    "untracked",
}


class RepositoryRecoveryError(RuntimeError):
    """Capture, package verification, or restore failed closed."""


def _lexical_absolute(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(os.fspath(candidate)))


def _validate_existing_chain(path: Path, *, final_directory: bool) -> Path:
    candidate = _lexical_absolute(path)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if current == candidate:
                raise RepositoryRecoveryError("required path does not exist")
            raise RepositoryRecoveryError("path parent does not exist")
        if stat.S_ISLNK(metadata.st_mode):
            raise RepositoryRecoveryError("symlinked path component is forbidden")
        if current != candidate and not stat.S_ISDIR(metadata.st_mode):
            raise RepositoryRecoveryError("path parent is not a directory")
    metadata = candidate.lstat()
    if final_directory and not stat.S_ISDIR(metadata.st_mode):
        raise RepositoryRecoveryError("required path is not a directory")
    return candidate


def _validate_new_path(path: Path) -> Path:
    candidate = _lexical_absolute(path)
    if candidate.exists() or candidate.is_symlink():
        raise RepositoryRecoveryError("destination already exists")
    current = Path(candidate.anchor)
    for part in candidate.parts[1:-1]:
        current = current / part
        if not current.exists() and not current.is_symlink():
            continue
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RepositoryRecoveryError("unsafe destination parent")
    return candidate


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_relative(raw: str) -> str:
    if not raw or "\x00" in raw or "\r" in raw or "\n" in raw or "\\" in raw:
        raise RepositoryRecoveryError("unsafe repository path")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RepositoryRecoveryError("unsafe repository path")
    normalized = path.as_posix()
    if normalized != raw or normalized == ".git" or normalized.startswith(".git/"):
        raise RepositoryRecoveryError("unsafe repository path")
    return normalized


def _split_nul(payload: bytes) -> list[str]:
    if payload and not payload.endswith(b"\0"):
        raise RepositoryRecoveryError("Git output is not NUL terminated")
    result: list[str] = []
    for item in payload.split(b"\0"):
        if not item:
            continue
        try:
            result.append(_safe_relative(item.decode("utf-8", "strict")))
        except UnicodeDecodeError as exc:
            raise RepositoryRecoveryError("repository path is not UTF-8") from exc
    return result


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
            "LC_ALL": "C",
        }
    )
    result = subprocess.run(
        list(argv),
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        raise RepositoryRecoveryError(
            "command failed "
            f"exit={result.returncode} argv_sha256={_sha256(canonical_json_bytes(list(argv)))} "
            f"stderr_sha256={_sha256(result.stderr)}"
        )
    return result


def _git(repository: Path, *args: str, check: bool = True) -> bytes:
    return _run(["git", *args], cwd=repository, check=check).stdout


def _write_once(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        raise RepositoryRecoveryError("refusing to replace recovery artifact")
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise RepositoryRecoveryError("short recovery artifact write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular(path: Path) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise RepositoryRecoveryError("recovery artifact is not a unique regular file")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_mode != before.st_mode
            or opened.st_size != before.st_size
            or opened.st_mtime_ns != before.st_mtime_ns
        ):
            raise RepositoryRecoveryError("recovery artifact changed before read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_mode != opened.st_mode
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
        ):
            raise RepositoryRecoveryError("recovery artifact changed during read")
        result = b"".join(chunks)
        if len(result) != opened.st_size:
            raise RepositoryRecoveryError("short recovery artifact read")
        return result
    finally:
        os.close(descriptor)


def _restricted_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise RepositoryRecoveryError("recovery directory already exists")
    path.mkdir(mode=0o700, parents=False)
    path.chmod(0o700)


def _normalize_remote(raw: str) -> str:
    value = raw.strip()
    if value.startswith(("http://", "https://", "ssh://")):
        parsed = urlsplit(value)
        if parsed.username not in {None, "", "git"} or parsed.password is not None:
            raise RepositoryRecoveryError("credentialed remote URL is forbidden")
        if parsed.query or parsed.fragment:
            raise RepositoryRecoveryError("remote URL query or fragment is forbidden")
        hostname = parsed.hostname or ""
        username = f"{parsed.username}@" if parsed.username else ""
        port = f":{parsed.port}" if parsed.port else ""
        normalized = urlunsplit(
            (parsed.scheme, f"{username}{hostname}{port}", parsed.path, "", "")
        )
        if normalized != value:
            raise RepositoryRecoveryError("remote URL is not canonical")
        return value
    if "@" in value.split(":", 1)[0]:
        user, remainder = value.split("@", 1)
        if user != "git":
            raise RepositoryRecoveryError("credentialed remote URL is forbidden")
        return f"git@{remainder}"
    return value


def _config_records(repository: Path) -> list[dict[str, str]]:
    payload = _git(repository, "config", "--local", "--null", "--list")
    records: list[dict[str, str]] = []
    for item in payload.split(b"\0"):
        if not item:
            continue
        try:
            text = item.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise RepositoryRecoveryError("Git config is not UTF-8") from exc
        if "\n" in text:
            key, value = text.split("\n", 1)
        else:
            key, value = text, ""
        lowered = key.lower()
        if (
            lowered.startswith("branch.") and lowered.endswith((".remote", ".merge"))
        ) or (
            lowered.startswith("remote.")
            and lowered.endswith((".url", ".pushurl", ".fetch"))
        ):
            if lowered.endswith((".url", ".pushurl")):
                value = _normalize_remote(value)
            records.append({"key": key, "value": value})
    return records


def _refs(repository: Path) -> list[dict[str, str]]:
    raw = _git(
        repository,
        "for-each-ref",
        "--sort=refname",
        "--format=%(refname)%09%(objectname)%09%(objecttype)%09%(*objectname)%09%(symref)",
    )
    result: list[dict[str, str]] = []
    for line in raw.decode("utf-8", "strict").splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            raise RepositoryRecoveryError("unexpected Git ref record")
        result.append(
            {
                "object_id": fields[1],
                "object_type": fields[2],
                "peeled_object_id": fields[3],
                "refname": fields[0],
                "symref": fields[4],
            }
        )
    return result


def _admin_files(repository: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for name in _ADMIN_FILES:
        path = Path(
            _git(
                repository,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                name,
            )
            .decode("utf-8", "strict")
            .strip()
        )
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_dir():
            raise RepositoryRecoveryError("directory admin state is unsupported")
        payload = _read_regular(path)
        records.append(
            {
                "base64": base64.b64encode(payload).decode("ascii"),
                "name": name,
                "sha256": _sha256(payload),
            }
        )
    return records


def _ignored_exclusions(repository: Path) -> dict[str, object]:
    payload = _git(
        repository,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--directory",
        "-z",
    )
    if payload and not payload.endswith(b"\0"):
        raise RepositoryRecoveryError("ignored inventory is not NUL terminated")
    paths: list[str] = []
    for item in payload.split(b"\0"):
        if not item:
            continue
        directory = item.endswith(b"/")
        raw = item[:-1] if directory else item
        try:
            relative = _safe_relative(raw.decode("utf-8", "strict"))
        except UnicodeDecodeError as exc:
            raise RepositoryRecoveryError("ignored path is not UTF-8") from exc
        paths.append(f"{relative}/" if directory else relative)
        if len(paths) > _MAX_DELIBERATE_EXCLUSIONS:
            raise RepositoryRecoveryError(
                "deliberate exclusion inventory exceeds max_paths"
            )
    paths.sort(key=lambda value: value.encode("utf-8"))
    return {
        "bounds": {"max_paths": _MAX_DELIBERATE_EXCLUSIONS},
        "canonical_sha256": _sha256(canonical_json_bytes(paths)),
        "count": len(paths),
        "paths": paths,
        "policy": "Git-ignored generated, runtime, and environment paths are recorded but not restored",
    }


def _index_object_ids(stages: bytes) -> set[str]:
    if stages and not stages.endswith(b"\0"):
        raise RepositoryRecoveryError("index stages are not NUL terminated")
    result: set[str] = set()
    for record in stages.split(b"\0"):
        if not record:
            continue
        try:
            metadata, _path = record.split(b"\t", 1)
            _mode, raw_oid, _stage = metadata.split(b" ")
            oid = raw_oid.decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RepositoryRecoveryError("invalid index stage record") from exc
        if set(oid) != {"0"}:
            result.add(oid)
    return result


def _required_objects(
    repository: Path,
    *,
    admin_files: list[dict[str, str]],
    head_object_id: str,
    refs: list[dict[str, str]],
    stages: bytes,
) -> list[dict[str, str]]:
    required = _index_object_ids(stages)
    required.add(head_object_id)
    for ref in refs:
        required.add(ref["object_id"])
        if ref["peeled_object_id"]:
            required.add(ref["peeled_object_id"])
    candidates = set(required)
    for record in admin_files:
        payload = base64.b64decode(record["base64"], validate=True)
        for match in _HEX_OBJECT.finditer(payload):
            candidates.add(match.group(0).decode("ascii"))
    result: list[dict[str, str]] = []
    for oid in sorted(candidates):
        object_type = _git(repository, "cat-file", "-t", oid, check=False)
        if not object_type:
            if oid in required:
                raise RepositoryRecoveryError("required Git object is missing")
            continue
        result.append(
            {
                "object_id": oid,
                "object_type": object_type.decode("ascii", "strict").strip(),
            }
        )
    return result


def _file_inventory(repository: Path, paths: list[str]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for relative in paths:
        path = repository / relative
        if not path.exists() and not path.is_symlink():
            result.append({"exists": False, "path": relative})
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RepositoryRecoveryError(
                "only unique regular worktree files are supported"
            )
        payload = _read_regular(path)
        result.append(
            {
                "bytes": len(payload),
                "exists": True,
                "mode": stat.S_IMODE(metadata.st_mode),
                "path": relative,
                "sha256": _sha256(payload),
            }
        )
    return result


def _tar_bytes(repository: Path, inventory: list[dict[str, object]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for entry in inventory:
            if entry["exists"] is not True:
                continue
            relative = str(entry["path"])
            content = _read_regular(repository / relative)
            if _sha256(content) != entry["sha256"]:
                raise RepositoryRecoveryError("worktree changed during capture")
            info = tarfile.TarInfo(relative)
            info.size = len(content)
            info.mode = int(entry["mode"])
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _untracked_capture_bounds(repository: Path) -> dict[str, int]:
    paths = _split_nul(
        _git(repository, "ls-files", "--others", "--exclude-standard", "-z")
    )
    if len(paths) > _MAX_UNTRACKED_FILES:
        raise RepositoryRecoveryError(
            "non-ignored untracked inventory exceeds max_files"
        )
    observed_bytes = 0
    for relative in paths:
        path = repository / relative
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RepositoryRecoveryError(
                "only unique regular untracked files are supported"
            )
        observed_bytes += metadata.st_size
        if observed_bytes > _MAX_UNTRACKED_BYTES:
            raise RepositoryRecoveryError(
                "non-ignored untracked inventory exceeds max_bytes"
            )
    return {
        "max_bytes": _MAX_UNTRACKED_BYTES,
        "max_files": _MAX_UNTRACKED_FILES,
        "observed_bytes": observed_bytes,
        "observed_files": len(paths),
    }


def repository_identity(repository: Path) -> dict[str, object]:
    """Capture the mutable Git/worktree facts needed for exact comparison."""

    repository = _validate_existing_chain(Path(repository), final_directory=True)
    top = Path(
        _git(repository, "rev-parse", "--show-toplevel")
        .decode("utf-8", "strict")
        .strip()
    )
    if top != repository:
        raise RepositoryRecoveryError("repository must be the exact top level")
    head = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    symbolic = _git(repository, "symbolic-ref", "-q", "HEAD", check=False)
    index_path = Path(
        _git(repository, "rev-parse", "--path-format=absolute", "--git-path", "index")
        .decode("utf-8", "strict")
        .strip()
    )
    index = _read_regular(index_path)
    tracked_paths = sorted(
        set(_split_nul(_git(repository, "ls-files", "-z"))),
        key=lambda value: value.encode("utf-8"),
    )
    untracked_paths = _split_nul(
        _git(repository, "ls-files", "--others", "--exclude-standard", "-z")
    )
    tracked = _file_inventory(repository, tracked_paths)
    untracked = _file_inventory(repository, untracked_paths)
    status = _git(
        repository,
        "status",
        "--porcelain=v2",
        "--branch",
        "-z",
        "--untracked-files=all",
    )
    stages = _git(repository, "ls-files", "--stage", "-z")
    refs = _refs(repository)
    admin_files = _admin_files(repository)
    return {
        "admin_files": admin_files,
        "config": _config_records(repository),
        "deliberate_exclusions": _ignored_exclusions(repository),
        "head_object_id": head,
        "head_symbolic_ref": symbolic.decode("utf-8", "strict").strip() or None,
        "index": {"bytes": len(index), "sha256": _sha256(index)},
        "object_format": _git(repository, "rev-parse", "--show-object-format")
        .decode("ascii", "strict")
        .strip(),
        "refs": refs,
        "required_objects": _required_objects(
            repository,
            admin_files=admin_files,
            head_object_id=head,
            refs=refs,
            stages=stages,
        ),
        "schema_version": "hqa.repository-recovery-identity.v1",
        "stages": {"bytes": len(stages), "sha256": _sha256(stages)},
        "status": {"bytes": len(status), "sha256": _sha256(status)},
        "tracked": tracked,
        "untracked": untracked,
    }


def _package_index(package: Path) -> tuple[bytes, dict[str, object]]:
    entries: list[dict[str, object]] = []
    for name in _PACKAGE_FILES:
        path = package / name
        payload = _read_regular(path)
        entries.append(
            {
                "bytes": len(payload),
                "mode": stat.S_IMODE(path.lstat().st_mode),
                "path": name,
                "sha256": _sha256(payload),
            }
        )
    document = {
        "entries": entries,
        "entry_count": len(entries),
        "schema_version": "hqa.repository-recovery-files.v1",
    }
    return canonical_json_bytes(document), document


def _repository_roots(repository: Path) -> set[Path]:
    roots = {repository}
    for argument in ("--git-dir", "--git-common-dir"):
        raw = (
            _git(repository, "rev-parse", "--path-format=absolute", argument)
            .decode("utf-8", "strict")
            .strip()
        )
        roots.add(_lexical_absolute(Path(raw)))
    worktrees = _git(repository, "worktree", "list", "--porcelain", "-z")
    for field in worktrees.split(b"\0"):
        if not field.startswith(b"worktree "):
            continue
        try:
            roots.add(_lexical_absolute(Path(field[9:].decode("utf-8", "strict"))))
        except UnicodeDecodeError as exc:
            raise RepositoryRecoveryError("worktree path is not UTF-8") from exc
    return roots


def _assert_disjoint(path: Path, roots: set[Path], *, label: str) -> None:
    for root in roots:
        if path == root or root in path.parents or path in root.parents:
            raise RepositoryRecoveryError(f"{label} overlaps a repository worktree")


def _create_bundle(
    repository: Path, staging: Path, identity: dict[str, object]
) -> None:
    object_format = str(identity["object_format"])
    if object_format not in {"sha1", "sha256"}:
        raise RepositoryRecoveryError("unsupported Git object format")
    source = staging / ".bundle-source.git"
    verification = staging / ".bundle-verification.git"
    _run(
        ["git", "init", "--bare", f"--object-format={object_format}", str(source)],
        cwd=staging,
    )
    common_dir = Path(
        _git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")
        .decode("utf-8", "strict")
        .strip()
    )
    alternates = source / "objects" / "info" / "alternates"
    _write_once(alternates, os.fsencode(common_dir / "objects") + b"\n")
    for ref in identity["refs"]:  # type: ignore[union-attr]
        if ref["symref"]:
            continue
        _run(
            [
                "git",
                f"--git-dir={source}",
                "update-ref",
                ref["refname"],
                ref["object_id"],
            ],
            cwd=staging,
        )
    for number, record in enumerate(identity["required_objects"]):  # type: ignore[union-attr]
        refname = f"refs/recovery/objects/{number:06d}-{record['object_type']}"
        _run(
            [
                "git",
                f"--git-dir={source}",
                "update-ref",
                refname,
                record["object_id"],
            ],
            cwd=staging,
        )
    bundle = staging / "bundle.bundle"
    _run(
        ["git", f"--git-dir={source}", "bundle", "create", str(bundle), "--all"],
        cwd=staging,
    )
    bundle.chmod(0o600)
    _run(["git", "bundle", "verify", str(bundle)], cwd=repository)
    _run(
        [
            "git",
            "init",
            "--bare",
            f"--object-format={object_format}",
            str(verification),
        ],
        cwd=staging,
    )
    _run(
        ["git", f"--git-dir={verification}", "bundle", "unbundle", str(bundle)],
        cwd=staging,
    )
    required_oids = {
        record["object_id"]
        for record in identity["required_objects"]  # type: ignore[union-attr]
    }
    required_oids.update(
        ref["object_id"]
        for ref in identity["refs"]  # type: ignore[union-attr]
    )
    for oid in sorted(required_oids):
        _run(
            ["git", f"--git-dir={verification}", "cat-file", "-e", oid],
            cwd=staging,
        )
    shutil.rmtree(source)
    shutil.rmtree(verification)


def capture_repository(repository: Path, package: Path) -> dict[str, object]:
    """Create one immutable recovery package using a sibling staging directory."""

    repository = _validate_existing_chain(Path(repository), final_directory=True)
    package = _validate_new_path(Path(package))
    roots = _repository_roots(repository)
    _assert_disjoint(package, roots, label="recovery package")
    package.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = package.with_name(f".{package.name}.staging")
    _assert_disjoint(staging, roots, label="recovery staging path")
    _restricted_directory(staging)
    try:
        before = repository_identity(repository)
        _create_bundle(repository, staging, before)
        index_path = Path(
            _git(
                repository,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "index",
            )
            .decode("utf-8", "strict")
            .strip()
        )
        _write_once(staging / "index.bin", _read_regular(index_path))
        _write_once(staging / "identity.json", canonical_json_bytes(before))
        _write_once(
            staging / "tracked-worktree.tar",
            _tar_bytes(repository, list(before["tracked"])),  # type: ignore[arg-type]
        )
        _write_once(
            staging / "untracked-worktree.tar",
            _tar_bytes(repository, list(before["untracked"])),  # type: ignore[arg-type]
        )
        after = repository_identity(repository)
        if after != before:
            raise RepositoryRecoveryError("repository changed during capture")
        index_bytes, index_document = _package_index(staging)
        _write_once(staging / _INDEX_NAME, index_bytes)
        os.replace(staging, package)
        return {
            "entry_count": index_document["entry_count"],
            "head_object_id": before["head_object_id"],
            "package": str(package),
            "recovery_files_bytes": len(index_bytes),
            "recovery_files_sha256": _sha256(index_bytes),
        }
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def verify_package(package: Path) -> dict[str, object]:
    """Verify the final package index by exact file-set equality."""

    package = _validate_existing_chain(Path(package), final_directory=True)
    metadata = package.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise RepositoryRecoveryError("recovery package is not a real directory")
    observed_names: list[str] = []
    for child in package.iterdir():
        if child.name == _INDEX_NAME:
            continue
        if child.is_symlink() or not child.is_file():
            raise RepositoryRecoveryError("unsafe recovery package member")
        observed_names.append(child.name)
    index_bytes = _read_regular(package / _INDEX_NAME)
    try:
        document = json.loads(index_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryRecoveryError("invalid recovery-files JSON") from exc
    if canonical_json_bytes(document) != index_bytes:
        raise RepositoryRecoveryError("recovery-files JSON is not canonical")
    if document.get("schema_version") != "hqa.repository-recovery-files.v1":
        raise RepositoryRecoveryError("unsupported recovery-files schema")
    entries = document.get("entries")
    if (
        set(document) != {"entries", "entry_count", "schema_version"}
        or not isinstance(entries, list)
        or document.get("entry_count") != len(entries)
        or len(entries) != len(_PACKAGE_FILES)
    ):
        raise RepositoryRecoveryError("invalid recovery-files entries")
    expected_names: list[str] = []
    for expected_name, entry in zip(_PACKAGE_FILES, entries):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"bytes", "mode", "path", "sha256"}
            or entry.get("path") != expected_name
        ):
            raise RepositoryRecoveryError("invalid recovery-files entry")
        name = _safe_relative(str(entry.get("path", "")))
        if "/" in name or name == _INDEX_NAME:
            raise RepositoryRecoveryError("invalid package member name")
        payload = _read_regular(package / name)
        if entry.get("bytes") != len(payload) or entry.get("sha256") != _sha256(
            payload
        ):
            raise RepositoryRecoveryError("recovery package digest mismatch")
        if entry.get("mode") != stat.S_IMODE((package / name).lstat().st_mode):
            raise RepositoryRecoveryError("recovery package mode mismatch")
        expected_names.append(name)
    if (
        expected_names != list(_PACKAGE_FILES)
        or sorted(expected_names) != sorted(observed_names)
        or len(set(expected_names)) != len(expected_names)
    ):
        raise RepositoryRecoveryError("recovery package file-set mismatch")
    return {
        "entry_count": len(entries),
        "recovery_files_bytes": len(index_bytes),
        "recovery_files_sha256": _sha256(index_bytes),
        "verified": True,
    }


def _load_identity(package: Path) -> dict[str, object]:
    payload = _read_regular(package / "identity.json")
    try:
        identity = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryRecoveryError("invalid recovery identity") from exc
    if (
        not isinstance(identity, dict)
        or set(identity) != _IDENTITY_KEYS
        or identity.get("schema_version") != "hqa.repository-recovery-identity.v1"
        or canonical_json_bytes(identity) != payload
        or identity.get("object_format") not in {"sha1", "sha256"}
    ):
        raise RepositoryRecoveryError("invalid recovery identity")
    admin_files = identity.get("admin_files")
    if not isinstance(admin_files, list):
        raise RepositoryRecoveryError("invalid admin state")
    seen_admin: set[str] = set()
    for record in admin_files:
        if (
            not isinstance(record, dict)
            or set(record) != {"base64", "name", "sha256"}
            or record.get("name") not in _ADMIN_FILES
            or record["name"] in seen_admin
            or not isinstance(record.get("base64"), str)
            or not isinstance(record.get("sha256"), str)
        ):
            raise RepositoryRecoveryError("invalid admin state")
        seen_admin.add(record["name"])
        try:
            content = base64.b64decode(record["base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise RepositoryRecoveryError("invalid admin state") from exc
        if _sha256(content) != record["sha256"]:
            raise RepositoryRecoveryError("admin state digest mismatch")
    config = identity.get("config")
    if not isinstance(config, list):
        raise RepositoryRecoveryError("invalid recovery config")
    for record in config:
        if (
            not isinstance(record, dict)
            or set(record) != {"key", "value"}
            or not isinstance(record.get("key"), str)
            or not isinstance(record.get("value"), str)
        ):
            raise RepositoryRecoveryError("invalid recovery config")
        key = record["key"].lower()
        allowed = (
            key.startswith("branch.") and key.endswith((".remote", ".merge"))
        ) or (
            key.startswith("remote.") and key.endswith((".url", ".pushurl", ".fetch"))
        )
        if not allowed:
            raise RepositoryRecoveryError("unsupported recovery config")
        if key.endswith((".url", ".pushurl")):
            _normalize_remote(record["value"])
    for ref in identity.get("refs", []):
        if not isinstance(ref, dict) or set(ref) != {
            "object_id",
            "object_type",
            "peeled_object_id",
            "refname",
            "symref",
        }:
            raise RepositoryRecoveryError("invalid recovery ref")
        _run(["git", "check-ref-format", ref["refname"]], cwd=package)
        if ref["symref"]:
            _run(["git", "check-ref-format", ref["symref"]], cwd=package)
    return identity


def _restore_config(repository: Path, records: list[dict[str, str]]) -> None:
    for record in records:
        _run(
            [
                "git",
                "config",
                "--local",
                "--add",
                record["key"],
                record["value"],
            ],
            cwd=repository,
        )


def _clear_worktree(repository: Path) -> None:
    for current, directory_names, file_names in os.walk(
        repository, topdown=False, followlinks=False
    ):
        current_path = Path(current)
        if (
            current_path == repository / ".git"
            or repository / ".git" in current_path.parents
        ):
            continue
        for name in file_names:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise RepositoryRecoveryError("unsafe disposable worktree member")
            path.unlink()
        for name in directory_names:
            path = current_path / name
            if path == repository / ".git":
                continue
            if path.is_symlink():
                raise RepositoryRecoveryError("unsafe disposable worktree directory")
            if path.exists():
                path.rmdir()


def _extract_tar(payload: bytes, repository: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            relative = _safe_relative(member.name)
            if not member.isfile() or member.issym() or member.islnk():
                raise RepositoryRecoveryError("unsafe recovery tar member")
            target = repository / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            content = archive.extractfile(member)
            if content is None:
                raise RepositoryRecoveryError("missing recovery tar content")
            _write_once(target, content.read(), mode=member.mode & 0o777)


def _replace_file(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.recovery-tmp")
    if temporary.exists() or temporary.is_symlink():
        raise RepositoryRecoveryError("restore staging file already exists")
    _write_once(temporary, payload)
    os.replace(temporary, path)


def _restore_admin_files(repository: Path, records: list[dict[str, str]]) -> None:
    targets: dict[str, Path] = {}
    for name in _ADMIN_FILES:
        target = Path(
            _git(
                repository,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                name,
            )
            .decode("utf-8", "strict")
            .strip()
        )
        targets[name] = target
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                raise RepositoryRecoveryError("unsafe generated admin state")
            target.unlink()
    for record in records:
        name = record["name"]
        if name not in targets:
            raise RepositoryRecoveryError("unsupported admin state name")
        payload = base64.b64decode(record["base64"], validate=True)
        if _sha256(payload) != record["sha256"]:
            raise RepositoryRecoveryError("admin state digest mismatch")
        _write_once(targets[name], payload)


def _materialize_restore(package: Path, destination: Path) -> dict[str, object]:
    destination = _validate_new_path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    identity = _load_identity(package)
    _run(
        [
            "git",
            "init",
            f"--object-format={identity['object_format']}",
            str(destination),
        ],
        cwd=destination.parent,
    )
    _run(
        ["git", "bundle", "unbundle", str(package / "bundle.bundle")],
        cwd=destination,
    )
    for ref in identity["refs"]:
        if ref["symref"]:
            continue
        _run(
            ["git", "update-ref", ref["refname"], ref["object_id"]],
            cwd=destination,
        )
    for ref in identity["refs"]:
        if not ref["symref"]:
            continue
        _run(
            ["git", "symbolic-ref", ref["refname"], ref["symref"]],
            cwd=destination,
        )
    symbolic = identity["head_symbolic_ref"]
    if symbolic is None:
        _run(
            ["git", "update-ref", "--no-deref", "HEAD", identity["head_object_id"]],
            cwd=destination,
        )
    else:
        _run(["git", "symbolic-ref", "HEAD", symbolic], cwd=destination)
    _restore_config(destination, identity["config"])
    _clear_worktree(destination)
    _extract_tar(_read_regular(package / "tracked-worktree.tar"), destination)
    _extract_tar(_read_regular(package / "untracked-worktree.tar"), destination)
    index_path = Path(
        _git(destination, "rev-parse", "--path-format=absolute", "--git-path", "index")
        .decode("utf-8", "strict")
        .strip()
    )
    _replace_file(index_path, _read_regular(package / "index.bin"))
    _restore_admin_files(destination, identity["admin_files"])
    observed = repository_identity(destination)
    return {"expected": identity, "observed": observed}


def restore_drill(
    package: Path,
    destination: Path,
    receipt: Path,
    *,
    rehearsal: Sequence[str] = ("git", "status", "--porcelain=v2"),
) -> dict[str, object]:
    """Restore once, compare exact identity, rehearse, and write an external receipt."""

    package = _validate_existing_chain(Path(package), final_directory=True)
    destination = _validate_new_path(Path(destination))
    receipt = _validate_new_path(Path(receipt))
    if destination == package or package in destination.parents:
        raise RepositoryRecoveryError("restore destination must be outside its package")
    if package == receipt.parent or package in receipt.parents:
        raise RepositoryRecoveryError("restore receipt must be outside its package")
    if receipt == destination or destination in receipt.parents:
        raise RepositoryRecoveryError("restore receipt must be outside its destination")
    package_validation = verify_package(package)
    comparison = _materialize_restore(package, destination)
    mismatches = sorted(
        key
        for key, expected in comparison["expected"].items()
        if key != "deliberate_exclusions"
        and comparison["observed"].get(key) != expected
    )
    rehearsal_result = _run(list(rehearsal), cwd=destination, check=False)
    restore_verified = not mismatches and rehearsal_result.returncode == 0
    receipt_document = {
        "comparison_mismatches": mismatches,
        "destination": str(destination),
        "package": str(package),
        "package_validation": {
            **package_validation,
            "exact_bytes_verified": True,
            "recovery_files_path": str(package / _INDEX_NAME),
        },
        "rehearsal": {
            "argv": list(rehearsal),
            "exit_code": rehearsal_result.returncode,
            "stderr_sha256": _sha256(rehearsal_result.stderr),
            "stdout_sha256": _sha256(rehearsal_result.stdout),
        },
        "restore_verified": restore_verified,
        "schema_version": "hqa.repository-restore-receipt.v1",
    }
    receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_once(receipt, canonical_json_bytes(receipt_document))
    if not restore_verified:
        raise RepositoryRecoveryError("restore drill did not verify")
    return receipt_document


def verify_receipt(package: Path, receipt: Path) -> dict[str, object]:
    """Re-read one receipt and the exact final package index it claims."""

    package = _validate_existing_chain(Path(package), final_directory=True)
    receipt = _validate_existing_chain(Path(receipt), final_directory=False)
    receipt_bytes = _read_regular(receipt)
    try:
        document = json.loads(receipt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryRecoveryError("invalid restore receipt") from exc
    if canonical_json_bytes(document) != receipt_bytes:
        raise RepositoryRecoveryError("restore receipt is not canonical")
    validation = verify_package(package)
    claimed = document.get("package_validation")
    if (
        document.get("schema_version") != "hqa.repository-restore-receipt.v1"
        or document.get("package") != str(package)
        or document.get("comparison_mismatches") != []
        or not isinstance(document.get("rehearsal"), dict)
        or document["rehearsal"].get("exit_code") != 0
        or not isinstance(claimed, dict)
        or claimed.get("recovery_files_sha256") != validation["recovery_files_sha256"]
        or claimed.get("recovery_files_bytes") != validation["recovery_files_bytes"]
        or claimed.get("entry_count") != validation["entry_count"]
        or claimed.get("exact_bytes_verified") is not True
        or claimed.get("verified") is not True
        or claimed.get("recovery_files_path") != str(package / _INDEX_NAME)
        or document.get("restore_verified") is not True
    ):
        raise RepositoryRecoveryError(
            "restore receipt does not bind final package index"
        )
    return {
        "receipt_sha256": _sha256(receipt_bytes),
        "recovery_files_bytes": validation["recovery_files_bytes"],
        "recovery_files_sha256": validation["recovery_files_sha256"],
        "verified": True,
    }


def _closure_observation(payload: bytes) -> dict[str, object]:
    return {"bytes": len(payload), "sha256": _sha256(payload)}


def _closure_refs_text(repository: Path) -> bytes:
    return _git(
        repository,
        "for-each-ref",
        "--sort=refname",
        "--format=%(refname)%09%(objectname)%09%(objecttype)%09%(*objectname)%09%(symref)",
    )


def _closure_index_stages_text(repository: Path) -> bytes:
    return _git(repository, "ls-files", "--stage")


def _closure_staged_patch(repository: Path) -> bytes:
    return _git(
        repository,
        "diff",
        "--cached",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-color",
    )


def _closure_unstaged_patch(repository: Path) -> bytes:
    return _git(
        repository,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-color",
    )


def _closure_worktree_list(repository: Path) -> bytes:
    return _git(repository, "worktree", "list", "--porcelain")


def _closure_submodules(repository: Path) -> tuple[bytes, int, str]:
    result = _run(
        ["git", "submodule", "status", "--recursive"],
        cwd=repository,
        check=False,
    )
    return result.stdout, result.returncode, _sha256(result.stderr)


def _closure_upstream(repository: Path) -> str | None:
    result = _run(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ],
        cwd=repository,
        check=False,
    )
    if result.returncode:
        return None
    return result.stdout.decode("utf-8", "strict").strip()


def _closure_package_index(package: Path) -> tuple[bytes, dict[str, object]]:
    entries: list[dict[str, object]] = []
    for name in _CLOSURE_PACKAGE_FILES:
        path = package / name
        payload = _read_regular(path)
        mode = stat.S_IMODE(path.lstat().st_mode)
        if mode != 0o600:
            raise RepositoryRecoveryError("closure recovery artifact mode is not 0600")
        entries.append(
            {
                "bytes": len(payload),
                "mode": mode,
                "path": name,
                "sha256": _sha256(payload),
            }
        )
    document = {
        "entries": entries,
        "entry_count": len(entries),
        "schema_version": "hqa.repository-recovery-files.v2",
        "self_digest_policy": (
            "recovery-files.json is excluded; its digest is supplied by the "
            "enclosing closure manifest"
        ),
    }
    return canonical_json_bytes(document), document


def _load_closure_identity(package: Path) -> dict[str, object]:
    payload = _read_regular(package / "identity.json")
    try:
        identity = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryRecoveryError("invalid closure recovery identity") from exc
    required = {
        "absolute_checkout_path",
        "branch",
        "capture_observations",
        "capture_time",
        "deliberate_exclusions",
        "git_version",
        "head",
        "mutable_identity",
        "object_format",
        "operator_identity",
        "publication_remote_name",
        "publication_url",
        "rehearsal_input",
        "repository_id",
        "schema_version",
        "submodule_capture",
        "untracked_capture_bounds",
        "upstream",
    }
    mutable = identity.get("mutable_identity") if isinstance(identity, dict) else None
    untracked_bounds = (
        identity.get("untracked_capture_bounds")
        if isinstance(identity, dict)
        else None
    )
    deliberate_exclusions = (
        mutable.get("deliberate_exclusions")
        if isinstance(mutable, dict)
        else None
    )
    untracked = mutable.get("untracked") if isinstance(mutable, dict) else None
    rehearsal_input = (
        identity.get("rehearsal_input") if isinstance(identity, dict) else None
    )
    if (
        not isinstance(identity, dict)
        or set(identity) != required
        or identity.get("schema_version")
        != "hqa.repository-recovery-identity.v2"
        or canonical_json_bytes(identity) != payload
        or not isinstance(mutable, dict)
        or set(mutable) != _IDENTITY_KEYS
        or mutable.get("schema_version")
        != "hqa.repository-recovery-identity.v1"
        or identity.get("head") != mutable.get("head_object_id")
        or identity.get("object_format") != mutable.get("object_format")
        or not isinstance(identity.get("repository_id"), str)
        or not identity["repository_id"]
        or not isinstance(identity.get("operator_identity"), str)
        or not identity["operator_identity"]
        or not isinstance(identity.get("absolute_checkout_path"), str)
        or not Path(identity["absolute_checkout_path"]).is_absolute()
        or not isinstance(rehearsal_input, dict)
        or set(rehearsal_input) != {"document", "kind", "sha256"}
        or rehearsal_input.get("kind") != "closed_rebuild"
        or not isinstance(rehearsal_input.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", rehearsal_input["sha256"]) is None
        or not isinstance(rehearsal_input.get("document"), dict)
        or _sha256(
            canonical_json_bytes(rehearsal_input["document"])
        )
        != rehearsal_input["sha256"]
        or not isinstance(untracked_bounds, dict)
        or set(untracked_bounds)
        != {"max_bytes", "max_files", "observed_bytes", "observed_files"}
        or untracked_bounds.get("max_bytes") != _MAX_UNTRACKED_BYTES
        or untracked_bounds.get("max_files") != _MAX_UNTRACKED_FILES
        or not isinstance(untracked_bounds.get("observed_bytes"), int)
        or not isinstance(untracked_bounds.get("observed_files"), int)
        or untracked_bounds["observed_bytes"] < 0
        or untracked_bounds["observed_bytes"] > _MAX_UNTRACKED_BYTES
        or untracked_bounds["observed_files"] < 0
        or untracked_bounds["observed_files"] > _MAX_UNTRACKED_FILES
        or not isinstance(untracked, list)
        or untracked_bounds["observed_files"] != len(untracked)
        or untracked_bounds["observed_bytes"]
        != sum(
            int(entry.get("bytes", 0))
            for entry in untracked
            if isinstance(entry, dict) and entry.get("exists") is True
        )
        or not isinstance(deliberate_exclusions, dict)
        or deliberate_exclusions.get("bounds")
        != {"max_paths": _MAX_DELIBERATE_EXCLUSIONS}
        or not isinstance(deliberate_exclusions.get("count"), int)
        or deliberate_exclusions["count"] > _MAX_DELIBERATE_EXCLUSIONS
    ):
        raise RepositoryRecoveryError("invalid closure recovery identity")
    _normalize_remote(str(identity["publication_url"]))
    return identity


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _closure_restore_semantically_verified(
    attempt: object,
    *,
    package: Path,
    identity: dict[str, object],
) -> bool:
    if not isinstance(attempt, dict):
        raise RepositoryRecoveryError("invalid closure restore attempt")
    commands = attempt.get("command_exits")
    mismatches = attempt.get("comparison_mismatches")
    compared = attempt.get("compared_fields")
    if (
        not isinstance(commands, list)
        or not isinstance(mismatches, list)
        or not all(isinstance(value, str) for value in mismatches)
        or not isinstance(compared, list)
        or not isinstance(attempt.get("restore_exit_code"), int)
        or isinstance(attempt.get("restore_exit_code"), bool)
        or not isinstance(attempt.get("restore_verified"), bool)
        or not isinstance(attempt.get("destination"), str)
    ):
        raise RepositoryRecoveryError("invalid closure restore attempt")
    command_exits_are_zero = bool(commands)
    for command in commands:
        if (
            not isinstance(command, dict)
            or not isinstance(command.get("exit_code"), int)
            or isinstance(command.get("exit_code"), bool)
            or not isinstance(command.get("argv"), list)
            or not all(
                isinstance(argument, str) and argument
                for argument in command["argv"]
            )
            or not _is_sha256(command.get("stdout_sha256"))
            or not _is_sha256(command.get("stderr_sha256"))
        ):
            raise RepositoryRecoveryError("invalid closure restore command receipt")
        command_exits_are_zero = (
            command_exits_are_zero and command["exit_code"] == 0
        )
    expected_fields = [
        *_CLOSURE_IDENTITY_COMPARISON_FIELDS,
        *_CLOSURE_ARTIFACT_COMPARISON_FIELDS,
    ]
    mutable = identity["mutable_identity"]
    if not isinstance(mutable, dict):
        raise RepositoryRecoveryError("invalid closure mutable identity")
    expected_hashes = {
        field: _sha256(canonical_json_bytes(mutable.get(field)))
        for field in _CLOSURE_IDENTITY_COMPARISON_FIELDS
    }
    for field in _CLOSURE_ARTIFACT_COMPARISON_FIELDS:
        if field == "submodule-command-exit":
            expected_hashes[field] = _sha256(b"0")
        elif field == "index.bin-final":
            expected_hashes[field] = _sha256(
                _read_regular(package / "index.bin")
            )
        else:
            expected_hashes[field] = _sha256(_read_regular(package / field))
    if [
        comparison.get("field") if isinstance(comparison, dict) else None
        for comparison in compared
    ] != expected_fields:
        raise RepositoryRecoveryError(
            "closure restore comparison field-set mismatch"
        )
    comparisons_match = True
    for comparison in compared:
        if (
            not isinstance(comparison, dict)
            or not isinstance(comparison.get("field"), str)
            or comparison.get("match") is not True
            or comparison.get("expected_sha256")
            != comparison.get("observed_sha256")
            or comparison.get("expected_sha256")
            != expected_hashes[comparison["field"]]
        ):
            raise RepositoryRecoveryError(
                "invalid closure restore comparison receipt"
            )
    computed = (
        attempt["restore_exit_code"] == 0
        and mismatches == []
        and command_exits_are_zero
        and comparisons_match
    )
    if attempt["restore_verified"] is not computed:
        raise RepositoryRecoveryError(
            "closure restore attempt semantic mismatch"
        )
    return computed


def _closure_rehearsal_semantically_verified(
    rehearsal: object,
    *,
    expected_input: dict[str, object],
    first_destination: str,
    second_destination: str,
    package: Path,
    source_checkout: Path,
) -> bool:
    if (
        not isinstance(rehearsal, dict)
        or rehearsal.get("input_sha256") != expected_input.get("sha256")
        or not _is_sha256(rehearsal.get("input_sha256"))
        or not isinstance(rehearsal.get("enabled"), bool)
        or not isinstance(rehearsal.get("state_changed"), bool)
    ):
        raise RepositoryRecoveryError("invalid closure rehearsal receipt")
    if (
        expected_input.get("kind") != "closed_rebuild"
        or "check_exit_code" in rehearsal
    ):
        raise RepositoryRecoveryError("closure rehearsal kind mismatch")
    spec = expected_input.get("document")
    if not isinstance(spec, dict):
        raise RepositoryRecoveryError("invalid embedded closed rebuild spec")
    return _closed_rebuild_rehearsal_verified(
        rehearsal,
        spec=spec,
        destination=Path(first_destination),
        expected_cache_path=package.parent / "uv-cache",
        protected_paths=[
            package,
            Path(first_destination),
            Path(second_destination),
            source_checkout,
        ],
    )


def verify_closure_package(package: Path) -> dict[str, object]:
    """Verify an exact Section 4.1 package and its non-recursive index."""

    package = _validate_existing_chain(Path(package), final_directory=True)
    if stat.S_IMODE(package.lstat().st_mode) != 0o700:
        raise RepositoryRecoveryError("closure recovery package mode is not 0700")
    observed_names: list[str] = []
    for child in package.iterdir():
        if child.is_symlink() or not child.is_file():
            raise RepositoryRecoveryError("unsafe closure recovery package member")
        if stat.S_IMODE(child.lstat().st_mode) != 0o600:
            raise RepositoryRecoveryError(
                "closure recovery package member mode is not 0600"
            )
        observed_names.append(child.name)
    expected_names = [*_CLOSURE_PACKAGE_FILES, _INDEX_NAME]
    if sorted(observed_names) != sorted(expected_names) or len(
        observed_names
    ) != len(set(observed_names)):
        raise RepositoryRecoveryError("closure recovery package file-set mismatch")
    index_bytes = _read_regular(package / _INDEX_NAME)
    try:
        document = json.loads(index_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryRecoveryError(
            "invalid closure recovery-files JSON"
        ) from exc
    if canonical_json_bytes(document) != index_bytes:
        raise RepositoryRecoveryError(
            "closure recovery-files JSON is not canonical"
        )
    entries = document.get("entries") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document)
        != {
            "entries",
            "entry_count",
            "schema_version",
            "self_digest_policy",
        }
        or document.get("schema_version")
        != "hqa.repository-recovery-files.v2"
        or document.get("entry_count") != len(_CLOSURE_PACKAGE_FILES)
        or not isinstance(entries, list)
        or len(entries) != len(_CLOSURE_PACKAGE_FILES)
    ):
        raise RepositoryRecoveryError("invalid closure recovery-files entries")
    for expected_name, entry in zip(_CLOSURE_PACKAGE_FILES, entries):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"bytes", "mode", "path", "sha256"}
            or entry.get("path") != expected_name
            or entry.get("mode") != 0o600
        ):
            raise RepositoryRecoveryError(
                "invalid closure recovery-files entry"
            )
        payload = _read_regular(package / expected_name)
        if (
            entry.get("bytes") != len(payload)
            or entry.get("sha256") != _sha256(payload)
        ):
            raise RepositoryRecoveryError(
                "closure recovery package digest mismatch"
            )
    identity = _load_closure_identity(package)
    receipt_bytes = _read_regular(package / "restore-receipt.json")
    try:
        receipt = json.loads(receipt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryRecoveryError("invalid closure restore receipt") from exc
    if (
        canonical_json_bytes(receipt) != receipt_bytes
        or not isinstance(receipt, dict)
        or set(receipt)
        != {
            "filesystem_devices",
            "first_restore",
            "package",
            "rehearsal",
            "restore_verified",
            "same_filesystem_class",
            "schema_version",
            "second_restore",
            "source_after_drills_sha256",
            "source_before_sha256",
        }
        or receipt.get("schema_version")
        != "hqa.repository-restore-receipt.v2"
        or receipt.get("package") != str(package)
        or not isinstance(receipt.get("restore_verified"), bool)
    ):
        raise RepositoryRecoveryError("invalid closure restore receipt")
    first_verified = _closure_restore_semantically_verified(
        receipt["first_restore"], package=package, identity=identity
    )
    second_verified = _closure_restore_semantically_verified(
        receipt["second_restore"], package=package, identity=identity
    )
    rehearsal_verified = _closure_rehearsal_semantically_verified(
        receipt["rehearsal"],
        expected_input=identity["rehearsal_input"],  # type: ignore[arg-type]
        first_destination=receipt["first_restore"]["destination"],
        second_destination=receipt["second_restore"]["destination"],
        package=package,
        source_checkout=Path(str(identity["absolute_checkout_path"])),
    )
    expected_source_sha256 = _sha256(
        canonical_json_bytes(identity["mutable_identity"])
    )
    source_unchanged = (
        receipt.get("source_before_sha256") == expected_source_sha256
        and receipt.get("source_after_drills_sha256")
        == expected_source_sha256
    )
    devices = receipt.get("filesystem_devices")
    if (
        not isinstance(devices, dict)
        or set(devices)
        != {
            "first_restore_st_dev",
            "second_restore_st_dev",
            "source_st_dev",
        }
        or not all(
            value is None
            or (isinstance(value, int) and not isinstance(value, bool))
            for value in devices.values()
        )
        or not isinstance(receipt.get("same_filesystem_class"), bool)
    ):
        raise RepositoryRecoveryError("invalid closure filesystem receipt")
    same_filesystem_class = (
        isinstance(devices["source_st_dev"], int)
        and devices["source_st_dev"]
        == devices["first_restore_st_dev"]
        == devices["second_restore_st_dev"]
    )
    if receipt["same_filesystem_class"] is not same_filesystem_class:
        raise RepositoryRecoveryError(
            "closure filesystem class semantic mismatch"
        )
    computed_restore_verified = (
        first_verified
        and second_verified
        and rehearsal_verified
        and source_unchanged
        and same_filesystem_class
    )
    if receipt["restore_verified"] is not computed_restore_verified:
        raise RepositoryRecoveryError(
            "closure restore receipt semantic mismatch"
        )
    verification_rebuild_verified = False
    verification_rebuild_proof: dict[str, object] | None = None
    verification_rebuild_exit_code: int | None = None
    if computed_restore_verified:
        rehearsal_input = identity["rehearsal_input"]
        if not isinstance(rehearsal_input, dict):
            raise RepositoryRecoveryError(
                "invalid closure rebuild verification input"
            )
        rebuild_spec = rehearsal_input.get("document")
        if not isinstance(rebuild_spec, dict):
            raise RepositoryRecoveryError(
                "invalid closure rebuild verification input"
            )
        with tempfile.TemporaryDirectory(
            prefix=f".{package.name}.verify-rebuild-",
            dir=package.parent,
        ) as temporary:
            verification_root = Path(temporary)
            verification_root.chmod(0o700)
            verification_destination = verification_root / "restore"
            verification_restore = _closure_restore_attempt(
                package,
                verification_destination,
                identity,
            )
            if verification_restore.get("restore_verified") is not True:
                raise RepositoryRecoveryError(
                    "independent verification restore failed"
                )
            verification_rehearsal = _closure_rehearse_closed_rebuild(
                verification_destination,
                rebuild_spec,
                enabled=True,
                expected_cache_path=package.parent / "uv-cache",
                protected_paths=[
                    package,
                    verification_destination,
                    Path(str(receipt["first_restore"]["destination"])),
                    Path(str(receipt["second_restore"]["destination"])),
                    Path(str(identity["absolute_checkout_path"])),
                ],
            )
            verification_rebuild_exit_code = verification_rehearsal.get(
                "command_exit_code"
            )
            if not isinstance(verification_rebuild_exit_code, int):
                raise RepositoryRecoveryError(
                    "independent verification rebuild exit is invalid"
                )
            verification_rebuild_verified = (
                _closed_rebuild_rehearsal_verified(
                    verification_rehearsal,
                    spec=rebuild_spec,
                    destination=verification_destination,
                    expected_cache_path=package.parent / "uv-cache",
                    protected_paths=[
                        package,
                        verification_destination,
                        Path(str(receipt["first_restore"]["destination"])),
                        Path(str(receipt["second_restore"]["destination"])),
                        Path(str(identity["absolute_checkout_path"])),
                    ],
                )
            )
            proof = verification_rehearsal.get("rebuild_proof")
            if not isinstance(proof, dict):
                raise RepositoryRecoveryError(
                    "independent verification rebuild proof is invalid"
                )
            verification_rebuild_proof = proof
            if verification_rebuild_verified is not True:
                raise RepositoryRecoveryError(
                    "independent verification rebuild failed"
                )
    return {
        "entry_count": len(entries),
        "head": identity["head"],
        "recovery_files_bytes": len(index_bytes),
        "recovery_files_sha256": _sha256(index_bytes),
        "restore_receipt_sha256": _sha256(receipt_bytes),
        "restore_verified": computed_restore_verified,
        "verification_rebuild_exit_code": verification_rebuild_exit_code,
        "verification_rebuild_proof": verification_rebuild_proof,
        "verification_rebuild_verified": verification_rebuild_verified,
        "verified": True,
    }


def _closure_recorded_run(
    argv: Sequence[str],
    *,
    cwd: Path,
    records: list[dict[str, object]],
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = _run(argv, cwd=cwd, check=False)
    records.append(
        {
            "argv": list(argv),
            "exit_code": result.returncode,
            "stderr_sha256": _sha256(result.stderr),
            "stdout_sha256": _sha256(result.stdout),
        }
    )
    if check and result.returncode:
        raise RepositoryRecoveryError(
            "closure restore command failed "
            f"exit={result.returncode} "
            f"argv_sha256={_sha256(canonical_json_bytes(list(argv)))} "
            f"stderr_sha256={_sha256(result.stderr)}"
        )
    return result


def _closure_restore_modes(
    repository: Path, mutable_identity: dict[str, object]
) -> None:
    for category in ("tracked", "untracked"):
        entries = mutable_identity.get(category)
        if not isinstance(entries, list):
            raise RepositoryRecoveryError("invalid closure worktree inventory")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("path"), str
            ):
                raise RepositoryRecoveryError(
                    "invalid closure worktree inventory"
                )
            target = repository / _safe_relative(entry["path"])
            if entry.get("exists") is not True:
                if target.exists() or target.is_symlink():
                    raise RepositoryRecoveryError(
                        "closure restore retained a deleted path"
                    )
                continue
            if target.is_symlink() or not target.is_file():
                raise RepositoryRecoveryError(
                    "closure restore worktree member is unsafe"
                )
            mode = entry.get("mode")
            if not isinstance(mode, int):
                raise RepositoryRecoveryError(
                    "invalid closure worktree inventory mode"
                )
            target.chmod(mode)


def _closure_compare(
    expected: dict[str, object], observed: dict[str, object]
) -> tuple[list[dict[str, object]], list[str]]:
    compared_fields: list[dict[str, object]] = []
    mismatches: list[str] = []
    for field in _CLOSURE_IDENTITY_COMPARISON_FIELDS:
        expected_bytes = canonical_json_bytes(expected.get(field))
        observed_bytes = canonical_json_bytes(observed.get(field))
        matches = expected.get(field) == observed.get(field)
        compared_fields.append(
            {
                "expected_sha256": _sha256(expected_bytes),
                "field": field,
                "match": matches,
                "observed_sha256": _sha256(observed_bytes),
            }
        )
        if not matches:
            mismatches.append(field)
    return compared_fields, mismatches


def _closure_compare_artifacts(
    package: Path, repository: Path, mutable_identity: dict[str, object]
) -> tuple[list[dict[str, object]], list[str]]:
    untracked_tar = _tar_bytes(
        repository,
        list(mutable_identity["untracked"]),  # type: ignore[arg-type]
    )
    submodules, submodule_exit, submodule_stderr = _closure_submodules(repository)
    observed = {
        "refs.txt": _closure_refs_text(repository),
        "status-v2-z.bin": _git(
            repository,
            "status",
            "--porcelain=v2",
            "--branch",
            "-z",
            "--untracked-files=all",
        ),
        "index-stages.txt": _closure_index_stages_text(repository),
        "staged.patch": _closure_staged_patch(repository),
        "unstaged.patch": _closure_unstaged_patch(repository),
        "untracked.tar": untracked_tar,
        "submodules.txt": submodules,
    }
    compared: list[dict[str, object]] = []
    mismatches: list[str] = []
    for name, payload in observed.items():
        expected = _read_regular(package / name)
        matches = payload == expected
        compared.append(
            {
                "expected_sha256": _sha256(expected),
                "field": name,
                "match": matches,
                "observed_sha256": _sha256(payload),
            }
        )
        if not matches:
            mismatches.append(name)
    compared.append(
        {
            "expected_sha256": _sha256(b"0"),
            "field": "submodule-command-exit",
            "match": submodule_exit == 0,
            "observed_sha256": _sha256(str(submodule_exit).encode("ascii")),
            "stderr_sha256": submodule_stderr,
        }
    )
    if submodule_exit:
        mismatches.append("submodule-command-exit")
    return compared, mismatches


def _materialize_closure_restore(
    package: Path,
    destination: Path,
    identity: dict[str, object],
    *,
    records: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    destination = _validate_new_path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    mutable = identity["mutable_identity"]
    if not isinstance(mutable, dict):
        raise RepositoryRecoveryError("invalid closure mutable identity")
    if records is None:
        records = []
    _closure_recorded_run(
        [
            "git",
            "init",
            f"--object-format={identity['object_format']}",
            str(destination),
        ],
        cwd=destination.parent,
        records=records,
    )
    _closure_recorded_run(
        ["git", "bundle", "unbundle", str(package / "bundle.bundle")],
        cwd=destination,
        records=records,
    )
    refs = mutable.get("refs")
    if not isinstance(refs, list):
        raise RepositoryRecoveryError("invalid closure refs")
    for ref in refs:
        if ref["symref"]:
            continue
        _closure_recorded_run(
            ["git", "update-ref", ref["refname"], ref["object_id"]],
            cwd=destination,
            records=records,
        )
    for ref in refs:
        if not ref["symref"]:
            continue
        _closure_recorded_run(
            ["git", "symbolic-ref", ref["refname"], ref["symref"]],
            cwd=destination,
            records=records,
        )
    symbolic = mutable["head_symbolic_ref"]
    if symbolic is None:
        _closure_recorded_run(
            [
                "git",
                "update-ref",
                "--no-deref",
                "HEAD",
                str(mutable["head_object_id"]),
            ],
            cwd=destination,
            records=records,
        )
    else:
        _closure_recorded_run(
            ["git", "symbolic-ref", "HEAD", str(symbolic)],
            cwd=destination,
            records=records,
        )
    config = mutable.get("config")
    if not isinstance(config, list):
        raise RepositoryRecoveryError("invalid closure config")
    for record in config:
        _closure_recorded_run(
            [
                "git",
                "config",
                "--local",
                "--add",
                record["key"],
                record["value"],
            ],
            cwd=destination,
            records=records,
        )
    _closure_recorded_run(
        ["git", "reset", "--hard", str(mutable["head_object_id"])],
        cwd=destination,
        records=records,
    )
    staged = _read_regular(package / "staged.patch")
    if staged:
        _closure_recorded_run(
            [
                "git",
                "apply",
                "--binary",
                "--index",
                "--whitespace=nowarn",
                "--",
                str(package / "staged.patch"),
            ],
            cwd=destination,
            records=records,
        )
    unstaged = _read_regular(package / "unstaged.patch")
    if unstaged:
        _closure_recorded_run(
            [
                "git",
                "apply",
                "--binary",
                "--whitespace=nowarn",
                "--",
                str(package / "unstaged.patch"),
            ],
            cwd=destination,
            records=records,
        )
    _extract_tar(_read_regular(package / "untracked.tar"), destination)
    index_path = Path(
        _git(
            destination,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
        .decode("utf-8", "strict")
        .strip()
    )
    _replace_file(index_path, _read_regular(package / "index.bin"))
    admin_files = mutable.get("admin_files")
    if not isinstance(admin_files, list):
        raise RepositoryRecoveryError("invalid closure admin files")
    _restore_admin_files(destination, admin_files)
    _closure_restore_modes(destination, mutable)
    observed = repository_identity(destination)
    compared_fields, mismatches = _closure_compare(mutable, observed)
    artifact_fields, artifact_mismatches = _closure_compare_artifacts(
        package, destination, mutable
    )
    mismatches.extend(artifact_mismatches)
    expected_index = _read_regular(package / "index.bin")
    _replace_file(index_path, expected_index)
    final_index = _read_regular(index_path)
    final_index_matches = final_index == expected_index
    artifact_fields.append(
        {
            "expected_sha256": _sha256(expected_index),
            "field": "index.bin-final",
            "match": final_index_matches,
            "observed_sha256": _sha256(final_index),
        }
    )
    if not final_index_matches:
        mismatches.append("index.bin-final")
    return {
        "command_exits": records,
        "compared_fields": [*compared_fields, *artifact_fields],
        "comparison_mismatches": sorted(mismatches),
        "destination": str(destination),
        "restore_exit_code": 0,
        "restore_verified": not mismatches,
    }


def _closure_restore_attempt(
    package: Path,
    destination: Path,
    identity: dict[str, object],
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    try:
        return _materialize_closure_restore(
            package, destination, identity, records=records
        )
    except RepositoryRecoveryError as exc:
        return {
            "command_exits": records,
            "compared_fields": [],
            "comparison_mismatches": ["restore-error"],
            "destination": str(destination),
            "error": str(exc),
            "restore_exit_code": 1,
            "restore_verified": False,
        }


def _regular_tree_inventory(root: Path) -> list[dict[str, object]]:
    root = _validate_existing_chain(root, final_directory=True)
    entries: list[dict[str, object]] = []

    def walk(directory: Path, prefix: PurePosixPath) -> None:
        try:
            with os.scandir(directory) as iterator:
                children = sorted(
                    iterator,
                    key=lambda child: child.name.encode("utf-8"),
                )
        except OSError as exc:
            raise RepositoryRecoveryError(
                "cannot enumerate closed rebuild source"
            ) from exc
        for child in children:
            relative = prefix / child.name
            metadata = child.stat(follow_symlinks=False)
            path = Path(child.path)
            if stat.S_ISLNK(metadata.st_mode):
                raise RepositoryRecoveryError(
                    "symlink in closed rebuild source is forbidden"
                )
            if stat.S_ISDIR(metadata.st_mode):
                walk(path, relative)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise RepositoryRecoveryError(
                    "special file in closed rebuild source is forbidden"
                )
            payload = _read_regular(path)
            entries.append(
                {
                    "path": relative.as_posix(),
                    "sha256": _sha256(payload),
                    "size": len(payload),
                }
            )

    walk(root, PurePosixPath())
    return entries


def _captured_source_inventory(
    repository: Path,
    source_package: str,
) -> list[dict[str, object]]:
    source_relative = _safe_relative(source_package)
    prefix = f"{source_relative}/"
    paths = sorted(
        set(
            _split_nul(
                _git(
                    repository,
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                    "--",
                    source_relative,
                )
            )
        ),
        key=lambda value: value.encode("utf-8"),
    )
    entries: list[dict[str, object]] = []
    for recorded in _file_inventory(repository, paths):
        if recorded["exists"] is not True:
            continue
        repository_relative = str(recorded["path"])
        if not repository_relative.startswith(prefix):
            raise RepositoryRecoveryError(
                "closed rebuild source path escaped its package"
            )
        entries.append(
            {
                "path": _safe_relative(repository_relative[len(prefix) :]),
                "sha256": recorded["sha256"],
                "size": recorded["bytes"],
            }
        )
    return entries


def _managed_python_contract() -> dict[str, object]:
    try:
        interpreter = Path(sys._base_executable).resolve(strict=True)
        invocation = Path(sys.executable)
        managed_root = (
            Path.home() / ".local" / "share" / "uv" / "python"
        ).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryRecoveryError(
            "managed Python interpreter cannot be resolved"
        ) from exc
    if (
        managed_root not in interpreter.parents
        or not interpreter.is_file()
        or not os.access(interpreter, os.X_OK)
        or sys.version_info[:2] != (3, 11)
    ):
        raise RepositoryRecoveryError(
            "closed rebuild requires the managed Python 3.11 interpreter"
        )
    python_input = interpreter
    if invocation.is_symlink():
        link_text = os.readlink(invocation)
        candidate = Path(link_text)
        if (
            candidate.is_absolute()
            and candidate.resolve(strict=True) == interpreter
        ):
            python_input = candidate
    return {
        "path": str(python_input),
        "resolved_path": str(interpreter),
        "sha256": _sha256(_read_regular(interpreter)),
        "version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def _closed_rebuild_spec(
    repository: Path,
    package: Path,
    *,
    repository_id: str,
) -> dict[str, object]:
    project = _CLOSED_REBUILD_PROJECTS.get(repository_id)
    if project is None:
        raise RepositoryRecoveryError(
            "closed rebuild is unsupported for this repository ID"
        )
    pyproject = _validate_existing_chain(
        repository / "pyproject.toml", final_directory=False
    )
    lockfile = _validate_existing_chain(
        repository / "uv.lock", final_directory=False
    )
    try:
        metadata = tomllib.loads(_read_regular(pyproject).decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RepositoryRecoveryError(
            "invalid closed rebuild project metadata"
        ) from exc
    project_metadata = metadata.get("project")
    if (
        not isinstance(project_metadata, dict)
        or project_metadata.get("name") != project["distribution_name"]
    ):
        raise RepositoryRecoveryError(
            "closed rebuild repository identity does not match project metadata"
        )
    source_package = _validate_existing_chain(
        repository / str(project["source_package"]),
        final_directory=True,
    )
    try:
        uv = _UV_EXECUTABLE.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryRecoveryError(
            "closed rebuild uv executable cannot be resolved"
        ) from exc
    if not os.access(uv, os.X_OK):
        raise RepositoryRecoveryError("closed rebuild uv executable is not executable")
    cache = package.parent / "uv-cache"
    if not cache.exists() and not cache.is_symlink():
        cache.mkdir(mode=0o700)
    cache = _validate_existing_chain(cache, final_directory=True)
    if stat.S_IMODE(cache.lstat().st_mode) != 0o700:
        raise RepositoryRecoveryError("closed rebuild cache mode is not 0700")
    source_inventory = _captured_source_inventory(
        repository,
        str(project["source_package"]),
    )
    managed = _managed_python_contract()
    return {
        "cache_path": str(cache),
        "distribution_name": project["distribution_name"],
        "editable": False,
        "environment_relative": _CLOSED_REBUILD_ENVIRONMENT,
        "frozen": True,
        "import_name": project["import_name"],
        "lock_sha256": _sha256(_read_regular(lockfile)),
        "managed_python": managed,
        "network_allowed": False,
        "project_relative": _CLOSED_REBUILD_PROJECT,
        "pyproject_sha256": _sha256(_read_regular(pyproject)),
        "repository_id": repository_id,
        "schema_version": _CLOSED_REBUILD_SCHEMA,
        "source_inventory_sha256": _sha256(
            canonical_json_bytes(source_inventory)
        ),
        "source_package_relative": project["source_package"],
        "uv_path": str(uv),
        "uv_sha256": _sha256(_read_regular(uv)),
        "write_root_relative": _CLOSED_REBUILD_ROOT,
    }


def _tracked_git_identity(identity: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in identity.items()
        if key != "deliberate_exclusions"
    }


def _paths_within_roots(paths: list[str], roots: list[str]) -> bool:
    root_paths = [PurePosixPath(root) for root in roots]
    for raw in paths:
        normalized = _safe_relative(raw[:-1] if raw.endswith("/") else raw)
        path = PurePosixPath(normalized)
        if not any(path == root or root in path.parents for root in root_paths):
            return False
    return True


def _bounded_write_inventory(
    repository: Path,
    roots: list[str],
    managed_python: dict[str, object],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    total_bytes = 0
    managed_path_raw = managed_python.get("path")
    managed_resolved_raw = managed_python.get("resolved_path")
    managed_sha256 = managed_python.get("sha256")
    managed_version = managed_python.get("version")
    if (
        not isinstance(managed_path_raw, str)
        or not Path(managed_path_raw).is_absolute()
        or not isinstance(managed_resolved_raw, str)
        or not Path(managed_resolved_raw).is_absolute()
        or not _is_sha256(managed_sha256)
        or managed_version != "3.11"
    ):
        raise RepositoryRecoveryError("invalid managed interpreter contract")
    managed_path = Path(managed_path_raw)
    managed_resolved = Path(managed_resolved_raw)
    if (
        managed_path.resolve(strict=True) != managed_resolved
        or managed_resolved.is_symlink()
        or not managed_resolved.is_file()
        or _sha256(_read_regular(managed_resolved)) != managed_sha256
    ):
        raise RepositoryRecoveryError("managed interpreter identity mismatch")
    write_roots = [repository / root for root in roots]
    allowed_link_paths = {
        repository / _CLOSED_REBUILD_ENVIRONMENT / "bin" / "python",
        repository / _CLOSED_REBUILD_ENVIRONMENT / "bin" / "python3",
        repository / _CLOSED_REBUILD_ENVIRONMENT / "bin" / "python3.11",
    }

    def within_write_root(candidate: Path) -> bool:
        return any(
            candidate == root or root in candidate.parents
            for root in write_roots
        )

    def symlink_final_target(path: Path, link_text: str) -> Path:
        if path not in allowed_link_paths:
            raise RepositoryRecoveryError(
                "rehearsal symlink path is not managed"
            )
        current_link = path
        current_text = link_text
        seen: set[Path] = set()
        while True:
            if current_link in seen:
                raise RepositoryRecoveryError("rehearsal symlink cycle is forbidden")
            seen.add(current_link)
            if os.path.isabs(current_text):
                candidate = Path(os.path.abspath(current_text))
                if candidate != managed_path:
                    raise RepositoryRecoveryError(
                        "absolute rehearsal symlink target is not managed"
                    )
            else:
                candidate = Path(
                    os.path.abspath(current_link.parent / current_text)
                )
                if not within_write_root(candidate):
                    raise RepositoryRecoveryError(
                        "rehearsal symlink escapes managed write root"
                    )
            try:
                metadata = candidate.lstat()
            except FileNotFoundError as exc:
                raise RepositoryRecoveryError(
                    "dangling rehearsal symlink is forbidden"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                current_link = candidate
                current_text = os.readlink(candidate)
                continue
            if (
                candidate.resolve(strict=True) != managed_resolved
                or not stat.S_ISREG(metadata.st_mode)
                or _sha256(_read_regular(managed_resolved)) != managed_sha256
            ):
                raise RepositoryRecoveryError(
                    "rehearsal symlink final target is not managed"
                )
            return managed_resolved

    def record(path: Path, relative: str, metadata: os.stat_result) -> None:
        nonlocal total_bytes
        if stat.S_ISLNK(metadata.st_mode):
            link_text = os.readlink(path)
            link_bytes = os.fsencode(link_text)
            resolved_target = symlink_final_target(path, link_text)
            entry = {
                "link_text": link_text,
                "mode": stat.S_IMODE(metadata.st_mode),
                "path": relative,
                "resolved_target": str(resolved_target),
                "sha256": _sha256(link_bytes),
                "size": len(link_bytes),
                "type": "symlink",
            }
        elif stat.S_ISDIR(metadata.st_mode):
            entry = {
                "mode": stat.S_IMODE(metadata.st_mode),
                "path": relative,
                "sha256": _sha256(b""),
                "size": 0,
                "type": "directory",
            }
        elif stat.S_ISREG(metadata.st_mode):
            total_bytes += metadata.st_size
            if total_bytes > _MAX_REHEARSAL_BYTES:
                raise RepositoryRecoveryError(
                    "rehearsal write inventory exceeds max_bytes"
                )
            payload = _read_regular(path)
            entry = {
                "mode": stat.S_IMODE(metadata.st_mode),
                "path": relative,
                "sha256": _sha256(payload),
                "size": len(payload),
                "type": "file",
            }
        else:
            raise RepositoryRecoveryError(
                "special file in rehearsal write inventory is forbidden"
            )
        entries.append(entry)
        if len(entries) > _MAX_REHEARSAL_FILES:
            raise RepositoryRecoveryError(
                "rehearsal write inventory exceeds max_files"
            )

    def walk(directory: Path, relative: PurePosixPath) -> None:
        try:
            with os.scandir(directory) as iterator:
                children = sorted(
                    iterator,
                    key=lambda child: child.name.encode("utf-8"),
                )
        except OSError as exc:
            raise RepositoryRecoveryError(
                "cannot enumerate rehearsal write root"
            ) from exc
        for child in children:
            child_path = Path(child.path)
            child_relative = relative / child.name
            metadata = child.stat(follow_symlinks=False)
            record(child_path, child_relative.as_posix(), metadata)
            if stat.S_ISDIR(metadata.st_mode):
                walk(child_path, child_relative)

    for relative_root in roots:
        root = repository / relative_root
        if not root.exists() and not root.is_symlink():
            continue
        metadata = root.lstat()
        record(root, relative_root, metadata)
        if stat.S_ISDIR(metadata.st_mode):
            walk(root, PurePosixPath(relative_root))
    entries.sort(key=lambda entry: str(entry["path"]).encode("utf-8"))
    return entries


def _sandbox_profile(allowed_roots: list[Path]) -> str:
    def literal(path: Path) -> str:
        raw = str(path)
        if any(character in raw for character in ('"', "\\", "\x00", "\n", "\r")):
            raise RepositoryRecoveryError("unsafe sandbox path")
        return f'(literal "{raw}")'

    rules = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
    ]
    for root in allowed_roots:
        rules.append(f"(allow file-write* {literal(root)})")
        rules.append(f'(allow file-write* (subpath "{root}"))')
    return "\n".join(rules) + "\n"


def _sandbox_run(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    profile: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    sandbox_argv = ["/usr/bin/sandbox-exec", "-p", profile, *argv]
    process = subprocess.Popen(
        sandbox_argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return subprocess.CompletedProcess(
            sandbox_argv,
            process.returncode,
            stdout,
            stderr,
        )
    except subprocess.TimeoutExpired:
        process_group_id = process.pid
        argv_sha256 = _sha256(canonical_json_bytes(sandbox_argv))
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass
        stdout = b""
        stderr = b""
        communicate_completed = False
        try:
            stdout, stderr = process.communicate(
                timeout=_TIMEOUT_TERM_GRACE_SECONDS
            )
            communicate_completed = True
        except subprocess.TimeoutExpired:
            pass
        deadline = time.monotonic() + _TIMEOUT_TERM_GRACE_SECONDS
        process_group_gone = False
        while time.monotonic() < deadline:
            try:
                os.killpg(process_group_id, 0)
            except ProcessLookupError:
                process_group_gone = True
                break
            time.sleep(0.025)
        if not process_group_gone:
            raise RepositoryRecoveryError(
                "timed-out recovery process group survived TERM "
                f"pgid={process_group_id} argv_sha256={argv_sha256}"
            )
        if not communicate_completed:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
            except subprocess.TimeoutExpired as exc:
                raise RepositoryRecoveryError(
                    "timed-out recovery leader was not reaped after group exit "
                    f"pgid={process_group_id} argv_sha256={argv_sha256}"
                ) from exc
        return subprocess.CompletedProcess(
            sandbox_argv,
            124,
            stdout,
            stderr + b"\nrepository recovery command timed out\n",
        )


def _sandbox_preflight(
    *,
    destination: Path,
    environment: dict[str, str],
    profile: str,
) -> dict[str, object]:
    write_probe = destination.parent / f".{destination.name}.sandbox-write-probe"
    if write_probe.exists() or write_probe.is_symlink():
        raise RepositoryRecoveryError("sandbox write probe path already exists")
    write_result = _sandbox_run(
        ["/usr/bin/touch", str(write_probe)],
        cwd=destination,
        environment=environment,
        profile=profile,
        timeout_seconds=_SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
    )
    write_denied = write_result.returncode != 0 and not write_probe.exists()
    network_result = _sandbox_run(
        [
            "/usr/bin/python3",
            "-c",
            (
                "import socket,sys; s=socket.socket();\n"
                "try: s.connect(('127.0.0.1',9))\n"
                "except PermissionError: sys.exit(77)\n"
                "except OSError: sys.exit(0)\n"
                "sys.exit(0)"
            ),
        ],
        cwd=destination,
        environment=environment,
        profile=profile,
        timeout_seconds=_SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
    )
    network_denied = network_result.returncode == 77
    result = {
        "network_denied": network_denied,
        "network_exit_code": network_result.returncode,
        "network_stderr_sha256": _sha256(network_result.stderr),
        "network_stdout_sha256": _sha256(network_result.stdout),
        "write_denied": write_denied,
        "write_exit_code": write_result.returncode,
        "write_probe_path": str(write_probe),
        "write_stderr_sha256": _sha256(write_result.stderr),
        "write_stdout_sha256": _sha256(write_result.stdout),
    }
    if not write_denied or not network_denied:
        raise RepositoryRecoveryError("sandbox preflight did not deny capabilities")
    return result


def _copy_closed_rebuild_project(
    destination: Path,
    spec: dict[str, object],
) -> None:
    write_root = destination / str(spec["write_root_relative"])
    project = destination / str(spec["project_relative"])
    write_root.mkdir(mode=0o700)
    project.mkdir(mode=0o700)

    def copy_tree(source: Path, target: Path) -> None:
        target.mkdir(mode=0o700, exist_ok=True)
        with os.scandir(source) as iterator:
            children = sorted(
                iterator,
                key=lambda child: child.name.encode("utf-8"),
            )
        for child in children:
            source_path = Path(child.path)
            target_path = target / child.name
            metadata = child.stat(follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise RepositoryRecoveryError(
                    "symlink in closed rebuild source is forbidden"
                )
            if stat.S_ISDIR(metadata.st_mode):
                copy_tree(source_path, target_path)
            elif stat.S_ISREG(metadata.st_mode):
                _write_once(
                    target_path,
                    _read_regular(source_path),
                    mode=stat.S_IMODE(metadata.st_mode),
                )
            else:
                raise RepositoryRecoveryError(
                    "special file in closed rebuild source is forbidden"
                )

    for name in ("pyproject.toml", "uv.lock"):
        source = _validate_existing_chain(
            destination / name, final_directory=False
        )
        _write_once(
            project / name,
            _read_regular(source),
            mode=stat.S_IMODE(source.lstat().st_mode),
        )
    readme = destination / "README.md"
    if readme.exists() and not readme.is_symlink():
        readme = _validate_existing_chain(readme, final_directory=False)
        _write_once(
            project / "README.md",
            _read_regular(readme),
            mode=stat.S_IMODE(readme.lstat().st_mode),
        )
    build_backend = destination / "build_backend.py"
    if build_backend.exists() and not build_backend.is_symlink():
        build_backend = _validate_existing_chain(
            build_backend, final_directory=False
        )
        _write_once(
            project / "build_backend.py",
            _read_regular(build_backend),
            mode=stat.S_IMODE(build_backend.lstat().st_mode),
        )
    source_relative = str(spec["source_package_relative"])
    copy_tree(
        _validate_existing_chain(
            destination / source_relative, final_directory=True
        ),
        project / source_relative,
    )


def _closed_rebuild_argv(
    destination: Path,
    spec: dict[str, object],
) -> list[str]:
    managed = spec["managed_python"]
    if not isinstance(managed, dict):
        raise RepositoryRecoveryError("invalid managed interpreter contract")
    return [
        str(spec["uv_path"]),
        "sync",
        "--frozen",
        "--offline",
        "--no-python-downloads",
        "--extra",
        "dev",
        "--no-editable",
        "--cache-dir",
        str(spec["cache_path"]),
        "--python",
        str(managed["path"]),
        "--project",
        str(destination / str(spec["project_relative"])),
    ]


def _inspect_closed_rebuild(
    destination: Path,
    spec: dict[str, object],
) -> tuple[dict[str, object], subprocess.CompletedProcess[bytes]]:
    environment_root = destination / str(spec["environment_relative"])
    environment_python = environment_root / "bin" / "python"
    distribution_root = _validate_existing_chain(
        environment_root / "lib" / "python3.11" / "site-packages",
        final_directory=True,
    )
    pth_files: list[dict[str, object]] = []
    unsafe_pth_lines: list[str] = []
    for pth in sorted(
        distribution_root.glob("*.pth"),
        key=lambda path: path.name.encode("utf-8"),
    ):
        if pth.is_symlink() or not pth.is_file():
            raise RepositoryRecoveryError(
                "unsafe pth member in closed rebuild environment"
            )
        payload = _read_regular(pth)
        try:
            meaningful_lines = [
                line.strip()
                for line in payload.decode("utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        except UnicodeDecodeError as exc:
            raise RepositoryRecoveryError(
                "unsafe pth member in closed rebuild environment"
            ) from exc
        bootstrap_pth = (
            pth.name == "_virtualenv.pth"
            and payload == _CLOSED_REBUILD_VIRTUALENV_PTH
        )
        if meaningful_lines and not bootstrap_pth:
            unsafe_pth_lines.extend(
                f"{pth.name}:{line}" for line in meaningful_lines
            )
        pth_files.append(
            {
                "bootstrap": bootstrap_pth,
                "path": pth.name,
                "sha256": _sha256(payload),
            }
        )
    if unsafe_pth_lines:
        raise RepositoryRecoveryError(
            "unsafe pth member in closed rebuild environment"
        )
    egg_links = sorted(
        path.name for path in distribution_root.glob("*.egg-link")
    )
    if egg_links:
        raise RepositoryRecoveryError(
            "unsafe egg-link member in closed rebuild environment"
        )
    probe = (
        "import importlib.metadata as m,importlib.util as u,json,pathlib,sys;"
        "site=pathlib.Path(sys.argv[3]);sys.path.insert(0,str(site));"
        "mod=u.find_spec(sys.argv[1]);"
        "dist=m.distribution(sys.argv[2]);"
        "du=dist.locate_file(next(f for f in dist.files "
        "if str(f).endswith('.dist-info/direct_url.json')));"
        "print(json.dumps({'sys_executable':sys.executable,"
        "'base_executable':sys._base_executable,"
        "'python_version':list(sys.version_info[:2]),"
        "'module_file':None if mod is None else mod.origin,"
        "'distribution_root':str(dist.locate_file('')),"
        "'distribution_version':dist.version,'direct_url_path':str(du),"
        "'direct_url':json.loads(du.read_text())},sort_keys=True,separators=(',',':')))"
    )
    probe_environment = {
        "LANG": os.environ.get("LANG", "C"),
        "LC_ALL": os.environ.get("LC_ALL", "C"),
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    probe_profile = _sandbox_profile([])
    result = _sandbox_run(
        [
            str(environment_python),
            "-I",
            "-S",
            "-c",
            probe,
            str(spec["import_name"]),
            str(spec["distribution_name"]),
            str(distribution_root),
        ],
        cwd=destination,
        environment=probe_environment,
        profile=probe_profile,
        timeout_seconds=_CLOSED_REBUILD_PROBE_TIMEOUT_SECONDS,
    )
    try:
        observation = json.loads(result.stdout) if result.returncode == 0 else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryRecoveryError(
            "closed rebuild probe output is invalid"
        ) from exc
    if not isinstance(observation, dict):
        raise RepositoryRecoveryError("closed rebuild probe output is invalid")
    source_root = destination / str(spec["source_package_relative"])
    copied_root = (
        destination
        / str(spec["project_relative"])
        / str(spec["source_package_relative"])
    )
    source_inventory = _regular_tree_inventory(source_root)
    copied_inventory = _regular_tree_inventory(copied_root)
    module_file_raw = observation.get("module_file")
    distribution_root_raw = observation.get("distribution_root")
    if (
        not isinstance(module_file_raw, str)
        or not isinstance(distribution_root_raw, str)
    ):
        installed_inventory: list[dict[str, object]] = []
        installed_root = Path("/")
    else:
        module_file = Path(module_file_raw)
        installed_root = module_file.parent
        installed_inventory = []
        for entry in source_inventory:
            relative = _safe_relative(str(entry["path"]))
            installed = installed_root / relative
            if (
                installed.is_symlink()
                or not installed.is_file()
                or _sha256(_read_regular(installed)) != entry["sha256"]
            ):
                raise RepositoryRecoveryError(
                    "closed rebuild installed source hash mismatch"
                )
            installed_inventory.append(
                {
                    "path": relative,
                    "sha256": entry["sha256"],
                    "size": entry["size"],
                }
            )
    direct_url = observation.get("direct_url")
    expected_project_url = (
        destination / str(spec["project_relative"])
    ).as_uri()
    environment_python_text = str(environment_python)
    managed = spec.get("managed_python")
    base_executable_raw = observation.get("base_executable")
    base_executable_matches = False
    if isinstance(managed, dict) and isinstance(base_executable_raw, str):
        try:
            base_executable = Path(base_executable_raw).resolve(strict=True)
        except (OSError, RuntimeError):
            base_executable = Path("/")
        base_executable_matches = (
            base_executable == Path(str(managed.get("resolved_path")))
            and base_executable.is_file()
            and _sha256(_read_regular(base_executable))
            == managed.get("sha256")
        )
    verified = (
        result.returncode == 0
        and observation.get("sys_executable") == environment_python_text
        and observation.get("python_version") == [3, 11]
        and base_executable_matches
        and isinstance(module_file_raw, str)
        and environment_root in Path(module_file_raw).parents
        and Path(module_file_raw).is_file()
        and isinstance(distribution_root_raw, str)
        and Path(distribution_root_raw) == distribution_root
        and isinstance(direct_url, dict)
        and direct_url.get("url") == expected_project_url
        and direct_url.get("dir_info") == {"editable": False}
        and source_inventory == copied_inventory
        and source_inventory == installed_inventory
        and _sha256(canonical_json_bytes(source_inventory))
        == spec.get("source_inventory_sha256")
    )
    proof = {
        "base_executable": base_executable_raw,
        "direct_url": direct_url,
        "direct_url_path": observation.get("direct_url_path"),
        "distribution_root": distribution_root_raw,
        "distribution_version": observation.get("distribution_version"),
        "editable_pth_lines": unsafe_pth_lines,
        "egg_links": egg_links,
        "environment_python": environment_python_text,
        "installed_inventory_sha256": _sha256(
            canonical_json_bytes(installed_inventory)
        ),
        "module_file": module_file_raw,
        "probe_exit_code": result.returncode,
        "probe_timed_out": result.returncode == 124,
        "probe_sandbox_profile_sha256": _sha256(
            probe_profile.encode("utf-8")
        ),
        "probe_stderr_sha256": _sha256(result.stderr),
        "probe_stdout_sha256": _sha256(result.stdout),
        "pth_files": pth_files,
        "python_version": observation.get("python_version"),
        "source_copy_inventory_sha256": _sha256(
            canonical_json_bytes(copied_inventory)
        ),
        "source_inventory_sha256": _sha256(
            canonical_json_bytes(source_inventory)
        ),
        "verified": verified,
    }
    return proof, result


def _validate_closed_rebuild_spec(
    spec: dict[str, object],
    *,
    destination: Path,
    expected_cache_path: Path,
    protected_paths: Sequence[Path],
) -> None:
    required = {
        "cache_path",
        "distribution_name",
        "editable",
        "environment_relative",
        "frozen",
        "import_name",
        "lock_sha256",
        "managed_python",
        "network_allowed",
        "project_relative",
        "pyproject_sha256",
        "repository_id",
        "schema_version",
        "source_inventory_sha256",
        "source_package_relative",
        "uv_path",
        "uv_sha256",
        "write_root_relative",
    }
    repository_id = spec.get("repository_id")
    project = (
        _CLOSED_REBUILD_PROJECTS.get(repository_id)
        if isinstance(repository_id, str)
        else None
    )
    managed = spec.get("managed_python")
    if (
        set(spec) != required
        or spec.get("schema_version") != _CLOSED_REBUILD_SCHEMA
        or project is None
        or spec.get("distribution_name") != project["distribution_name"]
        or spec.get("import_name") != project["import_name"]
        or spec.get("source_package_relative") != project["source_package"]
        or spec.get("write_root_relative") != _CLOSED_REBUILD_ROOT
        or spec.get("project_relative") != _CLOSED_REBUILD_PROJECT
        or spec.get("environment_relative") != _CLOSED_REBUILD_ENVIRONMENT
        or spec.get("frozen") is not True
        or spec.get("editable") is not False
        or spec.get("network_allowed") is not False
        or not isinstance(managed, dict)
        or set(managed) != {"path", "resolved_path", "sha256", "version"}
        or managed.get("version") != "3.11"
        or not isinstance(managed.get("path"), str)
        or not Path(str(managed.get("path"))).is_absolute()
        or not isinstance(managed.get("resolved_path"), str)
        or not Path(str(managed.get("resolved_path"))).is_absolute()
        or not _is_sha256(managed.get("sha256"))
        or not _is_sha256(spec.get("uv_sha256"))
        or not _is_sha256(spec.get("pyproject_sha256"))
        or not _is_sha256(spec.get("lock_sha256"))
        or not _is_sha256(spec.get("source_inventory_sha256"))
    ):
        raise RepositoryRecoveryError("invalid embedded closed rebuild spec")
    try:
        uv = _UV_EXECUTABLE.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryRecoveryError(
            "closed rebuild uv executable cannot be resolved"
        ) from exc
    live_managed = _managed_python_contract()
    managed_path = Path(str(managed["path"]))
    managed_resolved = Path(str(managed["resolved_path"]))
    managed_root = (
        Path.home() / ".local" / "share" / "uv" / "python"
    ).resolve(strict=True)
    embedded_cache = Path(str(spec["cache_path"]))
    expected_cache = _validate_existing_chain(
        expected_cache_path, final_directory=True
    )
    cache_overlaps_protected = any(
        expected_cache == protected
        or expected_cache in protected.parents
        or protected in expected_cache.parents
        for protected in protected_paths
    )
    if (
        not embedded_cache.is_absolute()
        or str(embedded_cache) != str(expected_cache)
        or cache_overlaps_protected
    ):
        raise RepositoryRecoveryError(
            "closed rebuild cache authority mismatch"
        )
    cache = expected_cache
    source = _validate_existing_chain(
        destination / str(spec["source_package_relative"]),
        final_directory=True,
    )
    if (
        spec.get("uv_path") != str(uv)
        or _sha256(_read_regular(uv)) != spec["uv_sha256"]
        or managed != live_managed
        or managed_path.resolve(strict=True) != managed_resolved
        or managed_root not in managed_resolved.parents
        or managed_resolved.is_symlink()
        or not managed_resolved.is_file()
        or _sha256(_read_regular(managed_resolved)) != managed["sha256"]
        or stat.S_IMODE(cache.lstat().st_mode) != 0o700
        or _sha256(_read_regular(destination / "pyproject.toml"))
        != spec["pyproject_sha256"]
        or _sha256(_read_regular(destination / "uv.lock"))
        != spec["lock_sha256"]
        or _sha256(canonical_json_bytes(_regular_tree_inventory(source)))
        != spec["source_inventory_sha256"]
    ):
        raise RepositoryRecoveryError("closed rebuild authority mismatch")


def _closure_rehearse_closed_rebuild(
    destination: Path,
    spec: dict[str, object],
    *,
    enabled: bool,
    expected_cache_path: Path,
    protected_paths: Sequence[Path],
) -> dict[str, object]:
    spec_payload = canonical_json_bytes(spec)
    spec_sha256 = _sha256(spec_payload)
    _validate_closed_rebuild_spec(
        spec,
        destination=destination,
        expected_cache_path=expected_cache_path,
        protected_paths=protected_paths,
    )
    write_roots = [str(spec["write_root_relative"])]
    materialized_write_roots = [destination / write_roots[0]]
    managed = spec["managed_python"]
    if not isinstance(managed, dict):
        raise RepositoryRecoveryError("invalid managed interpreter contract")
    if not enabled:
        return {
            "argv": [],
            "command_exit_code": None,
            "command_timed_out": False,
            "command_timeout_seconds": _CLOSED_REBUILD_COMMAND_TIMEOUT_SECONDS,
            "enabled": False,
            "input_bytes": len(spec_payload),
            "input_path": None,
            "input_sha256": spec_sha256,
            "network_allowed": False,
            "probe_timeout_seconds": _CLOSED_REBUILD_PROBE_TIMEOUT_SECONDS,
            "rebuild_proof": None,
            "required_paths_present": False,
            "side_effect_classification": "environment_rebuild",
            "state_changed": False,
        }
    environment = {
        "LANG": os.environ.get("LANG", "C"),
        "LC_ALL": os.environ.get("LC_ALL", "C"),
        "PATH": os.environ.get("PATH", os.defpath),
        "UV_PROJECT_ENVIRONMENT": str(
            destination / str(spec["environment_relative"])
        ),
    }
    cache = expected_cache_path
    profile = _sandbox_profile([*materialized_write_roots, cache])
    sandbox_preflight = _sandbox_preflight(
        destination=destination,
        environment=environment,
        profile=profile,
    )
    before = repository_identity(destination)
    tracked_before = _tracked_git_identity(before)
    inventory_before = _bounded_write_inventory(
        destination, write_roots, managed
    )
    _copy_closed_rebuild_project(destination, spec)
    argv = _closed_rebuild_argv(destination, spec)
    result = _sandbox_run(
        argv,
        cwd=destination,
        environment=environment,
        profile=profile,
        timeout_seconds=_CLOSED_REBUILD_COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        rebuild_proof, _probe_result = _inspect_closed_rebuild(
            destination, spec
        )
    else:
        rebuild_proof = {
            "probe_exit_code": None,
            "probe_timed_out": False,
            "verified": False,
        }
    after = repository_identity(destination)
    tracked_after = _tracked_git_identity(after)
    inventory_after = _bounded_write_inventory(
        destination, write_roots, managed
    )
    tracked_unchanged = tracked_before == tracked_after
    before_exclusions = before["deliberate_exclusions"]
    after_exclusions = after["deliberate_exclusions"]
    if not isinstance(before_exclusions, dict) or not isinstance(
        after_exclusions, dict
    ):
        raise RepositoryRecoveryError("invalid deliberate exclusion inventory")
    before_paths = before_exclusions.get("paths")
    after_paths = after_exclusions.get("paths")
    if not isinstance(before_paths, list) or not isinstance(after_paths, list):
        raise RepositoryRecoveryError("invalid deliberate exclusion inventory")
    ignored_paths_changed = sorted(
        set(before_paths).symmetric_difference(after_paths),
        key=lambda value: value.encode("utf-8"),
    )
    write_scope_respected = _paths_within_roots(
        ignored_paths_changed, write_roots
    )
    required_paths_present = (
        result.returncode == 0
        and rebuild_proof["verified"] is True
    )
    return {
        "argv": argv,
        "cache_path": str(cache),
        "command_exit_code": result.returncode,
        "command_timed_out": result.returncode == 124,
        "command_timeout_seconds": _CLOSED_REBUILD_COMMAND_TIMEOUT_SECONDS,
        "cwd": str(destination),
        "enabled": True,
        "environment_names": sorted(environment),
        "executable_path": str(spec["uv_path"]),
        "executable_sha256": spec["uv_sha256"],
        "expected_exit_code": 0,
        "ignored_paths_changed": ignored_paths_changed,
        "input_bytes": len(spec_payload),
        "input_path": None,
        "input_sha256": spec_sha256,
        "managed_python": managed,
        "network_allowed": False,
        "probe_timeout_seconds": _CLOSED_REBUILD_PROBE_TIMEOUT_SECONDS,
        "rebuild_proof": rebuild_proof,
        "required_paths_present": required_paths_present,
        "sandbox_executable_path": "/usr/bin/sandbox-exec",
        "sandbox_executable_sha256": _sha256(
            _read_regular(Path("/usr/bin/sandbox-exec"))
        ),
        "sandbox_preflight": sandbox_preflight,
        "sandbox_profile_sha256": _sha256(profile.encode("utf-8")),
        "side_effect_classification": "environment_rebuild",
        "state_changed": inventory_before != inventory_after,
        "stderr_sha256": _sha256(result.stderr),
        "stdout_sha256": _sha256(result.stdout),
        "tracked_git_identity_after_sha256": _sha256(
            canonical_json_bytes(tracked_after)
        ),
        "tracked_git_identity_before_sha256": _sha256(
            canonical_json_bytes(tracked_before)
        ),
        "tracked_git_identity_unchanged": tracked_unchanged,
        "write_inventory_after": inventory_after,
        "write_inventory_after_sha256": _sha256(
            canonical_json_bytes(inventory_after)
        ),
        "write_inventory_before": inventory_before,
        "write_inventory_before_sha256": _sha256(
            canonical_json_bytes(inventory_before)
        ),
        "write_inventory_bounds": {
            "max_bytes": _MAX_REHEARSAL_BYTES,
            "max_files": _MAX_REHEARSAL_FILES,
        },
        "write_root": str(materialized_write_roots[0]),
        "write_scope_respected": write_scope_respected,
    }


def _closed_rebuild_rehearsal_verified(
    rehearsal: dict[str, object],
    *,
    spec: dict[str, object],
    destination: Path,
    expected_cache_path: Path,
    protected_paths: Sequence[Path],
) -> bool:
    _validate_closed_rebuild_spec(
        spec,
        destination=destination,
        expected_cache_path=expected_cache_path,
        protected_paths=protected_paths,
    )
    spec_payload = canonical_json_bytes(spec)
    managed = spec["managed_python"]
    if not isinstance(managed, dict):
        raise RepositoryRecoveryError("invalid managed interpreter contract")
    if rehearsal.get("input_sha256") != _sha256(spec_payload):
        raise RepositoryRecoveryError("closed rebuild input digest mismatch")
    if rehearsal.get("enabled") is False:
        if (
            rehearsal.get("command_exit_code") is not None
            or rehearsal.get("required_paths_present") is not False
            or rehearsal.get("state_changed") is not False
            or rehearsal.get("rebuild_proof") is not None
        ):
            raise RepositoryRecoveryError(
                "disabled closed rebuild receipt is invalid"
            )
        return False
    cache = expected_cache_path
    write_root = destination / str(spec["write_root_relative"])
    expected_argv = _closed_rebuild_argv(destination, spec)
    expected_profile = _sandbox_profile([write_root, cache])
    inventory_before = rehearsal.get("write_inventory_before")
    inventory_after = rehearsal.get("write_inventory_after")
    ignored_paths_changed = rehearsal.get("ignored_paths_changed")
    if (
        rehearsal.get("argv") != expected_argv
        or rehearsal.get("cache_path") != str(cache)
        or rehearsal.get("cwd") != str(destination)
        or rehearsal.get("environment_names")
        != ["LANG", "LC_ALL", "PATH", "UV_PROJECT_ENVIRONMENT"]
        or rehearsal.get("executable_path") != spec["uv_path"]
        or rehearsal.get("executable_sha256") != spec["uv_sha256"]
        or rehearsal.get("expected_exit_code") != 0
        or rehearsal.get("input_bytes") != len(spec_payload)
        or rehearsal.get("input_path") is not None
        or rehearsal.get("managed_python") != managed
        or rehearsal.get("network_allowed") is not False
        or rehearsal.get("command_timeout_seconds")
        != _CLOSED_REBUILD_COMMAND_TIMEOUT_SECONDS
        or rehearsal.get("probe_timeout_seconds")
        != _CLOSED_REBUILD_PROBE_TIMEOUT_SECONDS
        or rehearsal.get("command_timed_out")
        is not (rehearsal.get("command_exit_code") == 124)
        or rehearsal.get("sandbox_executable_path") != "/usr/bin/sandbox-exec"
        or rehearsal.get("sandbox_executable_sha256")
        != _sha256(_read_regular(Path("/usr/bin/sandbox-exec")))
        or rehearsal.get("sandbox_profile_sha256")
        != _sha256(expected_profile.encode("utf-8"))
        or rehearsal.get("side_effect_classification")
        != "environment_rebuild"
        or rehearsal.get("write_root") != str(write_root)
        or not isinstance(inventory_before, list)
        or not isinstance(inventory_after, list)
        or rehearsal.get("write_inventory_before_sha256")
        != _sha256(canonical_json_bytes(inventory_before))
        or rehearsal.get("write_inventory_after_sha256")
        != _sha256(canonical_json_bytes(inventory_after))
        or rehearsal.get("write_inventory_bounds")
        != {
            "max_bytes": _MAX_REHEARSAL_BYTES,
            "max_files": _MAX_REHEARSAL_FILES,
        }
        or not isinstance(ignored_paths_changed, list)
        or not all(isinstance(value, str) for value in ignored_paths_changed)
    ):
        raise RepositoryRecoveryError("invalid closed rebuild receipt")
    preflight = rehearsal.get("sandbox_preflight")
    if (
        not isinstance(preflight, dict)
        or preflight.get("write_denied") is not True
        or preflight.get("network_denied") is not True
        or preflight.get("write_exit_code") == 0
        or preflight.get("network_exit_code") != 77
    ):
        raise RepositoryRecoveryError("closed rebuild sandbox proof is invalid")
    live_inventory = _bounded_write_inventory(
        destination,
        [str(spec["write_root_relative"])],
        managed,
    )
    if live_inventory != inventory_after:
        raise RepositoryRecoveryError(
            "closed rebuild environment inventory drifted"
        )
    inventory_changed = inventory_before != inventory_after
    if rehearsal.get("state_changed") is not inventory_changed:
        raise RepositoryRecoveryError(
            "closed rebuild inventory state mismatch"
        )
    tracked_before = rehearsal.get("tracked_git_identity_before_sha256")
    tracked_after = rehearsal.get("tracked_git_identity_after_sha256")
    tracked_unchanged = (
        _is_sha256(tracked_before)
        and _is_sha256(tracked_after)
        and tracked_before == tracked_after
    )
    if rehearsal.get("tracked_git_identity_unchanged") is not tracked_unchanged:
        raise RepositoryRecoveryError(
            "closed rebuild tracked identity mismatch"
        )
    write_scope_respected = _paths_within_roots(
        ignored_paths_changed,
        [str(spec["write_root_relative"])],
    )
    if rehearsal.get("write_scope_respected") is not write_scope_respected:
        raise RepositoryRecoveryError("closed rebuild write scope mismatch")
    recorded_proof = rehearsal.get("rebuild_proof")
    if not isinstance(recorded_proof, dict):
        raise RepositoryRecoveryError("invalid closed rebuild proof")
    if rehearsal.get("command_exit_code") != 0:
        if (
            rehearsal.get("required_paths_present") is not False
            or recorded_proof.get("verified") is not False
            or recorded_proof.get("probe_exit_code") is not None
        ):
            raise RepositoryRecoveryError(
                "failed closed rebuild receipt is invalid"
            )
        return False
    live_proof, _probe = _inspect_closed_rebuild(destination, spec)
    if recorded_proof != live_proof:
        raise RepositoryRecoveryError("closed rebuild proof drifted")
    required_paths_present = live_proof.get("verified") is True
    if (
        rehearsal.get("required_paths_present")
        is not required_paths_present
    ):
        raise RepositoryRecoveryError(
            "closed rebuild required-path proof mismatch"
        )
    computed = (
        rehearsal.get("command_exit_code") == 0
        and inventory_changed
        and tracked_unchanged
        and write_scope_respected
        and rehearsal.get("required_paths_present") is True
        and live_proof.get("verified") is True
    )
    return computed


def capture_and_drill_closure_repository(
    repository: Path,
    package: Path,
    first_destination: Path,
    second_destination: Path,
    rehearsal_patch: Path | None,
    *,
    rehearsal_patch_sha256: str | None,
    rehearsal_rebuild: bool = False,
    rehearsal_command_spec: Path | None = None,
    rehearsal_command_spec_sha256: str | None = None,
    repository_id: str,
    publication_url: str,
    publication_remote_name: str,
    operator_identity: str,
) -> dict[str, object]:
    """Capture Section 4.1 artifacts, rehearse one mutation, and restore twice."""

    repository = _validate_existing_chain(Path(repository), final_directory=True)
    package = _validate_new_path(Path(package))
    first_destination = _validate_new_path(Path(first_destination))
    second_destination = _validate_new_path(Path(second_destination))
    patch_mode = (
        rehearsal_patch is not None or rehearsal_patch_sha256 is not None
    )
    legacy_command_mode = (
        rehearsal_command_spec is not None
        or rehearsal_command_spec_sha256 is not None
    )
    if legacy_command_mode:
        raise RepositoryRecoveryError(
            "caller-authored rehearsal command specs are forbidden"
        )
    if patch_mode:
        raise RepositoryRecoveryError(
            "patch rehearsals cannot certify release recovery"
        )
    if rehearsal_rebuild is not True:
        raise RepositoryRecoveryError(
            "closed rebuild rehearsal is required for release recovery"
        )
    if first_destination == second_destination:
        raise RepositoryRecoveryError(
            "closure restore destinations must be independent"
        )
    if (
        first_destination in second_destination.parents
        or second_destination in first_destination.parents
    ):
        raise RepositoryRecoveryError(
            "closure restore destinations must not overlap"
        )
    roots = _repository_roots(repository)
    for path, label in (
        (package, "closure recovery package"),
        (first_destination, "first closure restore"),
        (second_destination, "second closure restore"),
    ):
        _assert_disjoint(path, roots, label=label)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", repository_id):
        raise RepositoryRecoveryError("invalid closure repository ID")
    if (
        not operator_identity.strip()
        or operator_identity != operator_identity.strip()
        or any(ord(character) < 32 for character in operator_identity)
    ):
        raise RepositoryRecoveryError("invalid closure operator identity")
    expected_publication_url = _normalize_remote(publication_url)
    if not publication_remote_name or any(
        ord(character) < 32 for character in publication_remote_name
    ):
        raise RepositoryRecoveryError("invalid publication remote name")
    observed_publication_url = (
        _git(repository, "remote", "get-url", publication_remote_name)
        .decode("utf-8", "strict")
        .strip()
    )
    if (
        _normalize_remote(observed_publication_url) != expected_publication_url
        or observed_publication_url != expected_publication_url
    ):
        raise RepositoryRecoveryError("publication remote URL mismatch")
    branch = (
        _git(repository, "symbolic-ref", "--short", "-q", "HEAD", check=False)
        .decode("utf-8", "strict")
        .strip()
    )
    if not branch:
        raise RepositoryRecoveryError("closure capture requires an attached HEAD")
    package.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    package.parent.chmod(0o700)
    first_destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    second_destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    closed_rebuild_spec = _closed_rebuild_spec(
        repository,
        package,
        repository_id=repository_id,
    )
    staging = package.with_name(f".{package.name}.staging")
    _assert_disjoint(staging, roots, label="closure recovery staging path")
    _restricted_directory(staging)
    try:
        untracked_capture_bounds = _untracked_capture_bounds(repository)
        before = repository_identity(repository)
        _create_bundle(repository, staging, before)
        refs = _closure_refs_text(repository)
        pseudo_refs = canonical_json_bytes(before["admin_files"])
        status = _git(
            repository,
            "status",
            "--porcelain=v2",
            "--branch",
            "-z",
            "--untracked-files=all",
        )
        index_path = Path(
            _git(
                repository,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "index",
            )
            .decode("utf-8", "strict")
            .strip()
        )
        index = _read_regular(index_path)
        stages = _closure_index_stages_text(repository)
        staged = _closure_staged_patch(repository)
        unstaged = _closure_unstaged_patch(repository)
        untracked = _tar_bytes(
            repository,
            list(before["untracked"]),  # type: ignore[arg-type]
        )
        worktrees = _closure_worktree_list(repository)
        submodules, submodule_exit, submodule_stderr = _closure_submodules(
            repository
        )
        artifacts = {
            "refs.txt": refs,
            "pseudo-refs.txt": pseudo_refs,
            "status-v2-z.bin": status,
            "index.bin": index,
            "index-stages.txt": stages,
            "staged.patch": staged,
            "unstaged.patch": unstaged,
            "untracked.tar": untracked,
            "worktree-list.txt": worktrees,
            "submodules.txt": submodules,
        }
        for name, payload in artifacts.items():
            _write_once(staging / name, payload)
        bundle_payload = _read_regular(staging / "bundle.bundle")
        identity = {
            "absolute_checkout_path": str(repository),
            "branch": branch,
            "capture_observations": {
                **{
                    name: _closure_observation(payload)
                    for name, payload in artifacts.items()
                },
                "bundle.bundle": _closure_observation(bundle_payload),
            },
            "capture_time": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "deliberate_exclusions": before["deliberate_exclusions"],
            "git_version": _run(
                ["git", "--version"], cwd=repository
            ).stdout.decode("utf-8", "strict").strip(),
            "head": before["head_object_id"],
            "mutable_identity": before,
            "object_format": before["object_format"],
            "operator_identity": operator_identity,
            "publication_remote_name": publication_remote_name,
            "publication_url": expected_publication_url,
            "rehearsal_input": {
                "document": closed_rebuild_spec,
                "kind": "closed_rebuild",
                "sha256": _sha256(
                    canonical_json_bytes(closed_rebuild_spec)
                ),
            },
            "repository_id": repository_id,
            "schema_version": "hqa.repository-recovery-identity.v2",
            "submodule_capture": {
                "exit_code": submodule_exit,
                "stderr_sha256": submodule_stderr,
            },
            "untracked_capture_bounds": untracked_capture_bounds,
            "upstream": _closure_upstream(repository),
        }
        _write_once(staging / "identity.json", canonical_json_bytes(identity))
        after_capture = repository_identity(repository)
        if after_capture != before:
            raise RepositoryRecoveryError(
                "repository changed during closure capture"
            )
        first = _closure_restore_attempt(
            staging, first_destination, identity
        )
        rehearsal = _closure_rehearse_closed_rebuild(
            first_destination,
            closed_rebuild_spec,
            enabled=first["restore_verified"] is True,
            expected_cache_path=package.parent / "uv-cache",
            protected_paths=[
                package,
                first_destination,
                second_destination,
                *roots,
            ],
        )
        second = _closure_restore_attempt(
            staging, second_destination, identity
        )
        after_drills = repository_identity(repository)
        if after_drills != before:
            raise RepositoryRecoveryError(
                "source repository changed during closure restore drills"
            )
        source_device = repository.stat().st_dev
        first_device = (
            first_destination.stat().st_dev
            if first_destination.is_dir()
            else None
        )
        second_device = (
            second_destination.stat().st_dev
            if second_destination.is_dir()
            else None
        )
        same_filesystem_class = (
            isinstance(first_device, int)
            and isinstance(second_device, int)
            and source_device == first_device == second_device
        )
        rehearsal_verified = (
            rehearsal["command_exit_code"] == 0
            and rehearsal["required_paths_present"] is True
            and rehearsal["state_changed"] is True
            and rehearsal["tracked_git_identity_unchanged"] is True
            and rehearsal["write_scope_respected"] is True
            and isinstance(rehearsal["rebuild_proof"], dict)
            and rehearsal["rebuild_proof"]["verified"] is True
        )
        restore_verified = (
            first["restore_verified"] is True
            and rehearsal_verified
            and second["restore_verified"] is True
            and same_filesystem_class
        )
        receipt = {
            "filesystem_devices": {
                "first_restore_st_dev": first_device,
                "second_restore_st_dev": second_device,
                "source_st_dev": source_device,
            },
            "first_restore": first,
            "package": str(package),
            "rehearsal": rehearsal,
            "restore_verified": restore_verified,
            "same_filesystem_class": same_filesystem_class,
            "schema_version": "hqa.repository-restore-receipt.v2",
            "second_restore": second,
            "source_after_drills_sha256": _sha256(
                canonical_json_bytes(after_drills)
            ),
            "source_before_sha256": _sha256(canonical_json_bytes(before)),
        }
        _write_once(
            staging / "restore-receipt.json", canonical_json_bytes(receipt)
        )
        index_bytes, index_document = _closure_package_index(staging)
        _write_once(staging / _INDEX_NAME, index_bytes)
        os.replace(staging, package)
        validation = verify_closure_package(package)
        return {
            "entry_count": index_document["entry_count"],
            "head": before["head_object_id"],
            "package": str(package),
            "recovery_files_bytes": len(index_bytes),
            "recovery_files_sha256": _sha256(index_bytes),
            "restore_receipt_sha256": validation[
                "restore_receipt_sha256"
            ],
            "restore_verified": restore_verified,
        }
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


__all__ = [
    "RepositoryRecoveryError",
    "capture_and_drill_closure_repository",
    "canonical_json_bytes",
    "capture_repository",
    "repository_identity",
    "restore_drill",
    "verify_closure_package",
    "verify_package",
    "verify_receipt",
]
