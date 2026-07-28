"""Operator-controlled updater for the two-worktree local Hermes topology.

The Desktop reads ``main`` from ``hermes_root`` while the managed gateway runs
from ``runtime_worktree`` on an integration branch.  This module treats those
as one update unit and never changes Agent, release, or trading gates.
"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


class HermesUpdateError(RuntimeError):
    """Fail-closed update error with a stable operator-facing code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class UpdateConfig:
    hermes_root: Path
    runtime_worktree: Path
    state_dir: Path
    remote: str = "origin"
    official_branch: str = "main"
    command_timeout_seconds: float = 120.0
    validation_commands: tuple[tuple[str, ...], ...] = ()
    install_commands: tuple[tuple[str, ...], ...] = ()
    restart_commands: tuple[tuple[str, ...], ...] = ()
    health_url: str | None = None


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    root_head: str
    runtime_head: str
    official_head: str
    root_branch: str
    runtime_branch: str
    root_missing_official: int
    runtime_missing_official: int
    runtime_local_commits: int
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class UpdateReceipt:
    status: str
    receipt_id: str
    receipt_path: Path
    backup_bundle: Path
    root_before: str
    runtime_before: str
    official_head: str
    candidate_head: str | None
    root_after: str | None
    runtime_after: str | None
    candidate_path: Path | None
    error_code: str | None = None


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(part) for part in command],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise HermesUpdateError(
            "command_timeout",
            f"command timed out in {cwd}: {command[0]}",
        ) from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "command failed"
        raise HermesUpdateError(
            "command_failed",
            f"{command[0]} failed in {cwd}: {detail}",
        ) from exc


def _git(
    config: UpdateConfig,
    repo: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        ("git", "-C", str(repo), *arguments),
        cwd=repo,
        timeout=config.command_timeout_seconds,
        check=check,
    )


def _git_text(config: UpdateConfig, repo: Path, *arguments: str) -> str:
    return _git(config, repo, *arguments).stdout.strip()


def _common_git_dir(config: UpdateConfig, repo: Path) -> Path:
    value = Path(_git_text(config, repo, "rev-parse", "--git-common-dir"))
    return (repo / value).resolve() if not value.is_absolute() else value.resolve()


def _is_ancestor(
    config: UpdateConfig,
    repo: Path,
    ancestor: str,
    descendant: str,
) -> bool:
    result = _git(
        config,
        repo,
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise HermesUpdateError(
            "git_ancestry_failed",
            "unable to verify Hermes commit ancestry",
        )
    return result.returncode == 0


def _count(config: UpdateConfig, repo: Path, revision_range: str) -> int:
    raw = _git_text(config, repo, "rev-list", "--count", revision_range)
    try:
        return int(raw)
    except ValueError as exc:
        raise HermesUpdateError(
            "git_count_invalid",
            "git returned an invalid revision count",
        ) from exc


def _tracked_dirty(config: UpdateConfig, repo: Path) -> bool:
    return bool(
        _git_text(
            config,
            repo,
            "status",
            "--porcelain",
            "--untracked-files=no",
        )
    )


def check_update(config: UpdateConfig, *, fetch: bool) -> UpdateCheck:
    root = config.hermes_root
    runtime = config.runtime_worktree
    if not root.is_absolute() or not runtime.is_absolute() or not config.state_dir.is_absolute():
        raise HermesUpdateError(
            "paths_must_be_absolute",
            "Hermes update paths must be absolute",
        )
    if not root.is_dir() or not runtime.is_dir():
        raise HermesUpdateError(
            "worktree_missing",
            "Hermes root or runtime worktree is missing",
        )
    if _common_git_dir(config, root) != _common_git_dir(config, runtime):
        raise HermesUpdateError(
            "topology_mismatch",
            "Desktop root and runtime must be worktrees of the same repository",
        )

    if fetch:
        _git(
            config,
            root,
            "fetch",
            "--prune",
            config.remote,
            config.official_branch,
        )

    official_ref = f"{config.remote}/{config.official_branch}"
    root_head = _git_text(config, root, "rev-parse", "HEAD")
    runtime_head = _git_text(config, runtime, "rev-parse", "HEAD")
    official_head = _git_text(config, root, "rev-parse", official_ref)
    root_branch = _git_text(config, root, "branch", "--show-current")
    runtime_branch = _git_text(config, runtime, "branch", "--show-current")

    blockers: list[str] = []
    if root_branch != config.official_branch:
        blockers.append("desktop_root_not_official_branch")
    if not runtime_branch or runtime_branch == config.official_branch:
        blockers.append("runtime_integration_branch_invalid")
    if _tracked_dirty(config, root):
        blockers.append("desktop_root_tracked_changes")
    if _tracked_dirty(config, runtime):
        blockers.append("runtime_tracked_changes")
    if not _is_ancestor(config, root, root_head, official_head):
        blockers.append("desktop_root_not_fast_forward")
    if not _is_ancestor(config, root, root_head, runtime_head):
        blockers.append("runtime_missing_installed_official_baseline")

    root_missing = _count(config, root, f"{root_head}..{official_head}")
    runtime_missing = _count(config, root, f"{runtime_head}..{official_head}")
    runtime_local = _count(config, root, f"{official_head}..{runtime_head}")
    if blockers:
        status = "blocked"
    elif root_missing == 0 and runtime_missing == 0:
        status = "up_to_date"
    else:
        status = "update_available"
    return UpdateCheck(
        status=status,
        root_head=root_head,
        runtime_head=runtime_head,
        official_head=official_head,
        root_branch=root_branch,
        runtime_branch=runtime_branch,
        root_missing_official=root_missing,
        runtime_missing_official=runtime_missing,
        runtime_local_commits=runtime_local,
        blockers=tuple(blockers),
    )


def _prepare_state_directory(config: UpdateConfig) -> None:
    state = config.state_dir
    if state.exists() and state.is_symlink():
        raise HermesUpdateError(
            "state_dir_unsafe",
            "Hermes update state directory must not be a symlink",
        )
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(state, 0o700)


def _write_receipt(config: UpdateConfig, receipt: UpdateReceipt) -> None:
    document = {
        "schema_version": 1,
        "status": receipt.status,
        "receipt_id": receipt.receipt_id,
        "hermes_root": str(config.hermes_root),
        "runtime_worktree": str(config.runtime_worktree),
        "root_before": receipt.root_before,
        "runtime_before": receipt.runtime_before,
        "official_head": receipt.official_head,
        "candidate_head": receipt.candidate_head,
        "root_after": receipt.root_after,
        "runtime_after": receipt.runtime_after,
        "candidate_path": str(receipt.candidate_path) if receipt.candidate_path else None,
        "backup_bundle": str(receipt.backup_bundle),
        "error_code": receipt.error_code,
    }
    receipt.receipt_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".receipt.",
        dir=receipt.receipt_path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                document,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, receipt.receipt_path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _new_receipt_paths(config: UpdateConfig) -> tuple[str, Path, Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    receipt_dir = config.state_dir / "receipts" / receipt_id
    receipt_dir.mkdir(parents=True, mode=0o700)
    return (
        receipt_id,
        receipt_dir / "receipt.json",
        receipt_dir / "hermes-before.bundle",
        config.state_dir / "candidates" / receipt_id,
    )


def _cleanup_candidate(
    config: UpdateConfig,
    *,
    candidate_path: Path,
    candidate_branch: str,
    candidate_head: str,
) -> None:
    _git(
        config,
        config.hermes_root,
        "worktree",
        "remove",
        str(candidate_path),
    )
    _git(
        config,
        config.hermes_root,
        "update-ref",
        "-d",
        f"refs/heads/{candidate_branch}",
        candidate_head,
    )


def _probe_health(config: UpdateConfig) -> None:
    if config.health_url is None:
        return
    parsed = urlsplit(config.health_url)
    try:
        is_loopback = bool(
            parsed.hostname
            and ipaddress.ip_address(parsed.hostname).is_loopback
        )
    except ValueError as exc:
        raise HermesUpdateError(
            "health_url_invalid",
            "Hermes health URL must use a numeric loopback address",
        ) from exc
    if (
        parsed.scheme != "http"
        or not is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/health"
        or parsed.query
        or parsed.fragment
    ):
        raise HermesUpdateError(
            "health_url_invalid",
            "Hermes health URL must be an unauthenticated loopback /health URL",
        )

    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + min(config.command_timeout_seconds, 30.0)
    last_error = "health probe failed"
    while time.monotonic() < deadline:
        try:
            response = opener.open(
                Request(config.health_url, method="GET"),
                timeout=2.0,
            )
            with response:
                raw = response.read(16_385)
                if response.status != 200 or len(raw) > 16_384:
                    raise ValueError("invalid health response")
            document = json.loads(raw.decode("utf-8", errors="strict"))
            if isinstance(document, dict) and document.get("status") in {
                "ok",
                "healthy",
            }:
                return
            last_error = "Hermes health response is not healthy"
        except (
            HTTPError,
            URLError,
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            last_error = str(exc) or type(exc).__name__
        time.sleep(0.25)
    raise HermesUpdateError(
        "health_check_failed",
        f"Hermes did not become healthy: {last_error}",
    )


def apply_update(config: UpdateConfig) -> UpdateReceipt:
    _prepare_state_directory(config)
    preflight = check_update(config, fetch=True)
    if preflight.status == "blocked":
        raise HermesUpdateError(
            "update_blocked",
            "Hermes update is blocked: " + ",".join(preflight.blockers),
        )
    if preflight.status == "up_to_date":
        raise HermesUpdateError(
            "already_up_to_date",
            "Hermes is already up to date",
        )
    if not config.validation_commands:
        raise HermesUpdateError(
            "validation_required",
            "at least one isolated validation command is required",
        )

    receipt_id, receipt_path, backup_bundle, candidate_path = _new_receipt_paths(
        config
    )
    candidate_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    candidate_branch = f"codex/hqa-hermes-update-{receipt_id}"
    _git(
        config,
        config.hermes_root,
        "bundle",
        "create",
        str(backup_bundle),
        "--all",
    )
    _git(
        config,
        config.hermes_root,
        "worktree",
        "add",
        "--quiet",
        "-b",
        candidate_branch,
        str(candidate_path),
        preflight.runtime_head,
    )

    merge = _git(
        config,
        candidate_path,
        "-c",
        "user.name=HQA Hermes Updater",
        "-c",
        "user.email=hqa-hermes-update@localhost",
        "merge",
        "--no-edit",
        f"{config.remote}/{config.official_branch}",
        check=False,
    )
    if merge.returncode != 0:
        receipt = UpdateReceipt(
            status="conflict",
            receipt_id=receipt_id,
            receipt_path=receipt_path,
            backup_bundle=backup_bundle,
            root_before=preflight.root_head,
            runtime_before=preflight.runtime_head,
            official_head=preflight.official_head,
            candidate_head=None,
            root_after=None,
            runtime_after=None,
            candidate_path=candidate_path,
            error_code="candidate_merge_conflict",
        )
        _write_receipt(config, receipt)
        return receipt

    candidate_head = _git_text(config, candidate_path, "rev-parse", "HEAD")
    try:
        for command in config.validation_commands:
            _run(
                command,
                cwd=candidate_path,
                timeout=config.command_timeout_seconds,
            )
    except HermesUpdateError:
        receipt = UpdateReceipt(
            status="validation_failed",
            receipt_id=receipt_id,
            receipt_path=receipt_path,
            backup_bundle=backup_bundle,
            root_before=preflight.root_head,
            runtime_before=preflight.runtime_head,
            official_head=preflight.official_head,
            candidate_head=candidate_head,
            root_after=None,
            runtime_after=None,
            candidate_path=candidate_path,
            error_code="candidate_validation_failed",
        )
        _write_receipt(config, receipt)
        return receipt

    try:
        _git(
            config,
            config.runtime_worktree,
            "merge",
            "--ff-only",
            candidate_branch,
        )
        _git(
            config,
            config.hermes_root,
            "merge",
            "--ff-only",
            f"{config.remote}/{config.official_branch}",
        )
        root_after = _git_text(config, config.hermes_root, "rev-parse", "HEAD")
        runtime_after = _git_text(
            config,
            config.runtime_worktree,
            "rev-parse",
            "HEAD",
        )
        for command in (*config.install_commands, *config.restart_commands):
            _run(
                command,
                cwd=config.runtime_worktree,
                timeout=config.command_timeout_seconds,
            )
        _probe_health(config)
    except HermesUpdateError:
        promoted_root = _git_text(
            config,
            config.hermes_root,
            "rev-parse",
            "HEAD",
        )
        promoted_runtime = _git_text(
            config,
            config.runtime_worktree,
            "rev-parse",
            "HEAD",
        )
        rollback_error = False
        try:
            _git(
                config,
                config.runtime_worktree,
                "reset",
                "--hard",
                preflight.runtime_head,
            )
            _git(
                config,
                config.hermes_root,
                "reset",
                "--hard",
                preflight.root_head,
            )
            for command in (*config.install_commands, *config.restart_commands):
                _run(
                    command,
                    cwd=config.runtime_worktree,
                    timeout=config.command_timeout_seconds,
                )
            _probe_health(config)
        except HermesUpdateError:
            rollback_error = True
        if not rollback_error:
            _cleanup_candidate(
                config,
                candidate_path=candidate_path,
                candidate_branch=candidate_branch,
                candidate_head=candidate_head,
            )
        receipt = UpdateReceipt(
            status=(
                "rollback_failed"
                if rollback_error
                else "rolled_back_after_failure"
            ),
            receipt_id=receipt_id,
            receipt_path=receipt_path,
            backup_bundle=backup_bundle,
            root_before=preflight.root_head,
            runtime_before=preflight.runtime_head,
            official_head=preflight.official_head,
            candidate_head=candidate_head,
            root_after=promoted_root,
            runtime_after=promoted_runtime,
            candidate_path=candidate_path if rollback_error else None,
            error_code=(
                "automatic_rollback_failed"
                if rollback_error
                else "post_promotion_failed"
            ),
        )
        _write_receipt(config, receipt)
        return receipt

    _cleanup_candidate(
        config,
        candidate_path=candidate_path,
        candidate_branch=candidate_branch,
        candidate_head=candidate_head,
    )
    receipt = UpdateReceipt(
        status="applied",
        receipt_id=receipt_id,
        receipt_path=receipt_path,
        backup_bundle=backup_bundle,
        root_before=preflight.root_head,
        runtime_before=preflight.runtime_head,
        official_head=preflight.official_head,
        candidate_head=candidate_head,
        root_after=root_after,
        runtime_after=runtime_after,
        candidate_path=None,
    )
    _write_receipt(config, receipt)
    return receipt


def _load_receipt(config: UpdateConfig, receipt_path: Path) -> dict[str, object]:
    try:
        resolved = receipt_path.resolve(strict=True)
        resolved.relative_to((config.state_dir / "receipts").resolve(strict=True))
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HermesUpdateError(
            "rollback_receipt_invalid",
            "rollback receipt must be inside the private updater state directory",
        ) from exc
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HermesUpdateError(
            "rollback_receipt_invalid",
            "rollback receipt is unreadable",
        ) from exc
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or document.get("status") != "applied"
        or document.get("hermes_root") != str(config.hermes_root)
        or document.get("runtime_worktree") != str(config.runtime_worktree)
    ):
        raise HermesUpdateError(
            "rollback_receipt_invalid",
            "rollback receipt does not match this Hermes topology",
        )
    for field in (
        "root_before",
        "runtime_before",
        "root_after",
        "runtime_after",
        "official_head",
    ):
        if not re.fullmatch(r"[0-9a-f]{40,64}", str(document.get(field, ""))):
            raise HermesUpdateError(
                "rollback_receipt_invalid",
                f"rollback receipt has an invalid {field}",
            )
    return document


def rollback_update(
    config: UpdateConfig,
    receipt_path: Path,
) -> UpdateReceipt:
    _prepare_state_directory(config)
    document = _load_receipt(config, receipt_path)
    if _tracked_dirty(config, config.hermes_root) or _tracked_dirty(
        config, config.runtime_worktree
    ):
        raise HermesUpdateError(
            "rollback_tracked_changes",
            "rollback refuses to overwrite tracked worktree changes",
        )

    current_root = _git_text(config, config.hermes_root, "rev-parse", "HEAD")
    current_runtime = _git_text(
        config,
        config.runtime_worktree,
        "rev-parse",
        "HEAD",
    )
    if (
        current_root != document["root_after"]
        or current_runtime != document["runtime_after"]
    ):
        raise HermesUpdateError(
            "rollback_head_mismatch",
            "rollback refuses because Hermes advanced after this receipt",
        )

    _git(
        config,
        config.runtime_worktree,
        "reset",
        "--hard",
        str(document["runtime_before"]),
    )
    _git(
        config,
        config.hermes_root,
        "reset",
        "--hard",
        str(document["root_before"]),
    )
    for command in (*config.install_commands, *config.restart_commands):
        _run(
            command,
            cwd=config.runtime_worktree,
            timeout=config.command_timeout_seconds,
        )
    _probe_health(config)

    rolled_back = UpdateReceipt(
        status="rolled_back",
        receipt_id=str(document["receipt_id"]),
        receipt_path=receipt_path.resolve(),
        backup_bundle=Path(str(document["backup_bundle"])),
        root_before=str(document["root_before"]),
        runtime_before=str(document["runtime_before"]),
        official_head=str(document["official_head"]),
        candidate_head=(
            str(document["candidate_head"])
            if document.get("candidate_head")
            else None
        ),
        root_after=str(document["root_after"]),
        runtime_after=str(document["runtime_after"]),
        candidate_path=None,
    )
    _write_receipt(config, rolled_back)
    return rolled_back
