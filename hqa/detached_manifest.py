"""Strict detached SHA-256 manifests for owner-controlled evidence trees."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath

_LINE = re.compile(rb"^([0-9a-f]{64})  ([^\r\n]+)$")
_ROOT_NAME = "manifest.sha256"


class DetachedManifestError(RuntimeError):
    """Evidence tree or detached-root validation failed."""


def _lexical_absolute(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(os.fspath(candidate)))


def _real_root(path: Path) -> Path:
    candidate = _lexical_absolute(path)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise DetachedManifestError("evidence root does not exist") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise DetachedManifestError("symlinked evidence-root path is forbidden")
        if not stat.S_ISDIR(metadata.st_mode):
            raise DetachedManifestError("evidence-root path is not a directory")
    return candidate


def _relative_path(raw: str) -> str:
    if not raw or "\x00" in raw or "\r" in raw or "\n" in raw or "\\" in raw:
        raise DetachedManifestError("unsafe evidence path")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DetachedManifestError("unsafe evidence path")
    normalized = path.as_posix()
    if normalized != raw:
        raise DetachedManifestError("non-normalized evidence path")
    return normalized


def _regular_file_bytes(path: Path) -> bytes:
    return _regular_file_record(path)[0]


def _regular_file_record(path: Path) -> tuple[bytes, tuple[int, ...]]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise DetachedManifestError("evidence member is not a unique regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_mode != before.st_mode
            or opened.st_nlink != before.st_nlink
            or opened.st_size != before.st_size
            or opened.st_mtime_ns != before.st_mtime_ns
            or opened.st_ctime_ns != before.st_ctime_ns
        ):
            raise DetachedManifestError("evidence member changed before read")
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
            or after.st_nlink != opened.st_nlink
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise DetachedManifestError("evidence member changed during read")
        payload = b"".join(chunks)
        if len(payload) != opened.st_size:
            raise DetachedManifestError("short evidence read")
        return payload, (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    finally:
        os.close(descriptor)


def _enumerate_records(
    root: Path,
) -> dict[str, tuple[bytes, tuple[int, ...]]]:
    root = _real_root(root)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise DetachedManifestError("evidence root must be a real directory")
    members: dict[str, tuple[bytes, tuple[int, ...]]] = {}

    def fail_walk(error: OSError) -> None:
        raise DetachedManifestError("evidence tree is not fully readable") from error

    for current, directory_names, file_names in os.walk(
        root,
        followlinks=False,
        onerror=fail_walk,
    ):
        current_path = Path(current)
        for name in directory_names:
            directory = current_path / name
            _relative_path(directory.relative_to(root).as_posix())
            directory_metadata = directory.lstat()
            if not stat.S_ISDIR(directory_metadata.st_mode) or stat.S_ISLNK(
                directory_metadata.st_mode
            ):
                raise DetachedManifestError("unsafe evidence directory")
        for name in file_names:
            member = current_path / name
            relative = _relative_path(member.relative_to(root).as_posix())
            metadata = member.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise DetachedManifestError("unsafe evidence member")
            if relative == _ROOT_NAME:
                continue
            members[relative] = _regular_file_record(member)
    return members


def _enumerate(root: Path) -> dict[str, bytes]:
    return {path: record[0] for path, record in _enumerate_records(root).items()}


def manifest_bytes(root: Path) -> bytes:
    """Return strict detached-root bytes without mutating *root*."""

    members = _enumerate(Path(root))
    if not members:
        raise DetachedManifestError("detached manifest cannot be empty")
    lines = [
        hashlib.sha256(payload).hexdigest().encode("ascii")
        + b"  "
        + path.encode("utf-8")
        + b"\n"
        for path, payload in sorted(
            members.items(), key=lambda item: item[0].encode("utf-8")
        )
    ]
    return b"".join(lines)


def build_manifest(root: Path) -> Path:
    """Create ``manifest.sha256`` exactly once and return its path."""

    root = _real_root(Path(root))
    output = root / _ROOT_NAME
    if output.exists() or output.is_symlink():
        raise DetachedManifestError("detached manifest already exists")
    payload = manifest_bytes(root)
    descriptor = os.open(
        output,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise DetachedManifestError("short detached-manifest write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return output


def verify_manifest(root: Path) -> dict[str, object]:
    """Verify grammar, exact set equality, order and every covered digest."""

    root = _real_root(Path(root))
    manifest = root / _ROOT_NAME
    payload, manifest_record = _regular_file_record(manifest)
    if not payload:
        raise DetachedManifestError("detached manifest cannot be empty")
    if not payload.endswith(b"\n"):
        raise DetachedManifestError("detached manifest must end with LF")
    if b"\r" in payload:
        raise DetachedManifestError("detached manifest must use LF only")
    expected: dict[str, str] = {}
    previous: bytes | None = None
    for raw_line in payload[:-1].split(b"\n"):
        if not raw_line:
            raise DetachedManifestError("blank detached-manifest line")
        match = _LINE.fullmatch(raw_line)
        if match is None:
            raise DetachedManifestError("invalid detached-manifest line")
        digest = match.group(1).decode("ascii")
        try:
            path = _relative_path(match.group(2).decode("utf-8", "strict"))
        except UnicodeDecodeError as exc:
            raise DetachedManifestError("manifest path is not UTF-8") from exc
        if path == _ROOT_NAME:
            raise DetachedManifestError("detached root cannot cover itself")
        encoded = path.encode("utf-8")
        if previous is not None and encoded <= previous:
            raise DetachedManifestError("manifest paths are duplicated or unsorted")
        previous = encoded
        expected[path] = digest
    observed_records = _enumerate_records(root)
    observed = {path: record[0] for path, record in observed_records.items()}
    if set(expected) != set(observed_records):
        raise DetachedManifestError("detached-manifest file set mismatch")
    for path, content in observed.items():
        if hashlib.sha256(content).hexdigest() != expected[path]:
            raise DetachedManifestError("detached-manifest digest mismatch")
    final_records = _enumerate_records(root)
    if final_records != observed_records:
        raise DetachedManifestError("evidence tree changed during verification")
    final_manifest = _regular_file_record(manifest)
    if final_manifest != (payload, manifest_record):
        raise DetachedManifestError("detached manifest changed during verification")
    return {
        "covered_file_count": len(expected),
        "manifest_bytes": len(payload),
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "verified": True,
    }


__all__ = [
    "DetachedManifestError",
    "build_manifest",
    "manifest_bytes",
    "verify_manifest",
]
