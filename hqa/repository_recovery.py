"""Content-addressed Git repository recovery packages and restore drills."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
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
    paths.sort(key=lambda value: value.encode("utf-8"))
    return {
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
        "repository_id",
        "schema_version",
        "submodule_capture",
        "upstream",
    }
    mutable = identity.get("mutable_identity") if isinstance(identity, dict) else None
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
    ):
        raise RepositoryRecoveryError("invalid closure recovery identity")
    _normalize_remote(str(identity["publication_url"]))
    return identity


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
        or receipt.get("schema_version")
        != "hqa.repository-restore-receipt.v2"
        or receipt.get("package") != str(package)
        or not isinstance(receipt.get("restore_verified"), bool)
    ):
        raise RepositoryRecoveryError("invalid closure restore receipt")
    return {
        "entry_count": len(entries),
        "head": identity["head"],
        "recovery_files_bytes": len(index_bytes),
        "recovery_files_sha256": _sha256(index_bytes),
        "restore_receipt_sha256": _sha256(receipt_bytes),
        "restore_verified": receipt["restore_verified"],
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
    fields = (
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
    for field in fields:
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
) -> dict[str, object]:
    destination = _validate_new_path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    mutable = identity["mutable_identity"]
    if not isinstance(mutable, dict):
        raise RepositoryRecoveryError("invalid closure mutable identity")
    records: list[dict[str, object]] = []
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
    try:
        return _materialize_closure_restore(package, destination, identity)
    except RepositoryRecoveryError as exc:
        return {
            "command_exits": [],
            "compared_fields": [],
            "comparison_mismatches": ["restore-error"],
            "destination": str(destination),
            "error": str(exc),
            "restore_exit_code": 1,
            "restore_verified": False,
        }


def _closure_rehearse_patch(
    destination: Path,
    patch: Path,
    expected_sha256: str,
    *,
    enabled: bool,
) -> dict[str, object]:
    patch_payload = _read_regular(patch)
    observed_sha256 = _sha256(patch_payload)
    if observed_sha256 != expected_sha256:
        raise RepositoryRecoveryError("rehearsal patch digest mismatch")
    if not patch_payload.startswith(b"diff --git "):
        raise RepositoryRecoveryError(
            "rehearsal patch must be a non-empty Git patch"
        )
    if not enabled:
        return {
            "apply_exit_code": None,
            "check_exit_code": None,
            "enabled": False,
            "input_bytes": len(patch_payload),
            "input_path": str(patch),
            "input_sha256": observed_sha256,
            "state_changed": False,
        }
    before = repository_identity(destination)
    check_result = _run(
        [
            "git",
            "apply",
            "--check",
            "--binary",
            "--whitespace=nowarn",
            "--",
            str(patch),
        ],
        cwd=destination,
        check=False,
    )
    apply_exit: int | None = None
    apply_stdout = b""
    apply_stderr = b""
    if check_result.returncode == 0:
        apply_result = _run(
            [
                "git",
                "apply",
                "--binary",
                "--whitespace=nowarn",
                "--",
                str(patch),
            ],
            cwd=destination,
            check=False,
        )
        apply_exit = apply_result.returncode
        apply_stdout = apply_result.stdout
        apply_stderr = apply_result.stderr
    after = repository_identity(destination)
    state_changed = before != after
    return {
        "apply_exit_code": apply_exit,
        "apply_stderr_sha256": _sha256(apply_stderr),
        "apply_stdout_sha256": _sha256(apply_stdout),
        "check_exit_code": check_result.returncode,
        "check_stderr_sha256": _sha256(check_result.stderr),
        "check_stdout_sha256": _sha256(check_result.stdout),
        "enabled": True,
        "input_bytes": len(patch_payload),
        "input_path": str(patch),
        "input_sha256": observed_sha256,
        "state_after_sha256": _sha256(canonical_json_bytes(after)),
        "state_before_sha256": _sha256(canonical_json_bytes(before)),
        "state_changed": state_changed,
    }


def capture_and_drill_closure_repository(
    repository: Path,
    package: Path,
    first_destination: Path,
    second_destination: Path,
    rehearsal_patch: Path,
    *,
    rehearsal_patch_sha256: str,
    repository_id: str,
    publication_url: str,
    publication_remote_name: str,
    operator_identity: str,
) -> dict[str, object]:
    """Capture Section 4.1 artifacts, rehearse a patch, and restore twice."""

    repository = _validate_existing_chain(Path(repository), final_directory=True)
    package = _validate_new_path(Path(package))
    first_destination = _validate_new_path(Path(first_destination))
    second_destination = _validate_new_path(Path(second_destination))
    rehearsal_patch = _validate_existing_chain(
        Path(rehearsal_patch), final_directory=False
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
    if (
        rehearsal_patch == package
        or package in rehearsal_patch.parents
        or rehearsal_patch == first_destination
        or first_destination in rehearsal_patch.parents
        or rehearsal_patch == second_destination
        or second_destination in rehearsal_patch.parents
    ):
        raise RepositoryRecoveryError(
            "rehearsal patch must be outside package and restore destinations"
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", repository_id):
        raise RepositoryRecoveryError("invalid closure repository ID")
    if (
        not operator_identity.strip()
        or operator_identity != operator_identity.strip()
        or any(ord(character) < 32 for character in operator_identity)
    ):
        raise RepositoryRecoveryError("invalid closure operator identity")
    if not re.fullmatch(r"[0-9a-f]{64}", rehearsal_patch_sha256):
        raise RepositoryRecoveryError("invalid rehearsal patch digest")
    rehearsal_payload = _read_regular(rehearsal_patch)
    if _sha256(rehearsal_payload) != rehearsal_patch_sha256:
        raise RepositoryRecoveryError("rehearsal patch digest mismatch")
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
    staging = package.with_name(f".{package.name}.staging")
    _assert_disjoint(staging, roots, label="closure recovery staging path")
    _restricted_directory(staging)
    try:
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
            "repository_id": repository_id,
            "schema_version": "hqa.repository-recovery-identity.v2",
            "submodule_capture": {
                "exit_code": submodule_exit,
                "stderr_sha256": submodule_stderr,
            },
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
        rehearsal = _closure_rehearse_patch(
            first_destination,
            rehearsal_patch,
            rehearsal_patch_sha256,
            enabled=first["restore_verified"] is True,
        )
        second = _closure_restore_attempt(
            staging, second_destination, identity
        )
        after_drills = repository_identity(repository)
        if after_drills != before:
            raise RepositoryRecoveryError(
                "source repository changed during closure restore drills"
            )
        restore_verified = (
            first["restore_verified"] is True
            and rehearsal["check_exit_code"] == 0
            and rehearsal["apply_exit_code"] == 0
            and rehearsal["state_changed"] is True
            and second["restore_verified"] is True
        )
        receipt = {
            "first_restore": first,
            "package": str(package),
            "rehearsal": rehearsal,
            "restore_verified": restore_verified,
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
