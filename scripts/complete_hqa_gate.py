#!/usr/bin/env python3
"""Fail-closed authority for the complete HQA test gate."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


POPULATION_SCHEMA = "hqa.complete-hqa-population.v1"
EXPECTED_SKIPS = {
    "tests/test_aihot.py::test_fetch_items_live_smoke": (
        "network; flip to run a live smoke test manually"
    ),
    "tests/test_quant_cli.py::test_run_doctor_integration_real": (
        "manual — requires working quant-system environment; "
        "run with --no-skip to verify live"
    ),
}
MINIMUM_PASSED = 2012
_OUTCOMES = frozenset(
    {"passed", "failed", "error", "skipped", "xfailed", "xpassed"}
)
_MAX_JUNIT_BYTES = 64 * 1024 * 1024
_MAX_JSON_BYTES = 64 * 1024 * 1024
_GIT = "/usr/bin/git"
_GIT_TIMEOUT_SECONDS = 30
_PYTEST_TIMEOUT_SECONDS = 30 * 60
_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_BRANCH = "codex/agent-v0-2-release"
_PUBLIC_FLAGS = frozenset(
    {
        "--python",
        "--output-dir",
        "--expected-commit",
        "--hermes-live",
        "--integration-worktree",
        "--hermes-python",
    }
)


class GateError(ValueError):
    """The complete-HQA gate cannot prove its frozen contract."""


def _canonical_json(document: object) -> bytes:
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def load_canonical_json(content: bytes, *, field: str) -> object:
    """Parse bounded UTF-8 JSON, reject duplicates, and require canonical bytes."""

    if not isinstance(content, bytes) or not content:
        raise GateError("%s_empty" % field)
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GateError("%s_not_utf8" % field) from exc

    def pairs_hook(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise GateError("%s_duplicate_key" % field)
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise GateError("%s_nonfinite" % field)

    try:
        document = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except GateError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise GateError("%s_invalid" % field) from exc
    if _canonical_json(document) != content:
        raise GateError("%s_not_canonical" % field)
    return document


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_exclusive(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags, mode)
    except OSError as exc:
        raise GateError("output_create_failed") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _git_environment() -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": "/tmp",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _git_argv(root: Path, *arguments: str) -> list[str]:
    return [
        _GIT,
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "credential.helper=",
        "-C",
        str(root),
        *arguments,
    ]


def _git_bytes(
    root: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            _git_argv(root, *arguments),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError("git_timeout") from exc
    if check and completed.returncode != 0:
        raise GateError("git_command_failed")
    return completed


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return _git_bytes(root, *arguments).stdout.decode(
            "utf-8", errors="strict"
        ).strip()
    except UnicodeDecodeError as exc:
        raise GateError("git_output_not_utf8") from exc


def _require_oid(value: str, field: str) -> str:
    if _OID_RE.fullmatch(value) is None:
        raise GateError("%s_invalid" % field)
    return value


def _hidden_index_paths(raw: bytes) -> list[str]:
    hidden = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise GateError("index_state_invalid")
        marker = record[:1]
        if marker == b"S" or marker.islower():
            try:
                hidden.append(record[2:].decode("utf-8", errors="strict"))
            except UnicodeDecodeError as exc:
                raise GateError("index_path_not_utf8") from exc
    return sorted(hidden)


def capture_repository_identity(
    root_value: Path,
    *,
    expected_commit: str,
    expected_branch: str,
) -> dict[str, Any]:
    """Capture a clean checkout identity, including hidden index state."""

    root = Path(root_value).resolve(strict=True)
    top_level = Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve(
        strict=True
    )
    if top_level != root:
        raise GateError("repository_root_mismatch")
    expected_commit = _require_oid(expected_commit, "expected_commit")
    branch = _git_text(root, "branch", "--show-current")
    head = _require_oid(
        _git_text(root, "rev-parse", "--verify", "HEAD^{commit}"),
        "head",
    )
    tree = _require_oid(
        _git_text(root, "rev-parse", "--verify", "HEAD^{tree}"),
        "tree",
    )
    status = _git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    conflicts = _git_bytes(root, "ls-files", "-u", "-z").stdout
    hidden = _hidden_index_paths(_git_bytes(root, "ls-files", "-v", "-z").stdout)
    index_matches_head = (
        _git_bytes(root, "diff", "--cached", "--quiet", "HEAD", "--", check=False)
        .returncode
        == 0
    )
    worktree_matches_index = (
        _git_bytes(root, "diff", "--quiet", "--", check=False).returncode == 0
    )
    if hidden:
        raise GateError("hidden_index_state")
    if (
        branch != expected_branch
        or head != expected_commit
        or status
        or conflicts
        or not index_matches_head
        or not worktree_matches_index
    ):
        raise GateError("checkout_not_clean_or_exact")

    github_url_completed = _git_bytes(
        root, "config", "--get", "remote.github.url", check=False
    )
    github_url = (
        github_url_completed.stdout.decode("utf-8", errors="strict").strip()
        if github_url_completed.returncode == 0
        else None
    )
    publication_ref = "refs/remotes/github/%s" % expected_branch
    publication_completed = _git_bytes(
        root, "rev-parse", "--verify", publication_ref, check=False
    )
    publication_commit = (
        _require_oid(
            publication_completed.stdout.decode("ascii", errors="strict").strip(),
            "publication_commit",
        )
        if publication_completed.returncode == 0
        else None
    )
    return {
        "branch": branch,
        "clean": True,
        "conflict_count": 0,
        "github_remote_url": github_url,
        "head": head,
        "hidden_index_paths": [],
        "index_matches_head": True,
        "publication_commit": publication_commit,
        "publication_ref": publication_ref,
        "repository_root": str(root),
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "tree": tree,
        "worktree_matches_index": True,
    }


def capture_tests_identity(root_value: Path, commit: str) -> dict[str, Any]:
    """Bind every committed byte below tests/ to one canonical manifest."""

    root = Path(root_value).resolve(strict=True)
    commit = _require_oid(commit, "tests_commit")
    raw = _git_bytes(root, "ls-tree", "-r", "-z", commit, "--", "tests").stdout
    files = []
    seen = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GateError("tests_tree_invalid") from exc
        if (
            kind != b"blob"
            or mode not in {b"100644", b"100755"}
            or not path.startswith("tests/")
            or path in seen
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise GateError("tests_tree_invalid")
        _require_oid(object_id.decode("ascii", errors="strict"), "test_object")
        live = root / path
        if not live.is_file() or live.is_symlink():
            raise GateError("tests_live_file_invalid")
        content = live.read_bytes()
        files.append(
            {
                "bytes": len(content),
                "mode": mode.decode("ascii"),
                "object_id": object_id.decode("ascii"),
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        seen.add(path)
    files.sort(key=lambda item: item["path"])
    if not files:
        raise GateError("tests_tree_empty")
    tree = _require_oid(
        _git_text(root, "rev-parse", "--verify", "%s:tests" % commit),
        "tests_tree",
    )
    return {
        "file_count": len(files),
        "files": files,
        "manifest_sha256": hashlib.sha256(_canonical_json(files)).hexdigest(),
        "python_test_file_count": sum(
            item["path"].rsplit("/", 1)[-1].startswith("test_")
            and item["path"].endswith(".py")
            for item in files
        ),
        "tree": tree,
    }


def _require_exact_keys(
    value: Mapping[str, Any], expected: Sequence[str], field: str
) -> None:
    if set(value) != set(expected):
        raise GateError("%s_fields_invalid" % field)


def validate_population(
    document: object,
    *,
    expected_skips: Mapping[str, str],
    minimum_passed: int,
) -> dict[str, Any]:
    """Validate exact collected nodes, outcomes, and declared skip identities."""

    if not isinstance(document, dict):
        raise GateError("population_not_object")
    _require_exact_keys(
        document,
        (
            "schema_version",
            "collected_node_ids",
            "deselected_node_ids",
            "outcomes",
        ),
        "population",
    )
    if document["schema_version"] != POPULATION_SCHEMA:
        raise GateError("population_schema_invalid")
    collected = document["collected_node_ids"]
    deselected = document["deselected_node_ids"]
    outcomes = document["outcomes"]
    if (
        not isinstance(collected, list)
        or not collected
        or any(not isinstance(node_id, str) or not node_id for node_id in collected)
        or collected != sorted(collected)
        or len(collected) != len(set(collected))
    ):
        raise GateError("population_node_ids_invalid")
    if (
        not isinstance(deselected, list)
        or any(
            not isinstance(node_id, str) or not node_id
            for node_id in deselected
        )
        or deselected != sorted(deselected)
        or len(deselected) != len(set(deselected))
    ):
        raise GateError("population_deselected_invalid")
    if deselected:
        raise GateError("tests_deselected")
    if not isinstance(outcomes, list) or len(outcomes) != len(collected):
        raise GateError("population_outcomes_invalid")

    observed_by_node: dict[str, tuple[str, object]] = {}
    counts = {name: 0 for name in _OUTCOMES}
    for record in outcomes:
        if not isinstance(record, dict):
            raise GateError("population_outcome_invalid")
        _require_exact_keys(record, ("node_id", "outcome", "reason"), "outcome")
        node_id = record["node_id"]
        outcome = record["outcome"]
        reason = record["reason"]
        if (
            not isinstance(node_id, str)
            or node_id not in collected
            or node_id in observed_by_node
            or outcome not in _OUTCOMES
            or (
                outcome in {"passed", "failed", "error"}
                and reason is not None
            )
            or (
                outcome in {"skipped", "xfailed", "xpassed"}
                and (not isinstance(reason, str) or not reason)
            )
        ):
            raise GateError("population_outcome_invalid")
        observed_by_node[node_id] = (outcome, reason)
        counts[outcome] += 1
    if sorted(observed_by_node) != collected:
        raise GateError("population_outcomes_incomplete")

    observed_skips = {
        node_id: reason
        for node_id, (outcome, reason) in observed_by_node.items()
        if outcome == "skipped"
    }
    if observed_skips != dict(expected_skips):
        raise GateError("skip_set_not_declared")
    if counts["xfailed"] or counts["xpassed"]:
        raise GateError("unexpected_xfail")
    if counts["failed"] or counts["error"]:
        raise GateError("failed_testcases")
    if counts["passed"] < minimum_passed:
        raise GateError("passed_count_below_baseline")

    return {
        "collected": len(collected),
        "errors": counts["error"],
        "failed": counts["failed"],
        "node_ids": collected,
        "passed": counts["passed"],
        "skipped": counts["skipped"],
        "skips": [
            {"node_id": node_id, "reason": observed_skips[node_id]}
            for node_id in sorted(observed_skips)
        ],
        "xfailed": counts["xfailed"],
        "xpassed": counts["xpassed"],
    }


def _local_xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _declared_xml_count(element: ET.Element, field: str) -> Optional[int]:
    value = element.attrib.get(field)
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        raise GateError("junit_declared_count_invalid")
    return int(value)


def validate_junit(
    content: bytes,
    *,
    pytest_exit: int,
    population_result: Mapping[str, Any],
    expected_skip_reasons: Sequence[str],
) -> dict[str, int]:
    """Validate bounded JUnit and reconcile it with the exact node manifest."""

    if pytest_exit != 0:
        raise GateError("pytest_exit_nonzero:%s" % pytest_exit)
    if not content or len(content) > _MAX_JUNIT_BYTES:
        raise GateError("junit_empty_or_oversized")
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GateError("junit_not_utf8") from exc
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise GateError("junit_forbidden_xml")
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, RecursionError) as exc:
        raise GateError("junit_malformed") from exc
    if _local_xml_name(root.tag) not in {"testsuite", "testsuites"}:
        raise GateError("junit_root_invalid")

    testcases = [
        element
        for element in root.iter()
        if _local_xml_name(element.tag) == "testcase"
    ]
    if not testcases:
        raise GateError("junit_zero_collection")
    counts = {
        "errors": 0,
        "failed": 0,
        "passed": 0,
        "skipped": 0,
        "tests": len(testcases),
        "xfail": 0,
    }
    skip_reasons = []
    junit_node_ids = []
    for testcase in testcases:
        node_properties = [
            element.attrib.get("value")
            for element in testcase.iter()
            if _local_xml_name(element.tag) == "property"
            and element.attrib.get("name") == "hqa_node_id"
        ]
        if (
            len(node_properties) != 1
            or not isinstance(node_properties[0], str)
            or not node_properties[0]
        ):
            raise GateError("junit_node_ids_invalid")
        junit_node_ids.append(node_properties[0])
        outcomes = [
            child
            for child in testcase
            if _local_xml_name(child.tag) in {"error", "failure", "skipped"}
        ]
        if len(outcomes) > 1:
            raise GateError("junit_conflicting_testcase_outcomes")
        if not outcomes:
            counts["passed"] += 1
            continue
        outcome = outcomes[0]
        kind = _local_xml_name(outcome.tag)
        if kind == "error":
            counts["errors"] += 1
        elif kind == "failure":
            counts["failed"] += 1
        else:
            skip_type = outcome.attrib.get("type", "")
            reason = outcome.attrib.get("message")
            if "xfail" in skip_type.casefold():
                counts["xfail"] += 1
            else:
                if not isinstance(reason, str) or not reason:
                    raise GateError("junit_skip_reason_missing")
                counts["skipped"] += 1
                skip_reasons.append(reason)

    for container in (
        element
        for element in root.iter()
        if _local_xml_name(element.tag) in {"testsuite", "testsuites"}
    ):
        descendants = [
            element
            for element in container.iter()
            if _local_xml_name(element.tag) == "testcase"
        ]
        if not descendants:
            continue
        actual = {
            "tests": len(descendants),
            "errors": 0,
            "failures": 0,
            "skipped": 0,
        }
        for testcase in descendants:
            names = {
                _local_xml_name(child.tag)
                for child in testcase
                if _local_xml_name(child.tag) in {"error", "failure", "skipped"}
            }
            actual["errors"] += int("error" in names)
            actual["failures"] += int("failure" in names)
            actual["skipped"] += int("skipped" in names)
        for field, observed in actual.items():
            declared = _declared_xml_count(container, field)
            if declared is not None and declared != observed:
                raise GateError("junit_container_count_drift")

    if counts["xfail"]:
        raise GateError("junit_xfail_forbidden")
    population_node_ids = population_result.get("node_ids")
    if (
        not isinstance(population_node_ids, list)
        or len(junit_node_ids) != len(set(junit_node_ids))
        or sorted(junit_node_ids) != population_node_ids
    ):
        raise GateError("junit_node_ids_invalid")
    if sorted(skip_reasons) != sorted(expected_skip_reasons):
        raise GateError("junit_skip_reasons_invalid")
    expected = {
        "errors": population_result.get("errors"),
        "failed": population_result.get("failed"),
        "passed": population_result.get("passed"),
        "skipped": population_result.get("skipped"),
        "tests": population_result.get("collected"),
    }
    observed = {key: counts[key] for key in expected}
    if observed != expected:
        raise GateError("junit_population_mismatch")
    return counts


def write_pytest_driver(path: Path, population_path: Path) -> None:
    """Write the committed-hook driver that records real pytest node outcomes."""

    source = """\
import json
import os
import sys

import pytest

POPULATION_PATH = %r
SCHEMA = %r
PRIORITY = {
    "passed": 1,
    "skipped": 2,
    "xfailed": 3,
    "xpassed": 4,
    "failed": 5,
    "error": 6,
}


def canonical(document):
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def normalize_reason(value):
    reason = str(value)
    for prefix in ("Skipped: ", "XFailed: "):
        if reason.startswith(prefix):
            reason = reason[len(prefix):]
    return reason


class PopulationPlugin:
    def __init__(self):
        self.collected = []
        self.deselected = []
        self.outcomes = {}

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]
        for item in session.items:
            item.user_properties.append(("hqa_node_id", item.nodeid))

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    def record(self, node_id, outcome, reason):
        previous = self.outcomes.get(node_id)
        if previous is None or PRIORITY[outcome] > PRIORITY[previous["outcome"]]:
            self.outcomes[node_id] = {
                "node_id": node_id,
                "outcome": outcome,
                "reason": reason,
            }

    def pytest_runtest_logreport(self, report):
        was_xfail = getattr(report, "wasxfail", None)
        if report.failed:
            self.record(
                report.nodeid,
                "failed" if report.when == "call" else "error",
                None,
            )
        elif report.skipped:
            if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
                reason = normalize_reason(report.longrepr[2])
            else:
                reason = normalize_reason(was_xfail or report.longrepr)
            self.record(
                report.nodeid,
                "xfailed" if was_xfail else "skipped",
                reason,
            )
        elif report.when == "call" and report.passed:
            self.record(
                report.nodeid,
                "xpassed" if was_xfail else "passed",
                normalize_reason(was_xfail) if was_xfail else None,
            )

    def pytest_sessionfinish(self, session, exitstatus):
        collected = sorted(self.collected)
        outcomes = []
        for node_id in collected:
            outcomes.append(
                self.outcomes.get(
                    node_id,
                    {
                        "node_id": node_id,
                        "outcome": "error",
                        "reason": None,
                    },
                )
            )
        document = {
            "schema_version": SCHEMA,
            "collected_node_ids": collected,
            "deselected_node_ids": sorted(set(self.deselected)),
            "outcomes": sorted(outcomes, key=lambda item: item["node_id"]),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(POPULATION_PATH, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical(document))
            handle.flush()
            os.fsync(handle.fileno())


plugin = PopulationPlugin()
raise SystemExit(int(pytest.main(sys.argv[1:], plugins=[plugin])))
""" % (str(population_path), POPULATION_SCHEMA)
    _write_exclusive(path, source.encode("utf-8", errors="strict"))


def _require_probe_path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise GateError("%s_invalid" % field)
    try:
        return Path(value).resolve(strict=True)
    except OSError as exc:
        raise GateError("%s_invalid" % field) from exc


def _require_python_version(value: object, field: str) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(item) is not int or item < 0 for item in value)
        or value[:2] != [3, 11]
    ):
        raise GateError("%s_invalid" % field)
    return value


def _validate_direct_url(
    value: object,
    *,
    expected_url: str,
    expected_editable: bool,
    error: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(error)
    _require_exact_keys(value, ("url", "dir_info"), "direct_url")
    directory_info = value["dir_info"]
    if (
        value["url"] != expected_url
        or not isinstance(directory_info, dict)
        or set(directory_info) != {"editable"}
        or directory_info["editable"] is not expected_editable
    ):
        raise GateError(error)
    return value


def _validate_dependency_inventory(
    value: object,
    *,
    required: Mapping[str, str],
    error: str,
) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise GateError(error)
    inventory = []
    normalized_names = set()
    for record in value:
        if not isinstance(record, dict):
            raise GateError(error)
        _require_exact_keys(record, ("name", "version"), "dependency")
        name = record["name"]
        version = record["version"]
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(version, str)
            or not version
            or name.casefold() in normalized_names
        ):
            raise GateError(error)
        normalized_names.add(name.casefold())
        inventory.append({"name": name, "version": version})
    if inventory != sorted(
        inventory,
        key=lambda item: (
            item["name"].casefold(),
            item["name"],
            item["version"],
        ),
    ):
        raise GateError(error)
    versions = {item["name"].casefold(): item["version"] for item in inventory}
    if any(versions.get(name.casefold()) != version for name, version in required.items()):
        raise GateError(error)
    return inventory


def validate_hqa_environment_probe(
    document: object,
    *,
    repository_root: Path,
    python_path: Path,
    expected_installed_files: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate the exact non-editable HQA environment used by pytest."""

    if not isinstance(document, dict):
        raise GateError("hqa_environment_probe_invalid")
    _require_exact_keys(
        document,
        (
            "schema_version",
            "sys_executable",
            "sys_prefix",
            "python",
            "module_file",
            "dependency_inventory",
            "distribution_name",
            "distribution_version",
            "distribution_root",
            "direct_url",
            "installed_files",
            "pth_files",
            "pytest_version",
        ),
        "hqa_environment_probe",
    )
    if document["schema_version"] != "hqa.complete-hqa-environment-probe.v1":
        raise GateError("hqa_environment_probe_invalid")
    root = Path(repository_root).resolve(strict=True)
    expected_python = Path(python_path).absolute()
    if Path(document["sys_executable"]).absolute() != expected_python:
        raise GateError("hqa_python_identity_invalid")
    environment = expected_python.parent.parent
    prefix = _require_probe_path(document["sys_prefix"], "hqa_sys_prefix")
    module = _require_probe_path(document["module_file"], "hqa_module")
    distribution = _require_probe_path(
        document["distribution_root"], "hqa_distribution"
    )
    if (
        prefix != environment.resolve(strict=True)
        or environment not in module.parents
        or environment not in distribution.parents
        or module != distribution / "hqa" / "__init__.py"
        or document["distribution_name"] != "hermes-quant-agent"
        or document["distribution_version"] != "0.2.2"
        or document["pytest_version"] != "8.4.2"
    ):
        raise GateError("hqa_install_identity_invalid")
    _require_python_version(document["python"], "hqa_python_version")
    _validate_dependency_inventory(
        document["dependency_inventory"],
        required={
            "hermes-quant-agent": "0.2.2",
            "pytest": "8.4.2",
        },
        error="hqa_dependency_inventory_invalid",
    )
    direct_url = _validate_direct_url(
        document["direct_url"],
        expected_url=root.as_uri(),
        expected_editable=False,
        error="hqa_direct_url_invalid",
    )
    installed_files = document["installed_files"]
    if (
        not isinstance(installed_files, list)
        or installed_files != list(expected_installed_files)
    ):
        raise GateError("hqa_installed_files_invalid")
    pth_files = document["pth_files"]
    if not isinstance(pth_files, list):
        raise GateError("hqa_pth_files_invalid")
    for record in pth_files:
        if not isinstance(record, dict):
            raise GateError("hqa_pth_files_invalid")
        _require_exact_keys(record, ("name", "lines"), "pth")
        lines = record["lines"]
        if (
            not isinstance(record["name"], str)
            or not isinstance(lines, list)
            or any(
                not isinstance(line, str)
                or (
                    line
                    and not line.lstrip().startswith("#")
                    and line != "import _virtualenv"
                )
                for line in lines
            )
        ):
            raise GateError("hqa_pth_files_invalid")
    return {
        **document,
        "direct_url": direct_url,
        "verified": True,
    }


def validate_hermes_environment_probe(
    document: object,
    *,
    live_root: Path,
    integration_root: Path,
    python_path: Path,
) -> dict[str, Any]:
    """Validate Hermes install metadata against its exact integration source."""

    if not isinstance(document, dict):
        raise GateError("hermes_environment_probe_invalid")
    _require_exact_keys(
        document,
        (
            "schema_version",
            "sys_executable",
            "sys_prefix",
            "python",
            "module_file",
            "dependency_inventory",
            "distribution_name",
            "distribution_version",
            "distribution_root",
            "direct_url",
        ),
        "hermes_environment_probe",
    )
    if document["schema_version"] != "hqa.complete-hqa-hermes-probe.v1":
        raise GateError("hermes_environment_probe_invalid")
    live = Path(live_root).resolve(strict=True)
    integration = Path(integration_root).resolve(strict=True)
    expected_python = Path(python_path).absolute()
    if Path(document["sys_executable"]).absolute() != expected_python:
        raise GateError("hermes_python_identity_invalid")
    prefix = _require_probe_path(document["sys_prefix"], "hermes_sys_prefix")
    module = _require_probe_path(document["module_file"], "hermes_module")
    distribution = _require_probe_path(
        document["distribution_root"], "hermes_distribution"
    )
    environment = live / "venv"
    if (
        prefix != environment.resolve(strict=True)
        or environment not in distribution.parents
        or module != integration / "hermes_cli" / "__init__.py"
        or document["distribution_name"] != "hermes-agent"
        or document["distribution_version"] != "0.19.0"
    ):
        raise GateError("hermes_install_identity_invalid")
    _require_python_version(document["python"], "hermes_python_version")
    _validate_dependency_inventory(
        document["dependency_inventory"],
        required={"hermes-agent": "0.19.0"},
        error="hermes_dependency_inventory_invalid",
    )
    direct_url = _validate_direct_url(
        document["direct_url"],
        expected_url=integration.as_uri(),
        expected_editable=True,
        error="hermes_direct_url_invalid",
    )
    return {
        **document,
        "direct_url": direct_url,
        "verified": True,
    }


def parse_run_arguments(arguments: Sequence[str]) -> dict[str, Any]:
    """Parse the six mandatory public flags, each exactly once."""

    values = list(arguments)
    if len(values) != len(_PUBLIC_FLAGS) * 2:
        raise GateError("public_run_flags_invalid")
    parsed: dict[str, str] = {}
    for offset in range(0, len(values), 2):
        flag = values[offset]
        value = values[offset + 1]
        if flag not in _PUBLIC_FLAGS or flag in parsed or not value:
            raise GateError("public_run_flags_invalid")
        parsed[flag] = value
    if set(parsed) != _PUBLIC_FLAGS:
        raise GateError("public_run_flags_invalid")
    commit = _require_oid(parsed["--expected-commit"], "expected_commit")

    def absolute_input(flag: str, field: str) -> Path:
        candidate = Path(parsed[flag])
        if not candidate.is_absolute() or not candidate.exists():
            raise GateError("%s_invalid" % field)
        return candidate.absolute()

    output = Path(parsed["--output-dir"])
    if not output.is_absolute():
        raise GateError("output_dir_invalid")
    return {
        "expected_commit": commit,
        "hermes_live": absolute_input("--hermes-live", "hermes_live"),
        "hermes_python": absolute_input("--hermes-python", "hermes_python"),
        "integration_worktree": absolute_input(
            "--integration-worktree", "integration_worktree"
        ),
        "output_dir": output.absolute(),
        "python": absolute_input("--python", "python"),
    }


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def prepare_output_directory(
    output_value: Path, *, repository_root: Path
) -> Path:
    """Create one new owner-only evidence directory outside the checkout."""

    output = Path(output_value)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise GateError("output_dir_not_new")
    try:
        parent = output.parent.resolve(strict=True)
        repository = Path(repository_root).resolve(strict=True)
    except OSError as exc:
        raise GateError("output_parent_invalid") from exc
    if (
        output.parent.is_symlink()
        or output.parent.absolute() != parent
        or parent.stat().st_mode & 0o077
        or _is_within(parent, repository)
        or _is_within(repository, parent)
    ):
        raise GateError("output_parent_invalid")
    try:
        os.mkdir(str(output), mode=0o700)
        os.chmod(str(output), 0o700)
    except OSError as exc:
        raise GateError("output_create_failed") from exc
    return output


def _committed_file_records(
    root_value: Path,
    commit: str,
    *,
    pathspec: str,
) -> list[dict[str, Any]]:
    root = Path(root_value).resolve(strict=True)
    commit = _require_oid(commit, "manifest_commit")
    raw = _git_bytes(
        root, "ls-tree", "-r", "-z", commit, "--", pathspec
    ).stdout
    records = []
    seen = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
            object_text = object_id.decode("ascii", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GateError("committed_manifest_invalid") from exc
        if (
            kind != b"blob"
            or mode not in {b"100644", b"100755"}
            or path in seen
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise GateError("committed_manifest_invalid")
        _require_oid(object_text, "manifest_object")
        live = root / path
        if not live.is_file() or live.is_symlink():
            raise GateError("committed_live_file_invalid")
        content = live.read_bytes()
        committed = _git_bytes(root, "show", "%s:%s" % (commit, path)).stdout
        if content != committed:
            raise GateError("committed_live_bytes_differ")
        records.append(
            {
                "bytes": len(content),
                "mode": mode.decode("ascii"),
                "object_id": object_text,
                "path": path,
                "sha256": _sha256(content),
            }
        )
        seen.add(path)
    records.sort(key=lambda item: item["path"])
    if not records:
        raise GateError("committed_manifest_empty")
    return records


def capture_authority_identity(
    root_value: Path, commit: str
) -> dict[str, Any]:
    """Bind both executable-command authority files to committed bytes."""

    expected = {
        "scripts/complete_hqa_gate.py": "100644",
        "scripts/verify_agent_v02_complete_hqa.sh": "100755",
    }
    records = _committed_file_records(
        root_value,
        commit,
        pathspec="scripts",
    )
    selected = [item for item in records if item["path"] in expected]
    if (
        len(selected) != len(expected)
        or {item["path"]: item["mode"] for item in selected} != expected
    ):
        raise GateError("authority_files_invalid")
    return {
        "files": selected,
        "manifest_sha256": _sha256(_canonical_json(selected)),
    }


def capture_hqa_source_identity(
    root_value: Path, commit: str
) -> dict[str, Any]:
    """Bind the complete installed HQA package population to source bytes."""

    root = Path(root_value).resolve(strict=True)
    records = _committed_file_records(root, commit, pathspec="hqa")
    if any(not item["path"].startswith("hqa/") for item in records):
        raise GateError("hqa_source_manifest_invalid")
    installed = [
        {
            "bytes": item["bytes"],
            "path": item["path"],
            "sha256": item["sha256"],
        }
        for item in records
    ]
    tree = _require_oid(
        _git_text(root, "rev-parse", "--verify", "%s:hqa" % commit),
        "hqa_tree",
    )
    return {
        "file_count": len(installed),
        "installed_files": installed,
        "manifest_sha256": _sha256(_canonical_json(installed)),
        "tree": tree,
    }


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _file_identity(path_value: Path) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        raise GateError("identity_path_not_absolute")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise GateError("identity_file_missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise GateError("identity_file_unsafe")
    content = path.read_bytes()
    return {
        "bytes": len(content),
        "mode": "%04o" % stat.S_IMODE(metadata.st_mode),
        "path": str(path),
        "sha256": _sha256(content),
    }


def _executable_identity(path_value: Path) -> dict[str, Any]:
    invoked = Path(path_value)
    if not invoked.is_absolute() or not invoked.exists() or not os.access(
        str(invoked), os.X_OK
    ):
        raise GateError("python_not_executable")
    try:
        invoked_stat = invoked.lstat()
        resolved = invoked.resolve(strict=True)
        resolved_stat = resolved.stat()
    except OSError as exc:
        raise GateError("python_identity_failed") from exc
    if not stat.S_ISREG(resolved_stat.st_mode):
        raise GateError("python_identity_failed")
    content = resolved.read_bytes()
    return {
        "hardlink_count": resolved_stat.st_nlink,
        "invoked_mode": "%04o" % stat.S_IMODE(invoked_stat.st_mode),
        "invoked_path": str(invoked),
        "invoked_path_is_symlink": stat.S_ISLNK(invoked_stat.st_mode),
        "owner_uid": resolved_stat.st_uid,
        "resolved_bytes": len(content),
        "resolved_mode": "%04o" % stat.S_IMODE(resolved_stat.st_mode),
        "resolved_path": str(resolved),
        "resolved_sha256": _sha256(content),
    }


_HQA_PROBE_SOURCE = r"""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys

import hqa
import pytest


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("duplicate direct-url key")
        result[key] = value
    return result


distribution = metadata.distribution("hermes-quant-agent")
direct_paths = [
    entry
    for entry in (distribution.files or ())
    if str(entry).endswith(".dist-info/direct_url.json")
]
if len(direct_paths) != 1:
    raise RuntimeError("direct-url metadata missing")
direct_path = Path(distribution.locate_file(direct_paths[0]))
direct_url = json.loads(
    direct_path.read_text(encoding="utf-8"),
    object_pairs_hook=no_duplicates,
)
installed_files = []
for entry in distribution.files or ():
    relative = str(entry)
    if not relative.startswith("hqa/") or "__pycache__" in relative:
        continue
    installed = Path(distribution.locate_file(entry))
    if not installed.is_file() or installed.is_symlink():
        raise RuntimeError("installed package file unsafe")
    content = installed.read_bytes()
    installed_files.append(
        {
            "bytes": len(content),
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    )
installed_files.sort(key=lambda item: item["path"])
distribution_root = Path(distribution.locate_file("")).resolve(strict=True)
dependency_inventory = []
for candidate in metadata.distributions():
    name = candidate.metadata.get("Name")
    version = candidate.version
    if not isinstance(name, str) or not name or not version:
        raise RuntimeError("dependency metadata invalid")
    dependency_inventory.append({"name": name, "version": version})
dependency_inventory.sort(
    key=lambda item: (
        item["name"].casefold(),
        item["name"],
        item["version"],
    )
)
pth_files = []
for pth in sorted(distribution_root.glob("*.pth"), key=lambda item: item.name):
    if not pth.is_file() or pth.is_symlink():
        raise RuntimeError("pth file unsafe")
    pth_files.append(
        {
            "lines": pth.read_text(encoding="utf-8").splitlines(),
            "name": pth.name,
        }
    )
document = {
    "dependency_inventory": dependency_inventory,
    "direct_url": direct_url,
    "distribution_name": "hermes-quant-agent",
    "distribution_root": str(distribution_root),
    "distribution_version": distribution.version,
    "installed_files": installed_files,
    "module_file": str(Path(hqa.__file__).resolve(strict=True)),
    "pth_files": pth_files,
    "pytest_version": pytest.__version__,
    "python": list(sys.version_info[:3]),
    "schema_version": "hqa.complete-hqa-environment-probe.v1",
    "sys_executable": os.path.abspath(sys.executable),
    "sys_prefix": os.path.abspath(sys.prefix),
}
sys.stdout.buffer.write(
    json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")
)
"""


_HERMES_PROBE_SOURCE = r"""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys

import hermes_cli


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("duplicate direct-url key")
        result[key] = value
    return result


distribution = metadata.distribution("hermes-agent")
direct_paths = [
    entry
    for entry in (distribution.files or ())
    if str(entry).endswith(".dist-info/direct_url.json")
]
if len(direct_paths) != 1:
    raise RuntimeError("direct-url metadata missing")
direct_path = Path(distribution.locate_file(direct_paths[0]))
direct_url = json.loads(
    direct_path.read_text(encoding="utf-8"),
    object_pairs_hook=no_duplicates,
)
dependency_inventory = []
for candidate in metadata.distributions():
    name = candidate.metadata.get("Name")
    version = candidate.version
    if not isinstance(name, str) or not name or not version:
        raise RuntimeError("dependency metadata invalid")
    dependency_inventory.append({"name": name, "version": version})
dependency_inventory.sort(
    key=lambda item: (
        item["name"].casefold(),
        item["name"],
        item["version"],
    )
)
document = {
    "dependency_inventory": dependency_inventory,
    "direct_url": direct_url,
    "distribution_name": "hermes-agent",
    "distribution_root": str(
        Path(distribution.locate_file("")).resolve(strict=True)
    ),
    "distribution_version": distribution.version,
    "module_file": str(Path(hermes_cli.__file__).resolve(strict=True)),
    "python": list(sys.version_info[:3]),
    "schema_version": "hqa.complete-hqa-hermes-probe.v1",
    "sys_executable": os.path.abspath(sys.executable),
    "sys_prefix": os.path.abspath(sys.prefix),
}
sys.stdout.buffer.write(
    json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")
)
"""


def _probe_environment(output: Path) -> dict[str, str]:
    runtime_home = output / "runtime" / "home"
    return {
        "HOME": str(runtime_home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(output / "runtime" / "tmp"),
    }


def _run_probe(
    *,
    python: Path,
    source: str,
    output: Path,
    name: str,
) -> object:
    try:
        completed = subprocess.run(
            [str(python), "-I", "-B", "-c", source],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            cwd=str(output),
            env=_probe_environment(output),
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("%s_probe_execution_failed" % name) from exc
    stdout_path = output / ("%s.json" % name)
    stderr_path = output / ("%s.stderr" % name)
    _write_exclusive(stdout_path, completed.stdout)
    _write_exclusive(stderr_path, completed.stderr)
    if completed.returncode != 0:
        raise GateError("%s_probe_exit_nonzero" % name)
    if completed.stderr:
        raise GateError("%s_probe_stderr_nonempty" % name)
    if len(completed.stdout) > _MAX_JSON_BYTES:
        raise GateError("%s_probe_oversized" % name)
    return load_canonical_json(completed.stdout, field="%s_probe" % name)


def _capture_hqa_identity(
    *,
    root: Path,
    expected_commit: str,
    python: Path,
    output: Path,
    phase: str,
) -> dict[str, Any]:
    repository = capture_repository_identity(
        root,
        expected_commit=expected_commit,
        expected_branch=_BRANCH,
    )
    if (
        repository["github_remote_url"]
        != "https://github.com/YIBOWAY/hermes-quant-agent.git"
        or repository["publication_commit"] != expected_commit
    ):
        raise GateError("hqa_publication_identity_invalid")
    source = capture_hqa_source_identity(root, expected_commit)
    probe = _run_probe(
        python=python,
        source=_HQA_PROBE_SOURCE,
        output=output,
        name="hqa-environment-%s" % phase,
    )
    environment = validate_hqa_environment_probe(
        probe,
        repository_root=root,
        python_path=python,
        expected_installed_files=source["installed_files"],
    )
    return {
        "authority": capture_authority_identity(root, expected_commit),
        "environment": environment,
        "executable": _executable_identity(python),
        "inputs": {
            "pyproject": _file_identity(root / "pyproject.toml"),
            "uv_lock": _file_identity(root / "uv.lock"),
        },
        "repository": repository,
        "source": source,
        "tests": capture_tests_identity(root, expected_commit),
    }


def _capture_hermes_identity(
    *,
    live: Path,
    integration: Path,
    python: Path,
    output: Path,
    phase: str,
) -> dict[str, Any]:
    live_resolved = live.resolve(strict=True)
    integration_resolved = integration.resolve(strict=True)
    expected_integration = (
        live_resolved / ".claude" / "worktrees" / "v2-integration"
    ).resolve(strict=True)
    if integration_resolved != expected_integration:
        raise GateError("hermes_integration_path_invalid")
    commit = _require_oid(
        _git_text(integration_resolved, "rev-parse", "--verify", "HEAD^{commit}"),
        "hermes_commit",
    )
    repository = capture_repository_identity(
        integration_resolved,
        expected_commit=commit,
        expected_branch=_BRANCH,
    )
    origin = _git_text(
        integration_resolved, "config", "--get", "remote.origin.url"
    )
    if origin != "https://github.com/NousResearch/hermes-agent.git":
        raise GateError("hermes_origin_invalid")
    probe = _run_probe(
        python=python,
        source=_HERMES_PROBE_SOURCE,
        output=output,
        name="hermes-environment-%s" % phase,
    )
    environment = validate_hermes_environment_probe(
        probe,
        live_root=live_resolved,
        integration_root=integration_resolved,
        python_path=python,
    )
    return {
        "environment": environment,
        "executable": _executable_identity(python),
        "inputs": {
            "gateway_run": _file_identity(integration_resolved / "gateway" / "run.py"),
            "pyproject": _file_identity(integration_resolved / "pyproject.toml"),
            "uv_lock": _file_identity(integration_resolved / "uv.lock"),
        },
        "origin_url": origin,
        "repository": repository,
    }


def _mkdir_private(path: Path) -> None:
    try:
        os.mkdir(str(path), mode=0o700)
        os.chmod(str(path), 0o700)
    except OSError as exc:
        raise GateError("runtime_directory_create_failed") from exc


def _test_environment(
    *,
    output: Path,
    python: Path,
    hermes_live: Path,
    integration: Path,
    hermes_python: Path,
) -> dict[str, str]:
    return {
        "HOME": str(output / "runtime" / "home"),
        "HQA_HERMES_INTEGRATION_WT": str(integration),
        "HQA_HERMES_LIVE": str(hermes_live),
        "HQA_HERMES_VENV_PYTHON": str(hermes_python),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "%s:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        % python.parent,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(output / "runtime" / "pycache"),
        "TEMP": str(output / "runtime" / "tmp"),
        "TMP": str(output / "runtime" / "tmp"),
        "TMPDIR": str(output / "runtime" / "tmp"),
    }


def _open_exclusive(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except OSError as exc:
        raise GateError("log_create_failed") from exc
    return os.fdopen(descriptor, "wb")


def _run_pytest(
    *,
    argv: Sequence[str],
    root: Path,
    environment: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> int:
    with _open_exclusive(stdout_path) as stdout, _open_exclusive(
        stderr_path
    ) as stderr:
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=str(root),
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        except OSError as exc:
            raise GateError("pytest_start_failed") from exc
        try:
            return process.wait(timeout=_PYTEST_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                raise GateError("pytest_timeout_cleanup_unknown") from exc
            raise GateError("pytest_timeout") from exc


def _read_bounded(path: Path, *, maximum: int, field: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise GateError("%s_missing" % field)
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise GateError("%s_empty_or_oversized" % field)
    return path.read_bytes()


def _artifact_identity(path: Path, output: Path) -> dict[str, Any]:
    identity = _file_identity(path)
    try:
        relative = path.relative_to(output)
    except ValueError as exc:
        raise GateError("artifact_outside_output") from exc
    return {
        "bytes": identity["bytes"],
        "mode": identity["mode"],
        "path": str(relative),
        "sha256": identity["sha256"],
    }


def _failure_artifacts(output: Path) -> list[dict[str, Any]]:
    artifacts = []
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if path.is_file() and not path.is_symlink():
            artifacts.append(_artifact_identity(path, output))
    return artifacts


def _write_failure_receipt(
    output: Path,
    *,
    error: str,
    expected_commit: str,
    started_at: str,
) -> None:
    path = output / "complete-hqa-failure.json"
    if path.exists():
        return
    document = {
        "artifacts": _failure_artifacts(output),
        "ended_at": _utc_now(),
        "error": error,
        "expected_commit": expected_commit,
        "schema_version": "hqa.complete-hqa-failure.v1",
        "started_at": started_at,
        "status": "fail",
    }
    _write_exclusive(path, _canonical_json(document))


def run_complete_gate(
    *,
    root: Path,
    parsed: Mapping[str, Any],
    public_argv: Sequence[str],
) -> dict[str, Any]:
    expected_commit = parsed["expected_commit"]
    output = prepare_output_directory(
        parsed["output_dir"],
        repository_root=root,
    )
    started_at = _utc_now()
    monotonic_started = time.monotonic()
    try:
        runtime = output / "runtime"
        _mkdir_private(runtime)
        for name in ("home", "tmp", "pycache", "basetemp"):
            _mkdir_private(runtime / name)

        python = Path(parsed["python"])
        hermes_live = Path(parsed["hermes_live"])
        integration = Path(parsed["integration_worktree"])
        hermes_python = Path(parsed["hermes_python"])
        before = {
            "hermes": _capture_hermes_identity(
                live=hermes_live,
                integration=integration,
                python=hermes_python,
                output=output,
                phase="before",
            ),
            "hqa": _capture_hqa_identity(
                root=root,
                expected_commit=expected_commit,
                python=python,
                output=output,
                phase="before",
            ),
        }

        driver = output / "pytest-driver.py"
        population_path = output / "exact-node-population.json"
        junit = output / "junit.xml"
        stdout_path = output / "pytest.stdout"
        stderr_path = output / "pytest.stderr"
        write_pytest_driver(driver, population_path)
        argv = build_pytest_argv(
            python=python,
            driver=driver,
            junit=junit,
            basetemp=runtime / "basetemp",
        )
        environment = _test_environment(
            output=output,
            python=python,
            hermes_live=hermes_live,
            integration=integration,
            hermes_python=hermes_python,
        )
        pytest_exit = _run_pytest(
            argv=argv,
            root=root,
            environment=environment,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        for artifact in (population_path, junit, stdout_path, stderr_path):
            if artifact.exists():
                os.chmod(str(artifact), 0o600)

        after = {
            "hermes": _capture_hermes_identity(
                live=hermes_live,
                integration=integration,
                python=hermes_python,
                output=output,
                phase="after",
            ),
            "hqa": _capture_hqa_identity(
                root=root,
                expected_commit=expected_commit,
                python=python,
                output=output,
                phase="after",
            ),
        }
        if before != after:
            raise GateError("identity_drift")

        population_content = _read_bounded(
            population_path,
            maximum=_MAX_JSON_BYTES,
            field="population",
        )
        population_document = load_canonical_json(
            population_content,
            field="population",
        )
        population = validate_population(
            population_document,
            expected_skips=EXPECTED_SKIPS,
            minimum_passed=MINIMUM_PASSED,
        )
        junit_content = _read_bounded(
            junit,
            maximum=_MAX_JUNIT_BYTES,
            field="junit",
        )
        junit_result = validate_junit(
            junit_content,
            pytest_exit=pytest_exit,
            population_result=population,
            expected_skip_reasons=tuple(EXPECTED_SKIPS.values()),
        )
        artifact_paths = [
            output / "exact-node-population.json",
            output / "hermes-environment-after.json",
            output / "hermes-environment-after.stderr",
            output / "hermes-environment-before.json",
            output / "hermes-environment-before.stderr",
            output / "hqa-environment-after.json",
            output / "hqa-environment-after.stderr",
            output / "hqa-environment-before.json",
            output / "hqa-environment-before.stderr",
            output / "junit.xml",
            output / "pytest-driver.py",
            output / "pytest.stderr",
            output / "pytest.stdout",
        ]
        artifacts = [
            _artifact_identity(path, output) for path in artifact_paths
        ]
        receipt = {
            "argv": argv,
            "artifacts": artifacts,
            "authority_precedence": (
                "version-controlled executable verification script"
            ),
            "authority_source": {
                "entrypoint": "scripts/verify_agent_v02_complete_hqa.sh",
                "helper": "scripts/complete_hqa_gate.py",
            },
            "bindings": {
                "after": after,
                "before": before,
                "unchanged": True,
            },
            "cwd": str(root),
            "declared_skips": [
                {"node_id": node_id, "reason": EXPECTED_SKIPS[node_id]}
                for node_id in sorted(EXPECTED_SKIPS)
            ],
            "duration_seconds": round(time.monotonic() - monotonic_started, 6),
            "effect_policies": {
                "database": "test-isolated-only",
                "generated_files": "private-output-only",
                "network": "loopback-only",
                "provider_credentials": "absent",
                "trading": "forbidden",
            },
            "ended_at": _utc_now(),
            "environment": dict(environment),
            "environment_base": "empty",
            "environment_names": sorted(environment),
            "expected_commit": expected_commit,
            "expected_exit": 0,
            "junit_counts": junit_result,
            "minimum_passed": MINIMUM_PASSED,
            "population": population,
            "public_argv": list(public_argv),
            "pytest_exit": pytest_exit,
            "schema_version": "hqa.complete-hqa-receipt.v1",
            "selector": "tests",
            "side_effect_class": "complete-hqa-tests",
            "started_at": started_at,
            "status": "pass",
        }
        receipt_path = output / "complete-hqa-receipt.json"
        _write_exclusive(receipt_path, _canonical_json(receipt))
        return {
            "counts": {
                "collected": population["collected"],
                "passed": population["passed"],
                "skipped": population["skipped"],
            },
            "head": expected_commit,
            "receipt": str(receipt_path),
            "schema_version": "hqa.complete-hqa-result.v1",
            "status": "pass",
        }
    except GateError as exc:
        _write_failure_receipt(
            output,
            error=str(exc),
            expected_commit=expected_commit,
            started_at=started_at,
        )
        raise


def describe_contract() -> dict[str, Any]:
    """Return the closed public contract without inspecting mutable state."""

    return {
        "environment_base": "empty",
        "expected_skip_nodes": EXPECTED_SKIPS,
        "junit_required": True,
        "minimum_passed": MINIMUM_PASSED,
        "public_run_flags": sorted(_PUBLIC_FLAGS),
        "schema_version": "hqa.complete-hqa-contract.v1",
        "selector": "tests",
        "unexpected_skip_or_xfail_fails": True,
    }


def build_pytest_argv(
    *,
    python: Path,
    driver: Path,
    junit: Path,
    basetemp: Path,
) -> list[str]:
    """Build the unselectable complete-suite invocation."""

    return [
        str(python),
        "-X",
        "int_max_str_digits=0",
        "-I",
        "-B",
        str(driver),
        "-q",
        "-rs",
        "--import-mode=importlib",
        "-p",
        "no:cacheprovider",
        "tests",
        "--junitxml",
        str(junit),
        "--basetemp",
        str(basetemp),
    ]


def run_self_test() -> dict[str, str]:
    nodes = sorted([*EXPECTED_SKIPS, "self-test::passes"])
    outcomes = [
        {
            "node_id": node_id,
            "outcome": "skipped" if node_id in EXPECTED_SKIPS else "passed",
            "reason": EXPECTED_SKIPS.get(node_id),
        }
        for node_id in nodes
    ]
    population = validate_population(
        {
            "schema_version": POPULATION_SCHEMA,
            "collected_node_ids": nodes,
            "deselected_node_ids": [],
            "outcomes": outcomes,
        },
        expected_skips=EXPECTED_SKIPS,
        minimum_passed=1,
    )
    suite = ET.Element(
        "testsuite",
        {
            "errors": "0",
            "failures": "0",
            "skipped": "2",
            "tests": "3",
        },
    )
    for node_id in nodes:
        testcase = ET.SubElement(suite, "testcase", {"name": node_id})
        properties = ET.SubElement(testcase, "properties")
        ET.SubElement(
            properties,
            "property",
            {"name": "hqa_node_id", "value": node_id},
        )
        if node_id in EXPECTED_SKIPS:
            ET.SubElement(
                testcase,
                "skipped",
                {
                    "message": EXPECTED_SKIPS[node_id],
                    "type": "pytest.skip",
                },
            )
    validate_junit(
        ET.tostring(suite, encoding="utf-8"),
        pytest_exit=0,
        population_result=population,
        expected_skip_reasons=tuple(EXPECTED_SKIPS.values()),
    )
    return {
        "schema_version": "hqa.complete-hqa-self-test.v1",
        "status": "pass",
    }


def _dispatch_public(
    public_argv: Sequence[str], *, repository_root: Path
) -> int:
    if list(public_argv) == ["--describe"]:
        sys.stdout.buffer.write(_canonical_json(describe_contract()) + b"\n")
        return 0
    if list(public_argv) == ["--self-test"]:
        sys.stdout.buffer.write(_canonical_json(run_self_test()) + b"\n")
        return 0
    parsed = parse_run_arguments(public_argv)
    result = run_complete_gate(
        root=repository_root,
        parsed=parsed,
        public_argv=public_argv,
    )
    sys.stdout.buffer.write(_canonical_json(result) + b"\n")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    os.umask(0o077)
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if (
            len(arguments) < 5
            or arguments[0] != "--repository-root"
            or arguments[2] != "--public-entrypoint"
            or arguments[4] != "--public-argv"
        ):
            raise GateError("internal_invocation_invalid")
        repository_root = Path(arguments[1]).resolve(strict=True)
        public_entrypoint = Path(arguments[3]).resolve(strict=True)
        helper = Path(__file__).resolve(strict=True)
        if (
            helper != repository_root / "scripts" / "complete_hqa_gate.py"
            or public_entrypoint
            != repository_root / "scripts" / "verify_agent_v02_complete_hqa.sh"
        ):
            raise GateError("authority_path_invalid")
        return _dispatch_public(
            arguments[5:],
            repository_root=repository_root,
        )
    except (GateError, OSError) as exc:
        code = str(exc) if isinstance(exc, GateError) else "path_resolution_failed"
        sys.stderr.write("complete_hqa_error=%s\n" % code)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
