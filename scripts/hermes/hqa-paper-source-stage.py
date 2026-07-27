#!/usr/bin/python3
"""Stage reviewed paper-factor source without exposing its bytes in argv.

The installed launcher is bound to one release HQA checkout.  It accepts only
bounded UTF-8 Python source on stdin and publishes that exact byte sequence to
an ignored, owner-private, content-addressed runtime path.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path("__HQA_REPO_DIR__")
_MAX_SOURCE_BYTES = 256 * 1024
_PRIVATE_DIRECTORY_MODE = 0o700
_SOURCE_MODE = 0o600
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY
_DIRECTORY_FLAGS |= getattr(os, "O_CLOEXEC", 0)
_DIRECTORY_FLAGS |= getattr(os, "O_NOFOLLOW", 0)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
_READ_FLAGS |= getattr(os, "O_NOFOLLOW", 0)
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL
_WRITE_FLAGS |= getattr(os, "O_CLOEXEC", 0)
_WRITE_FLAGS |= getattr(os, "O_NOFOLLOW", 0)


class StageError(RuntimeError):
    """A stable failure that never contains source bytes or caller values."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _directory_is_owner_controlled(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid in {0, os.geteuid()}
        and not stat.S_IMODE(metadata.st_mode) & 0o022
    )


def _open_repo_root() -> int:
    root = os.path.abspath(os.fspath(_REPO_ROOT))
    if not os.path.isabs(root):
        raise StageError("repo_root_invalid")

    try:
        current_fd = os.open(os.path.sep, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise StageError("repo_root_unavailable") from exc

    try:
        root_metadata = os.fstat(current_fd)
        if not _directory_is_owner_controlled(root_metadata):
            raise StageError("repo_root_unsafe")

        for component in root.split(os.path.sep)[1:]:
            if component in {"", ".", ".."}:
                raise StageError("repo_root_invalid")
            try:
                next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise StageError("repo_root_not_physical") from exc
                raise StageError("repo_root_unavailable") from exc

            try:
                metadata = os.fstat(next_fd)
                if not _directory_is_owner_controlled(metadata):
                    raise StageError("repo_root_unsafe")
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd

        metadata = os.fstat(current_fd)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise StageError("repo_root_unsafe")
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_or_create_directory(
    parent_fd: int,
    name: str,
    *,
    private: bool,
) -> int:
    try:
        child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, _PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise StageError("runtime_directory_unavailable") from exc
        try:
            child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise StageError("runtime_directory_unsafe") from exc
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise StageError("runtime_directory_unsafe") from exc
        raise StageError("runtime_directory_unavailable") from exc

    metadata = os.fstat(child_fd)
    expected_mode = _PRIVATE_DIRECTORY_MODE if private else None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or (
            expected_mode is not None
            and stat.S_IMODE(metadata.st_mode) != expected_mode
        )
    ):
        os.close(child_fd)
        raise StageError("runtime_directory_unsafe")
    return child_fd


def _open_sources_directory(repo_fd: int) -> int:
    opened: list[int] = []
    current_fd = repo_fd
    try:
        for name, private in (
            ("data", False),
            ("_runtime", False),
            ("factor-gate1", True),
            ("sources", True),
        ):
            current_fd = _open_or_create_directory(
                current_fd,
                name,
                private=private,
            )
            opened.append(current_fd)
        return opened.pop()
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _require_private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != _PRIVATE_DIRECTORY_MODE
    ):
        raise StageError("runtime_directory_unsafe")


def _read_source() -> bytes:
    try:
        source = sys.stdin.buffer.read(_MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise StageError("source_read_failed") from exc
    if not source:
        raise StageError("source_empty")
    if len(source) > _MAX_SOURCE_BYTES:
        raise StageError("source_too_large")
    if b"\x00" in source:
        raise StageError("source_not_python")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StageError("source_not_utf8") from exc
    if not text.strip():
        raise StageError("source_empty")
    try:
        compile(text, "<reviewed-paper-source>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError, TypeError) as exc:
        raise StageError("source_not_python") from exc
    return source


def _require_ignored(source_path: Path) -> None:
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "HOME": os.devnull,
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    try:
        result = subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                os.fspath(_REPO_ROOT),
                "check-ignore",
                "--quiet",
                "--",
                os.fspath(source_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StageError("ignore_check_unavailable") from exc
    if result.returncode != 0:
        raise StageError("source_path_not_ignored")


def _read_exact_source(
    sources_fd: int,
    filename: str,
    expected: bytes,
) -> None:
    try:
        descriptor = os.open(filename, _READ_FLAGS, dir_fd=sources_fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise StageError("source_conflict") from exc

    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != _SOURCE_MODE
            or before.st_size != len(expected)
        ):
            raise StageError("source_conflict")

        payload = bytearray()
        while len(payload) <= _MAX_SOURCE_BYTES:
            chunk = os.read(
                descriptor,
                min(8192, _MAX_SOURCE_BYTES + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            bytes(payload) != expected
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise StageError("source_conflict")
    finally:
        os.close(descriptor)

    try:
        current = os.stat(filename, dir_fd=sources_fd, follow_symlinks=False)
    except OSError as exc:
        raise StageError("source_conflict") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_dev != before.st_dev
        or current.st_ino != before.st_ino
        or current.st_uid != os.geteuid()
        or current.st_nlink != 1
        or stat.S_IMODE(current.st_mode) != _SOURCE_MODE
    ):
        raise StageError("source_conflict")


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(descriptor, payload[offset:])
        except OSError as exc:
            raise StageError("source_write_failed") from exc
        if written <= 0:
            raise StageError("source_write_failed")
        offset += written


def _publish_source(
    sources_fd: int,
    filename: str,
    source: bytes,
) -> None:
    try:
        _read_exact_source(sources_fd, filename, source)
        return
    except FileNotFoundError:
        pass

    temporary = f".{filename}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    temporary_present = False
    try:
        try:
            descriptor = os.open(
                temporary,
                _WRITE_FLAGS,
                _SOURCE_MODE,
                dir_fd=sources_fd,
            )
        except OSError as exc:
            raise StageError("source_write_failed") from exc
        temporary_present = True
        try:
            _write_all(descriptor, source)
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != _SOURCE_MODE
            ):
                raise StageError("source_write_failed")
        finally:
            os.close(descriptor)

        try:
            os.link(
                temporary,
                filename,
                src_dir_fd=sources_fd,
                dst_dir_fd=sources_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
        except OSError as exc:
            raise StageError("source_write_failed") from exc

        os.unlink(temporary, dir_fd=sources_fd)
        temporary_present = False
        os.fsync(sources_fd)
        _read_exact_source(sources_fd, filename, source)
    finally:
        if temporary_present:
            try:
                os.unlink(temporary, dir_fd=sources_fd)
                os.fsync(sources_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _run() -> dict[str, str]:
    if len(sys.argv) != 1:
        raise StageError("arguments_not_allowed")
    source = _read_source()
    digest = hashlib.sha256(source).hexdigest()
    filename = f"source-{digest}.py"
    source_path = (
        _REPO_ROOT / "data" / "_runtime" / "factor-gate1" / "sources" / filename
    )

    repo_fd = _open_repo_root()
    try:
        _require_ignored(source_path)
        sources_fd = _open_sources_directory(repo_fd)
        try:
            _require_private_directory(sources_fd)
            _publish_source(sources_fd, filename, source)
            _require_private_directory(sources_fd)
        finally:
            os.close(sources_fd)
    finally:
        os.close(repo_fd)

    return {
        "source_file_ref": os.fspath(source_path),
        "reviewed_source_sha256": digest,
    }


def main() -> int:
    try:
        receipt = _run()
    except StageError as exc:
        print(f"paper_source_stage_error={exc.code}", file=sys.stderr)
        return 2
    except BaseException:
        print("paper_source_stage_error=unavailable", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
