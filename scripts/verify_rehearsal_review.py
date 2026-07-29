#!/usr/bin/env python3
"""Fail-closed verifier for v0.2.1 independent/adversarial review artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

CONTRACT = "hermes-v0.2.1-review-verifier/v1"
REVIEW_SCHEMA = "hermes-v0.2.1-review/v1"
BRANCH = "codex/agent-v0-2-release"
HQA_REMOTE = "https://github.com/YIBOWAY/hermes-quant-agent.git"
PLATFORM_REMOTE = "https://github.com/YIBOWAY/ai-quant-platform.git"
HQA_BASELINE = "a5589ba"
PLATFORM_BASELINE = "e19087e"
MODES = frozenset({"independent", "adversarial"})
SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})
FINDING_FIELDS = frozenset(
    {
        "severity",
        "affected_reference",
        "concrete_scenario",
        "direct_evidence",
        "admissible",
        "open",
        "blocking",
    }
)
MAX_REVIEW_BYTES = 8 * 1024 * 1024


class ReviewError(ValueError):
    """The review artifact or its bound repositories cannot be trusted."""


def canonical_json(document: object) -> bytes:
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def _strict_json(content: bytes) -> object:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewError("review_duplicate_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ReviewError("review_nonfinite")

    try:
        return json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except ReviewError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReviewError("review_invalid_json") from exc


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            return True
    return False


def _canonical_absolute(path: Path, field: str) -> Path:
    if (
        not path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or _has_symlink_component(path)
        or path.resolve() != path
    ):
        raise ReviewError(f"{field}_not_canonical")
    return path


def load_review(path: Path, *, forbidden_roots: tuple[Path, ...] = ()) -> tuple[dict[str, Any], dict[str, object]]:
    path = _canonical_absolute(path, "review")
    if any(path == root or root in path.parents for root in forbidden_roots):
        raise ReviewError("review_not_external")
    try:
        info = path.lstat()
        parent = path.parent.lstat()
    except OSError as exc:
        raise ReviewError("review_unreadable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size <= 0
        or info.st_size > MAX_REVIEW_BYTES
        or not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ReviewError("review_unsafe")
    try:
        content = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise ReviewError("review_unreadable") from exc
    if (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ReviewError("review_changed_while_reading")
    document = _strict_json(content)
    if not isinstance(document, dict):
        raise ReviewError("review_schema_invalid")
    if canonical_json(document) != content:
        raise ReviewError("review_not_canonical")
    return document, {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _git_env() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": "/tmp",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _git(root: Path, *args: str, allow_empty: bool = False) -> bytes:
    completed = subprocess.run(
        [
            "/usr/bin/git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(root),
            *args,
        ],
        check=False,
        capture_output=True,
        env=_git_env(),
    )
    if completed.returncode != 0 or (not allow_empty and not completed.stdout.strip()):
        raise ReviewError("repository_identity_failed")
    return completed.stdout


def _git_text(root: Path, *args: str) -> str:
    return _git(root, *args).decode("utf-8", errors="strict").strip()


def repository_identity(
    root: Path,
    *,
    baseline: str,
    expected_remote: str,
) -> dict[str, object]:
    root = _canonical_absolute(root, "repository_root")
    if Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ReviewError("repository_toplevel_mismatch")
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        allow_empty=True,
    )
    verbose = tuple(
        item for item in _git(root, "ls-files", "-v", "-z").split(b"\0") if item
    )
    tagged = tuple(
        item for item in _git(root, "ls-files", "-t", "-z").split(b"\0") if item
    )
    hidden = [
        item
        for item in (*verbose, *tagged)
        if item[:1] == b"S" or item[:1].decode("ascii").islower()
    ]
    if status or hidden or _git(root, "ls-files", "-u", "-z", allow_empty=True):
        raise ReviewError("repository_not_clean")
    for args in (
        ("diff-index", "--quiet", "--cached", "HEAD", "--"),
        ("diff-files", "--quiet", "--"),
    ):
        completed = subprocess.run(
            ["/usr/bin/git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            env=_git_env(),
        )
        if completed.returncode != 0 or completed.stdout or completed.stderr:
            raise ReviewError("repository_not_clean")
    branch = _git_text(root, "symbolic-ref", "--short", "HEAD")
    remote = _git_text(root, "remote", "get-url", "github")
    if branch != BRANCH or remote != expected_remote:
        raise ReviewError("repository_release_identity_mismatch")
    ancestry = subprocess.run(
        ["/usr/bin/git", "-C", str(root), "merge-base", "--is-ancestor", baseline, "HEAD"],
        check=False,
        capture_output=True,
        env=_git_env(),
    )
    if ancestry.returncode != 0 or ancestry.stdout or ancestry.stderr:
        raise ReviewError("repository_baseline_not_ancestor")
    return {
        "baseline": baseline,
        "baseline_commit": _git_text(root, "rev-parse", f"{baseline}^{{commit}}"),
        "baseline_is_ancestor": True,
        "branch": branch,
        "clean": True,
        "clean_status_sha256": hashlib.sha256(status).hexdigest(),
        "commit": _git_text(root, "rev-parse", "HEAD"),
        "github_remote_url": remote,
        "hidden_index_entry_count": 0,
        "root": str(root),
        "tree": _git_text(root, "rev-parse", "HEAD^{tree}"),
    }


def collect_scope(hqa_root: Path, platform_root: Path) -> dict[str, object]:
    expected_platform = hqa_root.parent / "ai-quant-platform"
    if platform_root != expected_platform:
        raise ReviewError("platform_root_mismatch")
    return {
        "hqa": repository_identity(
            hqa_root,
            baseline=HQA_BASELINE,
            expected_remote=HQA_REMOTE,
        ),
        "platform": repository_identity(
            platform_root,
            baseline=PLATFORM_BASELINE,
            expected_remote=PLATFORM_REMOTE,
        ),
    }


def validate_review(
    document: object,
    *,
    mode: str,
    scope: dict[str, object],
) -> dict[str, object]:
    if not isinstance(document, dict) or set(document) != {
        "schema",
        "mode",
        "reviewer",
        "scope",
        "findings",
        "verdict",
    }:
        raise ReviewError("review_schema_invalid")
    if document["schema"] != REVIEW_SCHEMA or document["mode"] != mode:
        raise ReviewError("review_mode_or_schema_mismatch")
    reviewer = document["reviewer"]
    if (
        not isinstance(reviewer, dict)
        or set(reviewer) != {"identity", "independence_attested"}
        or not isinstance(reviewer["identity"], str)
        or not reviewer["identity"].strip()
        or reviewer["identity"] != reviewer["identity"].strip()
        or reviewer["independence_attested"] is not True
    ):
        raise ReviewError("reviewer_invalid")
    if document["scope"] != scope:
        raise ReviewError("review_scope_mismatch")
    findings = document["findings"]
    if not isinstance(findings, list):
        raise ReviewError("findings_invalid")
    counts = {
        "admissible_open_p0": 0,
        "admissible_open_p1": 0,
        "admissible_open_blocking_p2": 0,
        "total": len(findings),
    }
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != FINDING_FIELDS:
            raise ReviewError("finding_schema_invalid")
        severity = finding["severity"]
        if severity not in SEVERITIES:
            raise ReviewError("finding_severity_invalid")
        for field in ("affected_reference", "concrete_scenario", "direct_evidence"):
            value = finding[field]
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ReviewError(f"finding_{field}_invalid")
        for field in ("admissible", "open", "blocking"):
            if type(finding[field]) is not bool:
                raise ReviewError(f"finding_{field}_invalid")
        if severity in {"P0", "P1"} and finding["blocking"] is not True:
            raise ReviewError("finding_blocking_inconsistent")
        if severity == "P3" and finding["blocking"] is not False:
            raise ReviewError("finding_blocking_inconsistent")
        if finding["admissible"] and finding["open"]:
            if severity == "P0":
                counts["admissible_open_p0"] += 1
            elif severity == "P1":
                counts["admissible_open_p1"] += 1
            elif severity == "P2" and finding["blocking"]:
                counts["admissible_open_blocking_p2"] += 1
    blocked = any(counts[key] for key in counts if key != "total")
    expected_verdict = "NEEDS_WORK" if blocked else "CLEAR"
    if document["verdict"] != expected_verdict:
        raise ReviewError("review_verdict_inconsistent")
    return {
        "counts": counts,
        "reviewer": reviewer,
        "verdict": expected_verdict,
    }


def _prepare_output(path: Path, roots: tuple[Path, ...]) -> Path:
    path = _canonical_absolute(path, "output_dir")
    if any(path == root or root in path.parents for root in roots):
        raise ReviewError("output_dir_not_external")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise ReviewError("output_parent_unsafe") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) & 0o022
    ):
        raise ReviewError("output_parent_unsafe")
    try:
        if path.exists():
            info = path.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
                or any(path.iterdir())
            ):
                raise ReviewError("output_dir_unsafe")
        else:
            path.mkdir(mode=0o700)
    except ReviewError:
        raise
    except OSError as exc:
        raise ReviewError("output_dir_unsafe") from exc
    return path


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ReviewError("receipt_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def verify(
    *,
    hqa_root: Path,
    platform_root: Path,
    mode: str,
    review_path: Path,
    output_dir: Path,
) -> tuple[int, dict[str, object]]:
    if mode not in MODES:
        raise ReviewError("mode_invalid")
    hqa_root = _canonical_absolute(hqa_root, "hqa_root")
    platform_root = _canonical_absolute(platform_root, "platform_root")
    scope = collect_scope(hqa_root, platform_root)
    review, artifact = load_review(
        review_path,
        forbidden_roots=(hqa_root, platform_root),
    )
    result = validate_review(review, mode=mode, scope=scope)
    output = _prepare_output(output_dir, (hqa_root, platform_root))
    exit_code = 0 if result["verdict"] == "CLEAR" else 1
    receipt = {
        "contract": CONTRACT,
        "exit_code": exit_code,
        "mode": mode,
        "repositories": scope,
        "review": {
            "artifact": artifact,
            **result,
        },
        "status": "verified",
    }
    receipt_path = output / "review-verifier-receipt.json"
    _write_exclusive(receipt_path, canonical_json(receipt))
    summary = {
        "contract": CONTRACT,
        "exit_code": exit_code,
        "receipt": str(receipt_path),
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "verdict": result["verdict"],
    }
    return exit_code, summary


class _FailClosedParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ReviewError("public_arguments_invalid")


def _parse_args() -> argparse.Namespace:
    parser = _FailClosedParser(add_help=False)
    parser.add_argument("--hqa-root", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--public-entrypoint", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--platform-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    hqa_root = args.hqa_root.resolve()
    expected_helper = hqa_root / "scripts" / "verify_rehearsal_review.py"
    expected_wrapper = hqa_root / "scripts" / "verify_rehearsal_review.sh"
    if Path(__file__).resolve() != expected_helper:
        raise ReviewError("helper_path_mismatch")
    if Path(args.public_entrypoint).resolve() != expected_wrapper:
        raise ReviewError("public_entrypoint_mismatch")
    exit_code, summary = verify(
        hqa_root=hqa_root,
        platform_root=args.platform_root,
        mode=args.mode,
        review_path=args.review,
        output_dir=args.output_dir,
    )
    sys.stdout.buffer.write(canonical_json(summary) + b"\n")
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReviewError as exc:
        print(f"rehearsal_review_error={exc}", file=sys.stderr, flush=True)
        raise SystemExit(78) from exc
