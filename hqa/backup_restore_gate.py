"""Fail-closed Gate 8 authority for one exact HQA release checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

from hqa.noneditable_upgrade import (
    CANONICAL_AUTHORITY,
    NoneditableUpgradeError,
    ReleaseAuthority,
    observe_release_identity,
)
from hqa.repository_recovery import (
    RepositoryRecoveryError,
    canonical_json_bytes,
    capture_repository,
    restore_drill,
    verify_package,
    verify_receipt,
)


class BackupRestoreGateError(RuntimeError):
    """The exact release backup/restore gate failed closed."""


_GIT = Path("/usr/bin/git")
_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _git(repository: Path, *arguments: str) -> bytes:
    environment = {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": os.devnull,
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    completed = subprocess.run(
        [
            str(_GIT),
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-C",
            str(repository),
            *arguments,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    if completed.returncode != 0:
        raise BackupRestoreGateError(
            "Git observation failed "
            f"exit={completed.returncode} "
            f"stderr_sha256={hashlib.sha256(completed.stderr).hexdigest()}"
        )
    return completed.stdout


def _safe_path(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise BackupRestoreGateError("committed inventory path is not UTF-8") from exc
    candidate = PurePosixPath(text)
    if (
        not text
        or "\x00" in text
        or "\\" in text
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != text
    ):
        raise BackupRestoreGateError("committed inventory path is unsafe")
    return text


def _committed_inventory(repository: Path) -> dict[str, object]:
    listing = _git(
        repository,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        "HEAD",
    )
    if listing and not listing.endswith(b"\0"):
        raise BackupRestoreGateError("committed inventory is malformed")
    entries: list[dict[str, object]] = []
    for raw_record in listing.split(b"\0"):
        if not raw_record:
            continue
        try:
            metadata, raw_path = raw_record.split(b"\t", 1)
            raw_mode, raw_kind, raw_object = metadata.split(b" ", 2)
            mode = raw_mode.decode("ascii", "strict")
            kind = raw_kind.decode("ascii", "strict")
            object_id = raw_object.decode("ascii", "strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise BackupRestoreGateError("committed inventory is malformed") from exc
        path = _safe_path(raw_path)
        if (
            kind != "blob"
            or mode not in {"100644", "100755"}
            or _OBJECT_ID.fullmatch(object_id) is None
        ):
            raise BackupRestoreGateError(
                "committed inventory contains an unsupported entry"
            )
        payload = _git(repository, "cat-file", "blob", object_id)
        target = repository / path
        try:
            metadata = target.lstat()
        except OSError as exc:
            raise BackupRestoreGateError(
                "worktree does not contain exact committed bytes"
            ) from exc
        expected_mode = 0o755 if mode == "100755" else 0o644
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != expected_mode
        ):
            raise BackupRestoreGateError(
                "worktree does not contain exact committed bytes and modes"
            )
        observed = target.read_bytes()
        if observed != payload:
            raise BackupRestoreGateError(
                "worktree does not contain exact committed bytes"
            )
        entries.append(
            {
                "bytes": len(payload),
                "mode": mode,
                "object_id": object_id,
                "path": path,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    tree = (
        _git(repository, "rev-parse", "--verify", "HEAD^{tree}")
        .decode("ascii", "strict")
        .strip()
    )
    commit = (
        _git(repository, "rev-parse", "--verify", "HEAD")
        .decode("ascii", "strict")
        .strip()
    )
    if (
        _OBJECT_ID.fullmatch(tree) is None
        or _OBJECT_ID.fullmatch(commit) is None
        or not entries
    ):
        raise BackupRestoreGateError("committed inventory identity is malformed")
    return {
        "commit": commit,
        "entries": entries,
        "exact_committed_bytes": True,
        "file_count": len(entries),
        "files_sha256": hashlib.sha256(canonical_json_bytes(entries)).hexdigest(),
        "tree": tree,
    }


def _canonical_new_output(repository: Path, output_dir: Path) -> Path:
    output = Path(output_dir)
    if not output.is_absolute():
        raise BackupRestoreGateError("output directory must be absolute")
    lexical = Path(os.path.abspath(os.fspath(output)))
    if lexical != output:
        raise BackupRestoreGateError("output directory must be canonical")
    if output.exists() or output.is_symlink():
        raise BackupRestoreGateError("output directory must not exist")
    try:
        parent = output.parent.resolve(strict=True)
        source = repository.resolve(strict=True)
    except OSError as exc:
        raise BackupRestoreGateError(
            "output directory must have a canonical existing parent"
        ) from exc
    canonical = parent / output.name
    if canonical != output:
        raise BackupRestoreGateError("output directory must be canonical")
    if output == source or source in output.parents:
        raise BackupRestoreGateError(
            "output directory must be outside the release checkout"
        )
    return output


def _write_once(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def run_backup_restore_gate(
    repository_root: Path,
    output_dir: Path,
    *,
    expected_commit: str,
    authority: ReleaseAuthority = CANONICAL_AUTHORITY,
) -> dict[str, object]:
    """Capture once and prove two exact, independent committed restores."""

    repository = Path(repository_root)
    output = _canonical_new_output(repository, Path(output_dir))
    if _OBJECT_ID.fullmatch(expected_commit) is None:
        raise BackupRestoreGateError("expected commit is malformed")
    source_inventory = _committed_inventory(repository)
    try:
        identity = observe_release_identity(repository, authority)
    except NoneditableUpgradeError as exc:
        detail = str(exc)
        if "hidden index" in detail:
            raise BackupRestoreGateError(
                "release identity lacks exact committed bytes authority"
            ) from exc
        raise BackupRestoreGateError(f"release identity rejected: {detail}") from exc
    if identity["commit"] != expected_commit:
        raise BackupRestoreGateError("expected commit does not match release HEAD")
    if (
        source_inventory["commit"] != expected_commit
        or source_inventory["tree"] != identity["tree"]
    ):
        raise BackupRestoreGateError(
            "committed inventory does not bind release HEAD and tree"
        )

    output.mkdir(mode=0o700)
    output.chmod(0o700)
    package = output / "package"
    first = output / "restore-first"
    second = output / "restore-second"
    receipts = output / "restore-receipts"
    receipts.mkdir(mode=0o700)
    receipts.chmod(0o700)
    try:
        capture = capture_repository(repository, package)
        package_validation = verify_package(package)
        restore_rows: list[dict[str, object]] = []
        for label, destination in (("first", first), ("second", second)):
            receipt_path = receipts / f"{label}.json"
            restored = restore_drill(package, destination, receipt_path)
            receipt_validation = verify_receipt(package, receipt_path)
            inventory = _committed_inventory(destination)
            if inventory != source_inventory:
                raise BackupRestoreGateError(
                    f"{label} restore committed inventory mismatch"
                )
            restore_rows.append(
                {
                    "commit": inventory["commit"],
                    "destination": str(destination),
                    "inventory": inventory,
                    "label": label,
                    "receipt": str(receipt_path),
                    "receipt_sha256": receipt_validation["receipt_sha256"],
                    "receipt_verified": receipt_validation["verified"],
                    "restore_verified": restored["restore_verified"],
                    "tree": inventory["tree"],
                }
            )
        after_inventory = _committed_inventory(repository)
        try:
            after_identity = observe_release_identity(repository, authority)
        except NoneditableUpgradeError as exc:
            raise BackupRestoreGateError(
                f"source release changed during Gate 8: {exc}"
            ) from exc
        if after_inventory != source_inventory or after_identity != identity:
            raise BackupRestoreGateError(
                "source release changed during backup/restore Gate 8"
            )
        result: dict[str, object] = {
            "effects": {
                "database": "denied",
                "network": "denied",
                "provider": "denied",
                "runtime_mutation": "denied",
                "writes": [str(output)],
            },
            "gate": 8,
            "package": {
                "capture_count": 1,
                "entry_count": capture["entry_count"],
                "path": str(package),
                "recovery_files_bytes": package_validation["recovery_files_bytes"],
                "recovery_files_sha256": package_validation["recovery_files_sha256"],
                "verified": package_validation["verified"],
            },
            "restores": restore_rows,
            "schema_version": "hqa.agent-v0.2-backup-restore-gate.v1",
            "source": {
                "branch": identity["branch"],
                "commit": identity["commit"],
                "inventory": source_inventory,
                "tree": identity["tree"],
            },
            "status": "pass",
        }
        _write_once(output / "receipt.json", canonical_json_bytes(result))
        return result
    except (OSError, RepositoryRecoveryError) as exc:
        raise BackupRestoreGateError(f"backup/restore authority failed: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m hqa.backup_restore_gate")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        result = run_backup_restore_gate(
            CANONICAL_AUTHORITY.absolute_checkout_path,
            Path(args.output_dir),
            expected_commit=args.expected_commit,
        )
    except BackupRestoreGateError as exc:
        print(f"hqa_backup_restore_error={exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
