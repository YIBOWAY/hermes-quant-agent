from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping, Sequence, Tuple
import xml.etree.ElementTree as ET


_KIND = "agent_v0_2_v0_v2_validation_binding"
_VERDICT_KIND = "agent_v0_2_v0_v2_independent_verdict"
_REPOSITORIES = frozenset({"hqa", "platform", "hermes"})
_VERDICT_CHECKS = frozenset(
    {
        "closed_schemas",
        "canonical_digests_match",
        "source_coordinates_match",
        "controlled_checkouts_clean",
        "remote_publication_matches",
        "tree_archive_digests_match",
        "junit_hashes_counts_commands_match",
        "runtime_fail_closed",
        "write_ready_false",
    }
)
_HEX40_RE = re.compile(r"[0-9a-f]{40}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_EVIDENCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_TEXT_BYTES = 4_096
_SECRET_ARG_PARTS = (
    "authorization",
    "api-key",
    "api_key",
    "password",
    "private-key",
    "private_key",
    "secret",
    "token=",
)


class ReleaseEvidenceError(ValueError):
    pass


def _fail(message: str) -> None:
    raise ReleaseEvidenceError(message)


def _hex(value: Any, pattern: re.Pattern[str], field: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail("{} is not canonical".format(field))
    return value


def _text(value: Any, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or not value.isprintable()
        or len(value.encode("utf-8")) > _MAX_TEXT_BYTES
    ):
        _fail("{} is invalid".format(field))
    return value


def _repo_relative(value: Any, field: str) -> str:
    text = _text(value, field)
    path = PurePosixPath(text)
    if (
        text.startswith("/")
        or "\\" in text
        or path.as_posix() != text
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        _fail("{} must be repository-relative".format(field))
    return text


def _absolute_path(value: Any, field: str) -> Path:
    if not isinstance(value, (str, Path)):
        _fail("{} must be path-like".format(field))
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        _fail("{} must be absolute".format(field))
    return path.resolve(strict=False)


def _argv(value: Any, field: str) -> Tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not value:
        _fail("{} must be a non-empty argv array".format(field))
    result = tuple(_text(item, field) for item in value)
    lowered = "\0".join(result).casefold()
    if any(part in lowered for part in _SECRET_ARG_PARTS):
        _fail("{} contains a secret-like argument".format(field))
    return result


def _commands(value: Any, field: str) -> Tuple[Tuple[str, ...], ...]:
    if not isinstance(value, (tuple, list)):
        _fail("{} must be an argv list".format(field))
    return tuple(_argv(item, field) for item in value)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def _sha256_file(path: Path, maximum: int) -> str:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or metadata.st_size > maximum
    ):
        _fail("evidence artifact is not a bounded owner file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                _fail("evidence artifact is oversized")
            digest.update(chunk)
    return digest.hexdigest()


def _junit_counts(path: Path) -> Tuple[int, int, int, int, int]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ReleaseEvidenceError("evidence artifact is not valid JUnit XML") from exc
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        _fail("evidence artifact contains no test suite")
    totals = {name: 0 for name in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for field in totals:
            raw = suite.get(field)
            if raw is None or not raw.isdigit():
                _fail("JUnit {} count is invalid".format(field))
            totals[field] += int(raw)
    passed = (
        totals["tests"]
        - totals["failures"]
        - totals["errors"]
        - totals["skipped"]
    )
    if passed < 0:
        _fail("JUnit counts are inconsistent")
    return (
        passed,
        totals["failures"],
        totals["errors"],
        totals["skipped"],
        totals["tests"],
    )


@dataclass(frozen=True)
class EvidenceSpec:
    evidence_id: str
    repo: str
    source_head_commit: str
    source_tree_oid: str
    source_archive_sha256: str
    cwd: Path
    command: Tuple[str, ...]
    setup_commands: Tuple[Tuple[str, ...], ...]
    cleanup_commands: Tuple[Tuple[str, ...], ...]
    exit_code: int
    artifact_path: Path

    def __post_init__(self) -> None:
        if type(self.evidence_id) is not str or _EVIDENCE_ID_RE.fullmatch(
            self.evidence_id
        ) is None:
            _fail("evidence_id is invalid")
        if self.repo not in _REPOSITORIES:
            _fail("evidence repo is invalid")
        _hex(self.source_head_commit, _HEX40_RE, "source_head_commit")
        _hex(self.source_tree_oid, _HEX40_RE, "source_tree_oid")
        _hex(self.source_archive_sha256, _HEX64_RE, "source_archive_sha256")
        object.__setattr__(self, "cwd", _absolute_path(self.cwd, "cwd"))
        object.__setattr__(self, "command", _argv(self.command, "command"))
        object.__setattr__(
            self,
            "setup_commands",
            _commands(self.setup_commands, "setup_commands"),
        )
        object.__setattr__(
            self,
            "cleanup_commands",
            _commands(self.cleanup_commands, "cleanup_commands"),
        )
        if type(self.exit_code) is not int or not 0 <= self.exit_code <= 255:
            _fail("exit_code is invalid")
        object.__setattr__(
            self,
            "artifact_path",
            _absolute_path(self.artifact_path, "artifact_path"),
        )


@dataclass(frozen=True)
class SourceCoordinate:
    repo: str
    head_commit: str
    tree_oid: str
    archive_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "head_commit": self.head_commit,
            "tree_oid": self.tree_oid,
            "archive_sha256": self.archive_sha256,
        }


@dataclass(frozen=True)
class ValidationEvidence:
    evidence_id: str
    repo: str
    source_head_commit: str
    source_tree_oid: str
    source_archive_sha256: str
    cwd: str
    command: Tuple[str, ...]
    setup_commands: Tuple[Tuple[str, ...], ...]
    cleanup_commands: Tuple[Tuple[str, ...], ...]
    exit_code: int
    passed: int
    failed: int
    errors: int
    skipped: int
    total: int
    artifact_format: str
    artifact_path: str
    artifact_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "repo": self.repo,
            "source_head_commit": self.source_head_commit,
            "source_tree_oid": self.source_tree_oid,
            "source_archive_sha256": self.source_archive_sha256,
            "cwd": self.cwd,
            "command": list(self.command),
            "setup_commands": [list(item) for item in self.setup_commands],
            "cleanup_commands": [list(item) for item in self.cleanup_commands],
            "exit_code": self.exit_code,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "total": self.total,
            "artifact_format": self.artifact_format,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True)
class ValidationBinding:
    schema_version: int
    kind: str
    identity_manifest_path: str
    identity_manifest_file_sha256: str
    identity_manifest_digest: str
    repositories: Tuple[SourceCoordinate, ...]
    evidence: Tuple[ValidationEvidence, ...]
    binding_digest: str

    def to_dict(self) -> dict[str, Any]:
        return _binding_document(self, include_digest=True)

    def to_json_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())


def _binding_document(
    binding: ValidationBinding, *, include_digest: bool
) -> dict[str, Any]:
    document = {
        "schema_version": binding.schema_version,
        "kind": binding.kind,
        "identity_manifest_path": binding.identity_manifest_path,
        "identity_manifest_file_sha256": binding.identity_manifest_file_sha256,
        "identity_manifest_digest": binding.identity_manifest_digest,
        "repositories": [item.to_dict() for item in binding.repositories],
        "evidence": [item.to_dict() for item in binding.evidence],
    }
    if include_digest:
        document["binding_digest"] = binding.binding_digest
    return document


def _source_coordinate(value: Mapping[str, Any]) -> SourceCoordinate:
    if set(value) != {"repo", "head_commit", "tree_oid", "archive_sha256"}:
        _fail("repository coordinate fields are invalid")
    if value["repo"] not in _REPOSITORIES:
        _fail("repository coordinate repo is invalid")
    return SourceCoordinate(
        repo=value["repo"],
        head_commit=_hex(value["head_commit"], _HEX40_RE, "head_commit"),
        tree_oid=_hex(value["tree_oid"], _HEX40_RE, "tree_oid"),
        archive_sha256=_hex(
            value["archive_sha256"], _HEX64_RE, "archive_sha256"
        ),
    )


def build_validation_binding(
    *,
    identity_manifest_path: str,
    identity_manifest_file_sha256: str,
    identity_manifest_digest: str,
    identity_repositories: Sequence[Mapping[str, Any]],
    evidence_specs: Sequence[EvidenceSpec],
) -> ValidationBinding:
    manifest_path = _repo_relative(identity_manifest_path, "identity_manifest_path")
    manifest_file_sha256 = _hex(
        identity_manifest_file_sha256,
        _HEX64_RE,
        "identity_manifest_file_sha256",
    )
    manifest_digest = _hex(
        identity_manifest_digest, _HEX64_RE, "identity_manifest_digest"
    )
    repositories = tuple(
        sorted(
            (_source_coordinate(item) for item in identity_repositories),
            key=lambda item: item.repo,
        )
    )
    if {item.repo for item in repositories} != _REPOSITORIES or len(
        repositories
    ) != 3:
        _fail("exactly three repository coordinates are required")
    coordinates = {item.repo: item for item in repositories}
    records = []
    seen_ids = set()
    for spec in evidence_specs:
        if type(spec) is not EvidenceSpec:
            _fail("evidence_specs must contain EvidenceSpec values")
        if spec.evidence_id in seen_ids:
            _fail("evidence_id is duplicated")
        seen_ids.add(spec.evidence_id)
        coordinate = coordinates[spec.repo]
        if (
            spec.source_head_commit != coordinate.head_commit
            or spec.source_tree_oid != coordinate.tree_oid
            or spec.source_archive_sha256 != coordinate.archive_sha256
        ):
            _fail("evidence source does not match the identity manifest")
        artifact = spec.artifact_path.resolve(strict=True)
        digest = _sha256_file(artifact, _MAX_ARTIFACT_BYTES)
        passed, failed, errors, skipped, total = _junit_counts(artifact)
        if spec.exit_code != 0 or failed or errors:
            _fail("primary validation evidence is not successful")
        records.append(
            ValidationEvidence(
                evidence_id=spec.evidence_id,
                repo=spec.repo,
                source_head_commit=spec.source_head_commit,
                source_tree_oid=spec.source_tree_oid,
                source_archive_sha256=spec.source_archive_sha256,
                cwd=str(spec.cwd),
                command=spec.command,
                setup_commands=spec.setup_commands,
                cleanup_commands=spec.cleanup_commands,
                exit_code=spec.exit_code,
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                total=total,
                artifact_format="pytest-junit-xml",
                artifact_path=str(artifact),
                artifact_sha256=digest,
            )
        )
    evidence = tuple(sorted(records, key=lambda item: (item.repo, item.evidence_id)))
    if {item.repo for item in evidence} != _REPOSITORIES:
        _fail("primary evidence is required for all three repositories")
    unsigned = ValidationBinding(
        schema_version=1,
        kind=_KIND,
        identity_manifest_path=manifest_path,
        identity_manifest_file_sha256=manifest_file_sha256,
        identity_manifest_digest=manifest_digest,
        repositories=repositories,
        evidence=evidence,
        binding_digest="",
    )
    digest = hashlib.sha256(
        _canonical_bytes(_binding_document(unsigned, include_digest=False))
    ).hexdigest()
    return ValidationBinding(
        schema_version=unsigned.schema_version,
        kind=unsigned.kind,
        identity_manifest_path=unsigned.identity_manifest_path,
        identity_manifest_file_sha256=unsigned.identity_manifest_file_sha256,
        identity_manifest_digest=unsigned.identity_manifest_digest,
        repositories=unsigned.repositories,
        evidence=unsigned.evidence,
        binding_digest=digest,
    )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _fail("validation binding JSON contains duplicate keys")
        value[key] = item
    return value


def _evidence_record(value: Mapping[str, Any]) -> ValidationEvidence:
    expected = {
        "evidence_id",
        "repo",
        "source_head_commit",
        "source_tree_oid",
        "source_archive_sha256",
        "cwd",
        "command",
        "setup_commands",
        "cleanup_commands",
        "exit_code",
        "passed",
        "failed",
        "errors",
        "skipped",
        "total",
        "artifact_format",
        "artifact_path",
        "artifact_sha256",
    }
    if set(value) != expected:
        _fail("validation evidence fields are invalid")
    evidence_id = value["evidence_id"]
    if type(evidence_id) is not str or _EVIDENCE_ID_RE.fullmatch(evidence_id) is None:
        _fail("evidence_id is invalid")
    if value["repo"] not in _REPOSITORIES:
        _fail("evidence repo is invalid")
    counts = []
    for field in ("passed", "failed", "errors", "skipped", "total"):
        item = value[field]
        if type(item) is not int or item < 0:
            _fail("evidence counts are invalid")
        counts.append(item)
    if counts[4] != sum(counts[:4]):
        _fail("evidence counts are inconsistent")
    if type(value["exit_code"]) is not int or not 0 <= value["exit_code"] <= 255:
        _fail("exit_code is invalid")
    if value["exit_code"] != 0 or value["failed"] or value["errors"]:
        _fail("primary validation evidence is not successful")
    if value["artifact_format"] != "pytest-junit-xml":
        _fail("artifact_format is unsupported")
    return ValidationEvidence(
        evidence_id=evidence_id,
        repo=value["repo"],
        source_head_commit=_hex(
            value["source_head_commit"], _HEX40_RE, "source_head_commit"
        ),
        source_tree_oid=_hex(
            value["source_tree_oid"], _HEX40_RE, "source_tree_oid"
        ),
        source_archive_sha256=_hex(
            value["source_archive_sha256"],
            _HEX64_RE,
            "source_archive_sha256",
        ),
        cwd=str(_absolute_path(value["cwd"], "cwd")),
        command=_argv(value["command"], "command"),
        setup_commands=_commands(value["setup_commands"], "setup_commands"),
        cleanup_commands=_commands(value["cleanup_commands"], "cleanup_commands"),
        exit_code=value["exit_code"],
        passed=value["passed"],
        failed=value["failed"],
        errors=value["errors"],
        skipped=value["skipped"],
        total=value["total"],
        artifact_format=value["artifact_format"],
        artifact_path=str(_absolute_path(value["artifact_path"], "artifact_path")),
        artifact_sha256=_hex(
            value["artifact_sha256"], _HEX64_RE, "artifact_sha256"
        ),
    )


def validate_validation_binding_document(value: Any) -> ValidationBinding:
    expected = {
        "schema_version",
        "kind",
        "identity_manifest_path",
        "identity_manifest_file_sha256",
        "identity_manifest_digest",
        "repositories",
        "evidence",
        "binding_digest",
    }
    if type(value) is not dict or set(value) != expected:
        _fail("validation binding fields are invalid")
    if value["schema_version"] != 1 or value["kind"] != _KIND:
        _fail("validation binding schema is unsupported")
    if type(value["repositories"]) is not list:
        _fail("repositories must be a list")
    repositories = tuple(_source_coordinate(item) for item in value["repositories"])
    if (
        tuple(item.repo for item in repositories) != tuple(sorted(_REPOSITORIES))
        or len(repositories) != 3
    ):
        _fail("repository coordinates must be complete and sorted")
    if type(value["evidence"]) is not list:
        _fail("evidence must be a list")
    evidence = tuple(_evidence_record(item) for item in value["evidence"])
    if tuple((item.repo, item.evidence_id) for item in evidence) != tuple(
        sorted((item.repo, item.evidence_id) for item in evidence)
    ):
        _fail("evidence must be sorted")
    if len({item.evidence_id for item in evidence}) != len(evidence):
        _fail("evidence_id is duplicated")
    coordinates = {item.repo: item for item in repositories}
    if {item.repo for item in evidence} != _REPOSITORIES:
        _fail("primary evidence is required for all three repositories")
    for item in evidence:
        coordinate = coordinates[item.repo]
        if (
            item.source_head_commit != coordinate.head_commit
            or item.source_tree_oid != coordinate.tree_oid
            or item.source_archive_sha256 != coordinate.archive_sha256
        ):
            _fail("evidence source does not match the identity manifest")
    binding = ValidationBinding(
        schema_version=1,
        kind=_KIND,
        identity_manifest_path=_repo_relative(
            value["identity_manifest_path"], "identity_manifest_path"
        ),
        identity_manifest_file_sha256=_hex(
            value["identity_manifest_file_sha256"],
            _HEX64_RE,
            "identity_manifest_file_sha256",
        ),
        identity_manifest_digest=_hex(
            value["identity_manifest_digest"],
            _HEX64_RE,
            "identity_manifest_digest",
        ),
        repositories=repositories,
        evidence=evidence,
        binding_digest=_hex(value["binding_digest"], _HEX64_RE, "binding_digest"),
    )
    expected_digest = hashlib.sha256(
        _canonical_bytes(_binding_document(binding, include_digest=False))
    ).hexdigest()
    if binding.binding_digest != expected_digest:
        _fail("validation binding digest does not match")
    return binding


def parse_validation_binding_json(raw: Any) -> ValidationBinding:
    if isinstance(raw, str):
        encoded = raw.encode("utf-8", errors="strict")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise TypeError("validation binding JSON must be bytes or text")
    if not encoded or len(encoded) > _MAX_DOCUMENT_BYTES:
        _fail("validation binding JSON is empty or oversized")
    try:
        value = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: _fail(
                "validation binding contains a non-finite number"
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReleaseEvidenceError("validation binding JSON is invalid") from exc
    return validate_validation_binding_document(value)


def parse_independent_verdict_json(raw: Any) -> dict[str, Any]:
    """Parse the closed, non-authorizing independent close-out verdict."""
    if isinstance(raw, str):
        encoded = raw.encode("utf-8", errors="strict")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise TypeError("independent verdict JSON must be bytes or text")
    if not encoded or len(encoded) > _MAX_DOCUMENT_BYTES:
        _fail("independent verdict JSON is empty or oversized")
    try:
        value = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: _fail(
                "independent verdict contains a non-finite number"
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReleaseEvidenceError("independent verdict JSON is invalid") from exc
    expected = {
        "schema_version",
        "kind",
        "verdict",
        "release_authorized",
        "identity_manifest",
        "validation_binding",
        "reviewer_checks",
    }
    if type(value) is not dict or set(value) != expected:
        _fail("independent verdict fields are invalid")
    if value["schema_version"] != 1 or value["kind"] != _VERDICT_KIND:
        _fail("independent verdict schema is unsupported")
    if value["verdict"] != "CLEAR":
        _fail("independent verdict is not clear")
    if value["release_authorized"] is not False:
        _fail("independent verdict never authorizes a live release")

    identity = value["identity_manifest"]
    if type(identity) is not dict or set(identity) != {
        "path",
        "file_sha256",
        "manifest_digest",
    }:
        _fail("identity verdict reference fields are invalid")
    normalized_identity = {
        "path": _repo_relative(identity["path"], "identity_manifest.path"),
        "file_sha256": _hex(
            identity["file_sha256"], _HEX64_RE, "identity_manifest.file_sha256"
        ),
        "manifest_digest": _hex(
            identity["manifest_digest"],
            _HEX64_RE,
            "identity_manifest.manifest_digest",
        ),
    }

    binding = value["validation_binding"]
    if type(binding) is not dict or set(binding) != {
        "path",
        "file_sha256",
        "binding_digest",
    }:
        _fail("validation verdict reference fields are invalid")
    normalized_binding = {
        "path": _repo_relative(binding["path"], "validation_binding.path"),
        "file_sha256": _hex(
            binding["file_sha256"],
            _HEX64_RE,
            "validation_binding.file_sha256",
        ),
        "binding_digest": _hex(
            binding["binding_digest"],
            _HEX64_RE,
            "validation_binding.binding_digest",
        ),
    }

    checks = value["reviewer_checks"]
    if (
        type(checks) is not dict
        or set(checks) != _VERDICT_CHECKS
        or any(item is not True for item in checks.values())
    ):
        _fail("independent verdict checks are incomplete")
    return {
        "schema_version": 1,
        "kind": _VERDICT_KIND,
        "verdict": "CLEAR",
        "release_authorized": False,
        "identity_manifest": normalized_identity,
        "validation_binding": normalized_binding,
        "reviewer_checks": {key: True for key in sorted(_VERDICT_CHECKS)},
    }


__all__ = (
    "EvidenceSpec",
    "ReleaseEvidenceError",
    "SourceCoordinate",
    "ValidationBinding",
    "ValidationEvidence",
    "build_validation_binding",
    "parse_independent_verdict_json",
    "parse_validation_binding_json",
    "validate_validation_binding_document",
)
